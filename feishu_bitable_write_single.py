import json
import os
import base64
import io as pyio
import uuid
import re
import time
import threading
import traceback
from datetime import datetime
import requests
from comfy_api.latest import io
import folder_paths

# Delay import numpy/PIL/torchaudio/torch to avoid circular import issues or load failures
np = None
Image = None
torchaudio = None
torch = None

def _lazy_import_numpy_pil():
    global np, Image
    if np is None:
        import numpy as n
        np = n
    if Image is None:
        from PIL import Image as I
        Image = I

def _lazy_import_torch():
    global torchaudio, torch
    try:
        import torchaudio as ta
        import torch as t
        torchaudio = ta
        torch = t
        return True
    except ImportError:
        return False

MAX_SAFE_INT = 9007199254740991

TYPE_OPTIONS_DISPLAY = ["文本","邮箱","数字","单选","多选","日期","复选框","人员","电话","链接","附件"]
TYPE_ALIASES = {
    "string": "text",
    "rich_text": "text",
    "float": "number",
    "int": "number",
    "datetime": "date",
    "time": "date",
    "文本": "text",
    "富文本": "text",
    "邮箱": "email",
    "邮件": "email",
    "数字": "number",
    "数值": "number",
    "单选": "single_select",
    "多选": "multi_select",
    "日期": "date",
    "时间": "date",
    "复选框": "checkbox",
    "勾选": "checkbox",
    "人员": "user",
    "用户": "user",
    "电话": "phone",
    "手机": "phone",
    "链接": "url",
    "网址": "url",
    "附件": "attachment",
}

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
    def __eq__(self, __value: object) -> bool:
        return True
    def __str__(self):
        return "*"

ANY = AnyType("*")

class FeishuBitableClient:
    def __init__(self, app_id=None, app_secret=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token_cache = None
        self._mock = str(os.getenv("FEISHU_BITABLE_MOCK", "")).strip().lower() in ("1", "true", "yes")

    def get_token(self):
        try:
            if self._mock:
                print("[FeishuBitable][MOCK] Using mock token")
                return "MOCK_TOKEN"
            if self._token_cache:
                print("[FeishuBitable] Using cached tenant_access_token")
                return self._token_cache
            if not (self.app_id and self.app_secret):
                print("[FeishuBitable] Missing AppID/AppSecret in config")
                return None
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            data = {"app_id": self.app_id, "app_secret": self.app_secret}
            print("[FeishuBitable] Requesting tenant_access_token...")
            res = requests.post(url, json=data, timeout=20)
            print(f"[FeishuBitable] token status={res.status_code}")
            j = {}
            try:
                j = res.json()
            except Exception:
                print(f"[FeishuBitable] token response not json: {res.text[:200]}")
            token = j.get("tenant_access_token")
            if token:
                self._token_cache = token
                print("[FeishuBitable] token acquired")
            else:
                print(f"[FeishuBitable] token missing in response: {str(j)[:200]}")
            return token
        except Exception as e:
            print(f"[FeishuBitable] token error: {e}")
            return None
    
    def headers(self):
        t = self.get_token()
        if t:
            return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
        return {"Content-Type": "application/json"}

    def get_wiki_node_info(self, wiki_token):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Get wiki node: {wiki_token}")
            return "mock_bitable_token"
        t = self.get_token()
        if not t:
            return None
        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
        # 传入的是 wiki 链接里的 token，此时不要设置 obj_type 为 bitable
        # 按官方文档，wiki token 默认按 wiki 类型查询，会返回 node，其中包含嵌入文档的 obj_token
        params = {"token": wiki_token}
        headers = {"Authorization": f"Bearer {t}"}
        try:
            print(f"[FeishuBitable] Get wiki node: {wiki_token}")
            res = requests.get(url, params=params, headers=headers, timeout=20)
            print(f"[FeishuBitable] Get wiki node status={res.status_code}")
            j = res.json()
            if j.get("code") == 0:
                node = j.get("data", {}).get("node", {})
                obj_token = node.get("obj_token")
                obj_type = node.get("obj_type")
                if obj_type == "bitable" and obj_token:
                    print(f"[FeishuBitable] Resolved wiki token to bitable token: {obj_token}")
                    return obj_token
            print(f"[FeishuBitable] Get wiki node failed: {res.text[:200]}")
        except Exception as e:
            print(f"[FeishuBitable] Get wiki node error: {e}")
        return None

    def list_files(self, file_type="bitable"):
        t = self.get_token()
        if not t:
            return []
        url = "https://open.feishu.cn/open-apis/drive/v1/files"
        # q syntax: type="bitable" AND trashed=false
        # but let's just list simple first. 
        # API docs: GET /open-apis/drive/v1/files
        # q parameter is optional.
        headers = {"Authorization": f"Bearer {t}"}
        all_files = []
        page_token = ""
        try:
            while True:
                params = {"page_size": 50}
                if page_token:
                    params["page_token"] = page_token
                # q is tricky to encode sometimes, let's filter client side if needed or try simple q
                # q='type="bitable"'
                # params["q"] = 'type="bitable"' 
                # Let's try without q first to avoid 400 if scope is limited, 
                # OR with q if we want to be efficient. 
                # User might have many files. Better use q.
                # If 400, fallback to no q? No, let's just try q.
                
                # Correct q format: type = "bitable"
                # But actually, listing all files requires drive scope.
                # If the user only gave bitable permission, this might fail.
                # Let's wrap in try-except.
                
                print(f"[FeishuBitable] Listing files (attempting to find app_token)...")
                # Using a safer q
                # params["q"] = "type = \"bitable\"" # This might need URL encoding? requests handles it.
                
                res = requests.get(url, headers=headers, params=params, timeout=10)
                if res.status_code != 200:
                    print(f"[FeishuBitable] List files failed: {res.status_code} {res.text}")
                    break
                
                j = res.json()
                if j.get("code") != 0:
                    print(f"[FeishuBitable] List files API error: {j}")
                    break
                    
                files = j.get("data", {}).get("files", [])
                all_files.extend(files)
                
                page_token = j.get("data", {}).get("next_page_token")
                if not page_token:
                    break
        except Exception as e:
            print(f"[FeishuBitable] List files exception: {e}")
            
        # Filter for bitable if we didn't use q
        return [f for f in all_files if f.get("type") == "bitable"]

    def list_tables(self, app_token):
        if self._mock:
            return [{"table_id": "tbl_mock", "name": "MockTable"}]
        t = self.get_token()
        if not t:
            return []
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables"
        headers = {"Authorization": f"Bearer {t}"}
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                j = res.json()
                if j.get("code") == 0:
                    return j.get("data", {}).get("items", [])
        except Exception as e:
            print(f"[FeishuBitable] List tables error for {app_token}: {e}")
        return []

    def find_app_token_by_table_id(self, table_id):
        print(f"[FeishuBitable] Auto-discovering app_token for table_id: {table_id}...")
        files = self.list_files()
        print(f"[FeishuBitable] Found {len(files)} bitable files accessible by bot.")
        for f in files:
            token = f.get("token")
            name = f.get("name")
            print(f"[FeishuBitable] Checking file: {name} ({token})")
            tables = self.list_tables(token)
            for tbl in tables:
                if tbl.get("table_id") == table_id:
                    print(f"[FeishuBitable] MATCH FOUND! app_token is {token}")
                    return token
        print("[FeishuBitable] No matching table_id found in accessible files.")
        return None

    def resolve_app_token(self, token_input, table_id=None):
        if not token_input:
            return token_input
        s = token_input.strip()
        
        # 1. Try to use it as is (if it's already an app_token)
        # We can't easily validate format without regex, but let's assume if it works it works.
        # But here we want to handle Wiki URLs.
        
        wiki_token = None
        if "/wiki/" in s:
            try:
                parts = s.split("/wiki/")
                if len(parts) > 1:
                    wiki_token = parts[1].split("?")[0].split("/")[0]
            except:
                pass
        
        # If we found a wiki token, try to resolve it via get_node
        if wiki_token:
            print(f"[FeishuBitable] Detected wiki token: {wiki_token}")
            resolved = self.get_wiki_node_info(wiki_token)
            if resolved:
                return resolved
            print("[FeishuBitable] Wiki resolution failed. Trying auto-discovery via Drive API...")
            # Fallback: if we have a table_id, try to find the file in Drive
            if table_id:
                discovered = self.find_app_token_by_table_id(table_id)
                if discovered:
                    return discovered
        
        return s

    def list_fields(self, app_token, table_id):
        if self._mock:
            print("[FeishuBitable][MOCK] List fields")
            return {"标题", "备注"}
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        try:
            print(f"[FeishuBitable] List fields: app_token={app_token[:6]}... table_id={table_id}")
            res = requests.get(url, headers=headers, timeout=20)
            print(f"[FeishuBitable] List fields status={res.status_code}")
            j = res.json()
            data = j.get("data", {})
            items = data.get("items", []) or data.get("records", []) or data.get("fields", [])
            names = set()
            for it in items:
                field_obj = it.get("field") if isinstance(it, dict) and "field" in it else it
                if isinstance(field_obj, dict):
                    n = field_obj.get("field_name") or field_obj.get("name")
                    if n:
                        names.add(n)
            return names
        except Exception:
            print("[FeishuBitable] List fields error")
            return set()
    
    def list_fields_map(self, app_token, table_id):
        if self._mock:
            print("[FeishuBitable][MOCK] List fields map")
            return {"标题": "fld_title", "备注": "fld_note"}
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        try:
            print(f"[FeishuBitable] List fields map: app_token={app_token[:6]}... table_id={table_id}")
            res = requests.get(url, headers=headers, timeout=20)
            print(f"[FeishuBitable] List fields map status={res.status_code}")
            try:
                print(f"[FeishuBitable] fields_raw={res.text[:200]}")
            except Exception:
                pass
            j = res.json()
            data = j.get("data", {})
            items = data.get("items", []) or data.get("records", []) or data.get("fields", [])
            name_to_id = {}
            def _norm(s):
                try:
                    t = str(s)
                    t = t.replace("：", ":")
                    t = t.strip()
                    if len(t) >= 2 and t[1] == ":" and t[0].isalpha():
                        t = t[2:].strip()
                    return t
                except Exception:
                    return s
            for it in items:
                field_obj = it.get("field") if isinstance(it, dict) and "field" in it else it
                fid = field_obj.get("field_id") or field_obj.get("id")
                n = field_obj.get("field_name") or field_obj.get("name")
                if fid and n:
                    name_to_id[n] = fid
                    nn = _norm(n)
                    if nn and nn != n:
                        name_to_id[nn] = fid
            print(f"[FeishuBitable] name_to_id keys={list(name_to_id.keys())[:6]} total={len(name_to_id)}")
            return name_to_id
        except Exception:
            print("[FeishuBitable] List fields map error")
            return {}
    
    def list_fields_info(self, app_token, table_id):
        if self._mock:
            print("[FeishuBitable][MOCK] List fields info")
            return {"标题": {"id": "fld_title", "type": 1, "ui_type": "Text"}, "备注": {"id": "fld_note", "type": 1, "ui_type": "Text"}}
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        try:
            print(f"[FeishuBitable] List fields info: app_token={app_token[:6]}... table_id={table_id}")
            res = requests.get(url, headers=headers, timeout=20)
            print(f"[FeishuBitable] List fields info status={res.status_code}")
            j = res.json()
            data = j.get("data", {})
            items = data.get("items", []) or data.get("records", []) or data.get("fields", [])
            info = {}
            for it in items:
                field_obj = it.get("field") if isinstance(it, dict) and "field" in it else it
                fid = field_obj.get("field_id") or field_obj.get("id")
                n = field_obj.get("field_name") or field_obj.get("name")
                t = field_obj.get("type")
                ui = field_obj.get("ui_type")
                if n:
                    info[n] = {"id": fid, "type": t, "ui_type": ui}
            return info
        except Exception:
            print("[FeishuBitable] List fields info error")
            return {}

    def _map_field_type(self, tname):
        if not isinstance(tname, str):
            return {"type": 1, "ui_type": "Text"}
        s = tname.strip().lower()
        s = TYPE_ALIASES.get(s, s)
        mapping = {
            "text": {"type": 1, "ui_type": "Text"},
            "email": {"type": 1, "ui_type": "Email"},
            "number": {"type": 2, "ui_type": "Number"},
            "single_select": {"type": 3, "ui_type": "SingleSelect"},
            "multi_select": {"type": 4, "ui_type": "MultiSelect"},
            "date": {"type": 5, "ui_type": "DateTime"},
            "checkbox": {"type": 7, "ui_type": "Checkbox"},
            "user": {"type": 11, "ui_type": "User"},
            "phone": {"type": 13, "ui_type": "Phone"},
            "url": {"type": 15, "ui_type": "Url"},
            "attachment": {"type": 17, "ui_type": "Attachment"},
        }
        return mapping.get(s, {"type": 1, "ui_type": "Text"})

    def create_field(self, app_token, table_id, field_name, field_type="text"):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Create field: {field_name} type={field_type}")
            return 201, json.dumps({"code": 0})
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        type_info = self._map_field_type(field_type)
        payload = {
            "field_name": field_name,
            "type": type_info.get("type", 1),
        }
        # 对于附件(17)、人员(11)、单选(3)、多选(4)等，property 可能有特殊要求
        # 附件类型通常不需要 property 或传 null，但空字典 {} 可能会报错 AttachFieldPropertyError
        # 简单起见，如果 type=17，我们不传 property
        if type_info.get("type", 1) != 17:
             payload["property"] = {}
        try:
            print(f"[FeishuBitable] Create field: {field_name} type={field_type}")
            res = requests.post(url, json=payload, headers=headers, timeout=20)
            print(f"[FeishuBitable] Create field status={res.status_code} body={res.text[:200]}")
            return res.status_code, res.text
        except Exception as e:
            print(f"[FeishuBitable] Create field error: {e}")
            return 0, str(e)

    def ensure_fields(self, app_token, table_id, required_fields):
        existing = self.list_fields(app_token, table_id)
        created = []
        for f in required_fields:
            name = f.get("name") if isinstance(f, dict) else str(f)
            ftype = f.get("type", "text") if isinstance(f, dict) else "text"
            if name and name not in existing:
                code, text = self.create_field(app_token, table_id, name, ftype)
                created.append((name, code, text))
        return created

    def create_record(self, app_token, table_id, fields, view_id=None):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Create record: table_id={table_id} fields_count={len(fields)}")
            return 200, json.dumps({"code": 0, "data": {"record_id": "rec_mock"}})
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        body = {"fields": fields}
        if view_id:
            body["view_id"] = view_id
        print(f"[FeishuBitable] Create record: table_id={table_id} view_id={'set' if view_id else 'None'} fields_count={len(fields)}")
        res = requests.post(url, json=body, headers=headers, timeout=30)
        print(f"[FeishuBitable] Create record status={res.status_code} body={res.text[:200]}")
        return res.status_code, res.text

    def update_record(self, app_token, table_id, record_id, fields):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Update record: table_id={table_id} record_id={record_id}")
            return 200, json.dumps({"code": 0, "data": {"record_id": record_id}})
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        body = {"fields": fields}
        print(f"[FeishuBitable] Update record: table_id={table_id} record_id={record_id} fields_count={len(fields)}")
        res = requests.put(url, json=body, headers=headers, timeout=30)
        print(f"[FeishuBitable] Update record status={res.status_code} body={res.text[:200]}")
        return res.status_code, res.text

    def list_records(self, app_token, table_id, view_id=None, page_size=20, page_token=None, filter=None, sort=None, automatic_fields=None):
        if self._mock:
            print(f"[FeishuBitable][MOCK] List records: table_id={table_id} filter={filter}")
            return {"items": [{"record_id": "rec_mock_1"}, {"record_id": "rec_mock_2"}], "total": 2, "has_more": False}
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        params = {"page_size": page_size}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        if filter:
            params["filter"] = filter
        if sort:
            params["sort"] = sort
        if automatic_fields is not None:
            params["automatic_fields"] = "true" if bool(automatic_fields) else "false"
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code == 200:
                j = res.json()
                if j.get("code") == 0:
                    data = j.get("data", {})
                    return {
                        "items": data.get("items", []),
                        "total": data.get("total", 0),
                        "has_more": data.get("has_more", False),
                        "page_token": data.get("page_token", "")
                    }
                if automatic_fields is not None:
                    params.pop("automatic_fields", None)
                    res2 = requests.get(url, headers=headers, params=params, timeout=20)
                    if res2.status_code == 200:
                        j2 = res2.json()
                        if j2.get("code") == 0:
                            data2 = j2.get("data", {})
                            return {
                                "items": data2.get("items", []),
                                "total": data2.get("total", 0),
                                "has_more": data2.get("has_more", False),
                                "page_token": data2.get("page_token", "")
                            }
            print(f"[FeishuBitable] List records failed: {res.status_code} {res.text[:200]}")
        except Exception as e:
            print(f"[FeishuBitable] List records error: {e}")
        return None


    def batch_create_records(self, app_token, table_id, records, view_id=None):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Batch create: table_id={table_id} count={len(records)}")
            return 200, json.dumps({"code": 0, "data": {"records": [{"record_id": "rec_mock"}]}})
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
        body = {"records": [{"fields": r} for r in records]}
        if view_id:
            body["view_id"] = view_id
        print(f"[FeishuBitable] Batch create: table_id={table_id} view_id={'set' if view_id else 'None'} count={len(records)}")
        res = requests.post(url, json=body, headers=headers, timeout=30)
        print(f"[FeishuBitable] Batch create status={res.status_code} body={res.text[:200]}")
        return res.status_code, res.text

    def batch_update_records(self, app_token, table_id, records):
        if self._mock:
            print(f"[FeishuBitable][MOCK] Batch update: table_id={table_id} count={len(records)}")
            out_records = []
            for r in records:
                rid = ""
                if isinstance(r, dict):
                    rid = str(r.get("record_id") or "")
                out_records.append({"record_id": rid or "rec_mock"})
            return 200, json.dumps({"code": 0, "data": {"records": out_records}})
        headers = self.headers()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
        body = {"records": records}
        print(f"[FeishuBitable] Batch update: table_id={table_id} count={len(records)}")
        res = requests.post(url, json=body, headers=headers, timeout=30)
        print(f"[FeishuBitable] Batch update status={res.status_code} body={res.text[:200]}")
        return res.status_code, res.text
    
    def upload_attachment(self, app_token, image_bytes, filename=None):
        if self._mock:
            print("[FeishuBitable][MOCK] Upload attachment")
            return "box_mock_token"
        t = self.get_token()
        if not t:
            return None
        if not filename:
            filename = f"{uuid.uuid4().hex}.png"
        image_size = len(image_bytes)
        if image_size > 20 * 1024 * 1024:
            ft_chunk = self._upload_media_chunked(app_token, image_bytes, filename, "bitable_image", t=t)
            if ft_chunk:
                return ft_chunk
        url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
        headers = {"Authorization": f"Bearer {t}"}
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"file_name": filename, "parent_type": "bitable_image", "parent_node": app_token, "size": str(image_size)}
        try:
            res = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            j = res.json()
            if res.status_code == 200 and j.get("code") == 0:
                ft = j.get("data", {}).get("file_token")
                if ft:
                    print(f"[FeishuBitable] Upload attachment OK: {ft}")
                    return ft
            print(f"[FeishuBitable] Upload attachment fail: {res.status_code} {res.text[:200]}")
        except Exception as e:
            print(f"[FeishuBitable] Upload attachment error: {e}")
        return None

    def _upload_media_chunked(self, app_token, file_bytes, filename, parent_type, t=None):
        if self._mock:
            print("[FeishuBitable][MOCK] Chunked upload media")
            return "box_mock_token_chunked"
        if not t:
            t = self.get_token()
        if not t:
            return None
        file_size = len(file_bytes)
        print(f"[FeishuBitable] Start chunked upload for {filename} ({file_size} bytes) parent_type={parent_type}")
        try:
            url_prepare = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_prepare"
            headers_json = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
            data_prepare = {
                "file_name": filename,
                "parent_type": parent_type,
                "parent_node": app_token,
                "size": file_size
            }
            res_prep = requests.post(url_prepare, headers=headers_json, json=data_prepare, timeout=30)
            j_prep = res_prep.json()
            if res_prep.status_code != 200 or j_prep.get("code") != 0:
                print(f"[FeishuBitable] Upload prepare fail: {res_prep.text[:200]}")
                return None
            prep_data = j_prep.get("data", {}) or {}
            upload_id = prep_data.get("upload_id")
            block_size = prep_data.get("block_size") or (4 * 1024 * 1024)
            block_num = prep_data.get("block_num")
            if not upload_id:
                print(f"[FeishuBitable] Upload prepare missing upload_id: {str(j_prep)[:200]}")
                return None
            if not isinstance(block_num, int) or block_num <= 0:
                try:
                    block_num = int((file_size + block_size - 1) // block_size)
                except Exception:
                    block_num = 1
            print(f"[FeishuBitable] Upload prepare OK: upload_id={upload_id} block_size={block_size} blocks={block_num}")

            url_part = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_part"
            headers_part = {"Authorization": f"Bearer {t}"}

            for i in range(block_num):
                start = i * block_size
                end = min((i + 1) * block_size, file_size)
                chunk_data = file_bytes[start:end]
                files_part = {"file": (filename, chunk_data)}
                data_part = {"upload_id": upload_id, "seq": str(i), "size": str(len(chunk_data))}
                print(f"[FeishuBitable] Uploading part {i+1}/{block_num} ({len(chunk_data)} bytes)...")
                res_part = requests.post(url_part, headers=headers_part, files=files_part, data=data_part, timeout=120)
                j_part = res_part.json()
                if res_part.status_code != 200 or j_part.get("code") != 0:
                    print(f"[FeishuBitable] Upload part {i} fail: {res_part.text[:200]}")
                    return None

            url_finish = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_finish"
            data_finish = {"upload_id": upload_id, "block_num": block_num}
            res_fin = requests.post(url_finish, headers=headers_json, json=data_finish, timeout=60)
            j_fin = res_fin.json()
            if res_fin.status_code == 200 and j_fin.get("code") == 0:
                ft = j_fin.get("data", {}).get("file_token")
                if ft:
                    print(f"[FeishuBitable] Upload finish OK: {ft}")
                    return ft
            print(f"[FeishuBitable] Upload finish fail: {res_fin.text[:200]}")
            return None
        except Exception as e:
            print(f"[FeishuBitable] Chunked upload error: {e}")
            return None

    def upload_file(self, app_token, file_bytes, filename=None):
        if self._mock:
            print("[FeishuBitable][MOCK] Upload file")
            return "box_mock_token_file"
        t = self.get_token()
        if not t:
            return None
        if not filename:
            filename = f"{uuid.uuid4().hex}.bin"
        return self._upload_media_chunked(app_token, file_bytes, filename, "bitable_file", t=t)


class FeishuBitableConfigNode:
    CATEGORY = "maoyu/多维表格"
    TITLE = "飞书表格配置 (Feishu Bitable Config)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableConfigNode",
                display_name="Feishu Bitable 配置",
                category="maoyu/多维表格",
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                    io.String.Input("app_token", default="", tooltip="飞书多维表格 App Token"),
                    io.String.Input("table_id", default="", tooltip="数据表 ID"),
                    io.String.Input("view_id", default="", tooltip="视图 ID（可选）"),
                    io.String.Input("feishu_app_id", default="", tooltip="飞书应用 App ID（用于鉴权）", optional=True),
                    io.String.Input("feishu_app_secret", default="", tooltip="飞书应用 App Secret（用于鉴权）", optional=True),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, app_token: str, table_id: str, view_id: str, feishu_app_id: str, feishu_app_secret: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            # Deep copy bitable_items list to avoid side effects on upstream cache
            if "bitable_items" not in config:
                config["bitable_items"] = []
            else:
                config["bitable_items"] = list(config["bitable_items"])
            
            # 如果上游已经有 Record 节点生成的“空配置项”（只有 action 等），则合并进去
            # 否则创建一个新的配置项
            target_index = -1
            if config["bitable_items"]:
                # 寻找最后一个还没有 app_token 的项
                for idx in range(len(config["bitable_items"]) - 1, -1, -1):
                    if not config["bitable_items"][idx].get("app_token"):
                        target_index = idx
                        break
            
            if target_index == -1:
                target_item = {}
                config["bitable_items"].append(target_item)
            else:
                # Copy the item before modifying
                target_item = config["bitable_items"][target_index].copy()
                config["bitable_items"][target_index] = target_item
            
            if app_token.strip():
                target_item["app_token"] = app_token.strip()
            if table_id.strip():
                target_item["table_id"] = table_id.strip()
            if view_id.strip():
                target_item["view_id"] = view_id.strip()
            
            if feishu_app_id.strip():
                config["feishu_app_id"] = feishu_app_id.strip()
            if feishu_app_secret.strip():
                config["feishu_app_secret"] = feishu_app_secret.strip()
            return io.NodeOutput(config)

class FeishuBitableUpdateRowNode:
    CATEGORY = "maoyu/多维表格"
    TITLE = "更新指定行 (Update Row)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableUpdateRowNode",
                display_name="Feishu Bitable 更新行",
                category="maoyu/多维表格",
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                    io.Int.Input("record_index", default=0, tooltip="行号 (1开始，0无效)"),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, record_index: int, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_items" not in config:
                config["bitable_items"] = []
            else:
                config["bitable_items"] = list(config["bitable_items"])
            
            # 查找或创建一个配置项
            target_index = -1
            if config["bitable_items"]:
                for idx in range(len(config["bitable_items"]) - 1, -1, -1):
                    it = config["bitable_items"][idx]
                    if isinstance(it, dict) and (not (it.get("app_token") or "").strip()):
                        target_index = idx
                        break
                if target_index == -1:
                    target_index = len(config["bitable_items"]) - 1
            
            if target_index == -1:
                target_item = {}
                config["bitable_items"].append(target_item)
            else:
                target_item = config["bitable_items"][target_index].copy()
                config["bitable_items"][target_index] = target_item
            
            target_item["record_action"] = "update_index"
            target_item["record_index"] = record_index
            return io.NodeOutput(config)

class FeishuBitableUpdateIDNode:
    CATEGORY = "maoyu/多维表格"
    TITLE = "更新记录ID (Update ID)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableUpdateIDNode",
                display_name="Feishu Bitable 更新ID",
                category="maoyu/多维表格",
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                    io.String.Input("record_id", default="", tooltip="记录 ID (record_id)"),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, record_id: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_items" not in config:
                config["bitable_items"] = []
            else:
                config["bitable_items"] = list(config["bitable_items"])
            
            # 查找或创建一个配置项
            target_index = -1
            if config["bitable_items"]:
                for idx in range(len(config["bitable_items"]) - 1, -1, -1):
                    it = config["bitable_items"][idx]
                    if isinstance(it, dict) and (not (it.get("app_token") or "").strip()):
                        target_index = idx
                        break
                if target_index == -1:
                    target_index = len(config["bitable_items"]) - 1
            
            if target_index == -1:
                target_item = {}
                config["bitable_items"].append(target_item)
            else:
                target_item = config["bitable_items"][target_index].copy()
                config["bitable_items"][target_index] = target_item
            
            target_item["record_action"] = "update_id"
            target_item["record_id"] = (record_id or "").strip()
            return io.NodeOutput(config)

class FeishuBitableMatchNode:
    CATEGORY = "maoyu/多维表格"
    TITLE = "匹配字段更新 (Match Field)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableMatchNode",
                display_name="Feishu Bitable 匹配更新",
                category="maoyu/多维表格",
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                    io.String.Input("match_field", default="标题", tooltip="匹配字段名"),
                    io.String.Input("match_value", default="", tooltip="匹配字段值"),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, match_field: str, match_value: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_items" not in config:
                config["bitable_items"] = []
            else:
                config["bitable_items"] = list(config["bitable_items"])
            
            # 查找或创建一个配置项
            target_index = -1
            if config["bitable_items"]:
                for idx in range(len(config["bitable_items"]) - 1, -1, -1):
                    it = config["bitable_items"][idx]
                    if isinstance(it, dict) and (not (it.get("app_token") or "").strip()):
                        target_index = idx
                        break
                if target_index == -1:
                    target_index = len(config["bitable_items"]) - 1
            
            if target_index == -1:
                target_item = {}
                config["bitable_items"].append(target_item)
            else:
                target_item = config["bitable_items"][target_index].copy()
                config["bitable_items"][target_index] = target_item
            
            target_item["record_action"] = "update_match"
            target_item["match_field"] = match_field
            target_item["match_value"] = match_value
            return io.NodeOutput(config)

class FeishuBitableFieldNode:
    CATEGORY = "maoyu/多维表格"
    TITLE = "表格字段 (Bitable Field)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableFieldNode",
                display_name="Feishu Bitable 字段",
                category="maoyu/多维表格",
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                    io.String.Input("field_name", default="标题", tooltip="多维表格列名"),
                    io.AnyType.Input("field_value", optional=True),
                    io.Combo.Input("field_type", options=[
                        *TYPE_OPTIONS_DISPLAY
                    ], default="文本", tooltip="字段类型"),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, field_name: str, field_value, field_type: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_items" not in config:
                config["bitable_items"] = []
            else:
                config["bitable_items"] = list(config["bitable_items"])
            
            # 查找或创建一个配置项
            target_index = -1
            if config["bitable_items"]:
                for idx in range(len(config["bitable_items"]) - 1, -1, -1):
                    it = config["bitable_items"][idx]
                    if isinstance(it, dict) and (not (it.get("app_token") or "").strip()):
                        target_index = idx
                        break
                if target_index == -1:
                    target_index = len(config["bitable_items"]) - 1
            
            if target_index == -1:
                target_item = {}
                config["bitable_items"].append(target_item)
            else:
                target_item = config["bitable_items"][target_index].copy()
                config["bitable_items"][target_index] = target_item
            
            if "fields" not in target_item:
                target_item["fields"] = {}
            else:
                target_item["fields"] = target_item["fields"].copy()
                
            if "field_types" not in target_item:
                target_item["field_types"] = {}
            else:
                target_item["field_types"] = target_item["field_types"].copy()
                
            name = (field_name or "").strip()
            if name:
                target_item["fields"][name] = field_value
                # Mapping user-friendly type name to internal type code/string if needed
                ftype = field_type
                for k, v in TYPE_ALIASES.items():
                    if k in field_type: # e.g. "文本" in "文本 (Text)"
                        ftype = v
                        break
                target_item["field_types"][name] = ftype
                
            return io.NodeOutput(config)

class FeishuBitablePushNode:
    CATEGORY = "maoyu/多维表格"
    OUTPUT_NODE = True
    TITLE = "飞书多维表格 (Feishu Bitable)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitablePushNode",
                display_name="Feishu Bitable (飞书多维表格)",
                category="maoyu/多维表格",
                is_output_node=True,
                outputs=[
                    io.String.Output(display_name="多维表格记录ID(record_id)"),
                    io.String.Output(display_name="写入日志"),
                ],
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("config"),
                ],
            )
        @classmethod
        def execute(cls, config) -> io.NodeOutput:
            try:
                print("[FeishuBitable] Execute begin")
                node = FeishuBitablePushNode()
                out = node.push_bitable(config)
                print("[FeishuBitable] Execute done")
                return io.NodeOutput(*out)
            except Exception as e:
                print(f"[FeishuBitable] Execute error: {e}")
                return io.NodeOutput("", f"Error: {str(e)}")

    def _has_value(self, v):
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return len(v.strip()) > 0
        try:
            size = getattr(v, "size", None)
            if size is not None:
                return int(size) > 0
        except Exception:
            pass
        try:
            return len(v) > 0
        except Exception:
            return True

    def _tensor_to_bytes(self, tensor):
        _lazy_import_torch()
        _lazy_import_numpy_pil()
        if hasattr(tensor, "shape"):
            dims = len(tensor.shape)
            if dims == 4:
                array = 255. * tensor[0].cpu().numpy()
            elif dims == 3:
                array = 255. * tensor.cpu().numpy()
            else:
                array = None
        else:
            array = None
        if array is None:
            raise ValueError("unsupported image tensor shape")
        image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
        buffered = pyio.BytesIO()
        image.save(buffered, format="PNG")
        return buffered.getvalue()

    def _audio_to_bytes(self, audio_data):
        _lazy_import_torch()
        _lazy_import_numpy_pil()
        if not (torchaudio and torch):
            print("[FeishuBitable] torchaudio/torch not available for audio processing")
            return None
        try:
            waveform = None
            sample_rate = None
            
            if isinstance(audio_data, dict):
                waveform = audio_data.get("waveform")
                sample_rate = audio_data.get("sample_rate")
            elif hasattr(audio_data, "waveform") and hasattr(audio_data, "sample_rate"):
                waveform = audio_data.waveform
                sample_rate = audio_data.sample_rate
            elif "LazyAudioMap" in type(audio_data).__name__:
                try:
                    # LazyAudioMap usually behaves like a dict or has methods to get data
                    if hasattr(audio_data, "get"):
                        waveform = audio_data.get("waveform")
                        sample_rate = audio_data.get("sample_rate")
                    # If it's a mapping but not a dict
                    elif hasattr(audio_data, "__getitem__"):
                        waveform = audio_data["waveform"]
                        sample_rate = audio_data["sample_rate"]
                        
                    # Handle the case where values might be functions or properties needing access
                    if callable(waveform): waveform = waveform()
                    if callable(sample_rate): sample_rate = sample_rate()
                    
                    # Special handling for LazyAudioMap from VHS
                    # It might store internal state differently, let's try to access it directly if possible
                    # or force evaluation if it has such methods
                    
                except Exception as e:
                    print(f"[FeishuBitable] LazyAudioMap access error: {e}")
            
            if waveform is not None and sample_rate:
                # waveform shape: [batch, channels, time] or [channels, time]
                if hasattr(waveform, "shape") and len(waveform.shape) == 3:
                    # Take first in batch
                    waveform = waveform[0]
                
                buff = pyio.BytesIO()

                # Force format="WAV" to use soundfile backend, avoid torchcodec
                # torchaudio 2.0+ might try to use ffmpeg or other backends if not specified
                # or if the data type is weird. float32 + WAV is the safest bet for soundfile.
                # Force use of soundfile backend if available
                # In newer torchaudio, get_audio_backend is removed, but we can try setting it via global config
                # or just ensure we pass correct args.
                # However, torchaudio.save might default to ffmpeg or others if available.
                # Explicitly trying to use soundfile if installed.
                
                try:
                    import soundfile
                    # If soundfile is available, we can use it directly or via torchaudio
                    # But torchaudio.save is convenient.
                    # Let's try to set the backend if the function exists
                    if hasattr(torchaudio, "set_audio_backend"):
                        if torchaudio.get_audio_backend() != 'soundfile':
                            torchaudio.set_audio_backend('soundfile')
                except Exception:
                    pass

                # Final fallback: ensure tensor is on CPU and is float32
                if hasattr(waveform, "cpu"):
                    waveform = waveform.cpu()
                
                if hasattr(waveform, "dtype") and hasattr(torch, "float32"):
                     if waveform.dtype != torch.float32:
                         waveform = waveform.float()

                # Try saving with specific backend arg if supported in newer versions, 
                # but 'backend' arg was deprecated/removed in some versions too.
                # The safest way across versions without torchcodec is ensuring float32 + WAV.
                
                try:
                    # Try default save
                    torchaudio.save(buff, waveform, sample_rate, format="WAV")
                except Exception as e_save:
                    # If default save fails (e.g. asking for torchcodec), try using soundfile directly if possible
                    # or try a different strategy.
                    print(f"[FeishuBitable] torchaudio.save failed: {e_save}. Trying soundfile direct write...")
                    try:
                        import soundfile as sf
                        # soundfile expects (frames, channels) numpy array
                        # waveform is (channels, frames) tensor
                        audio_np = waveform.numpy().T
                        sf.write(buff, audio_np, sample_rate, format="WAV")
                    except Exception as e_sf:
                        print(f"[FeishuBitable] soundfile direct write failed: {e_sf}")
                        raise e_save

                return buff.getvalue()
        except Exception as e:
            print(f"[FeishuBitable] Audio conversion error: {e}")
            import traceback
            traceback.print_exc()
        return None

    def _upload_file_gitee(self, file_bytes, filename, config):
        token = config.get("gitee_token")
        owner = config.get("gitee_owner")
        repo = config.get("gitee_repo")
        path = config.get("gitee_path", "files")
        branch = config.get("gitee_branch", "master")
        if not (token and owner and repo):
            return None
        try:
            path = path.strip("/")
            full_path = f"{path}/{filename}" if path else filename
            url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{full_path}"
            content_base64 = base64.b64encode(file_bytes).decode('utf-8')
            data = {"access_token": token, "content": content_base64, "message": f"upload: {filename}", "branch": branch}
            res = requests.post(url, data=data, timeout=60)
            j = res.json()
            if res.status_code == 201:
                return j.get("content", {}).get("download_url")
            print(f"[FeishuBitable] Gitee upload fail: {res.status_code} {res.text[:200]}")
        except Exception as e:
            print(f"[FeishuBitable] Gitee upload error: {e}")
        return None

    def _upload_image_gitee(self, image_bytes, config):
        filename = f"{uuid.uuid4().hex}.png"
        cfg = config.copy()
        if not cfg.get("gitee_path"):
            cfg["gitee_path"] = "images"
        return self._upload_file_gitee(image_bytes, filename, cfg)
    
    def _image_bytes_to_data_url(self, image_bytes):
        _lazy_import_numpy_pil()
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return None

    def push_bitable(self, config):
        class MediaItem:
            def __init__(self, data, filename):
                self.data = data
                self.filename = filename

        logs = []
        record_ids = []
        collect_only = bool(config.get("_bitable_collect_only"))
        collected_ops = []
        
        # 1. 预处理：兼容旧版 bitable_fields 配置
        items = config.get("bitable_items", [])
        legacy_fields = config.get("bitable_fields", [])
        # 如果没有 items 但有 legacy fields，尝试转换
        if legacy_fields and not items:
             app_token = config.get("bitable_app_token", "")
             table_id = config.get("bitable_table_id", "")
             if app_token and table_id:
                 new_item = {"app_token": app_token, "table_id": table_id, "fields": {}, "field_types": {}}
                 for f in legacy_fields:
                     if f.get("name"):
                         new_item["fields"][f["name"]] = f.get("value")
                         new_item["field_types"][f["name"]] = f.get("type", "text")
                 items.append(new_item)
                 logs.append("Converted legacy fields to item")

        try:
            if isinstance(items, list) and len(items) > 1:
                base_targets = []
                for it in items:
                    if isinstance(it, dict) and (it.get("app_token") or "").strip() and (it.get("table_id") or "").strip():
                        base_targets.append(((it.get("app_token") or "").strip(), (it.get("table_id") or "").strip(), (it.get("view_id") or "").strip()), it)
                base_key = None
                if base_targets:
                    uniq = []
                    for k, _ in base_targets:
                        if k not in uniq:
                            uniq.append(k)
                    if len(uniq) == 1:
                        base_key = uniq[0]

                if base_key is not None:
                    app_token_base, table_id_base, view_id_base = base_key
                    normalized = []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        has_fields = isinstance(it.get("fields"), dict) and len(it.get("fields") or {}) > 0
                        has_action = bool((it.get("record_action") or "").strip()) or bool(it.get("record_index")) or bool((it.get("record_id") or "").strip()) or bool((it.get("match_field") or "").strip())
                        has_target = bool((it.get("app_token") or "").strip()) and bool((it.get("table_id") or "").strip())

                        if (not has_target) and (has_fields or has_action):
                            it = it.copy()
                            it["app_token"] = app_token_base
                            it["table_id"] = table_id_base
                            if (it.get("view_id") or "").strip() == "" and view_id_base:
                                it["view_id"] = view_id_base
                            normalized.append(it)
                            continue

                        if has_target and (not has_fields) and (not has_action) and len(items) > 1:
                            continue

                        normalized.append(it)
                    items = normalized
        except Exception:
            pass

        print(f"[FeishuBitable] Push started. Items count: {len(items)}")
        
        def dump_obj(obj, level=0):
            indent = "  " * level
            if isinstance(obj, dict):
                res = "{\n"
                for k, v in obj.items():
                    res += f"{indent}  {repr(k)}: {dump_obj(v, level+1)},\n"
                res += f"{indent}}}"
                return res
            elif isinstance(obj, list):
                res = "[\n"
                for v in obj:
                    res += f"{indent}  {dump_obj(v, level+1)},\n"
                res += f"{indent}]"
                return res
            elif isinstance(obj, (bytes, bytearray)):
                return f"<bytes len={len(obj)}>"
            elif hasattr(obj, "shape") and hasattr(obj, "dtype"): # Tensor/Numpy
                return f"<Tensor shape={obj.shape} dtype={obj.dtype}>"
            else:
                s = repr(obj)
                if len(s) > 200:
                    s = s[:200] + "..."
                return s

        for idx, item in enumerate(items):
            fields_data = item.get("fields", {})
            print(f"[FeishuBitable] Item {idx} fields keys: {list(fields_data.keys())}")
            for k, v in fields_data.items():
                print(f"[FeishuBitable] Field '{k}' DUMP:\n{dump_obj(v)}")

        try:
            has_app_id = bool((config.get("feishu_app_id") or "").strip())
            has_app_secret = bool((config.get("feishu_app_secret") or "").strip())
            print(f"[FeishuBitable] Config: app_id={'yes' if has_app_id else 'no'} app_secret={'yes' if has_app_secret else 'no'}")
        except Exception:
            print("[FeishuBitable] Config inspect error")

        def is_image_like(x):
            try:
                if hasattr(x, "shape"):
                    d = len(x.shape)
                    if d == 4 or d == 3:
                        return True
            except Exception:
                return False
            return False

        def _is_url_string(s):
            try:
                if isinstance(s, str):
                    st = s.strip().lower()
                    return st.startswith("http://") or st.startswith("https://")
            except Exception:
                pass
            return False

        def _is_video_file(v):
            try:
                if isinstance(v, str):
                    exts = (".mp4", ".mov", ".avi", ".mkv", ".webm")
                    return v.lower().endswith(exts)
            except Exception:
                pass
            return False

        def _resolve_comfy_path(v_path, v_sub="", v_type="input"):
            if not v_path:
                return None
            if os.path.isabs(v_path) and os.path.exists(v_path):
                return v_path
            
            if hasattr(folder_paths, 'get_annotated_filepath'):
                try:
                    p = folder_paths.get_annotated_filepath(v_path, v_sub)
                    if p and os.path.exists(p):
                        return p
                except Exception:
                    pass
            
            roots = []
            if v_type == "input":
                roots.append(folder_paths.get_input_directory())
            elif v_type == "output":
                roots.append(folder_paths.get_output_directory())
            elif v_type == "temp":
                roots.append(folder_paths.get_temp_directory())
            else:
                roots.append(folder_paths.get_output_directory())
                roots.append(folder_paths.get_input_directory())
                roots.append(folder_paths.get_temp_directory())
            
            for root in roots:
                if not root: continue
                p = os.path.join(root, v_sub, v_path) if v_sub else os.path.join(root, v_path)
                if os.path.exists(p) and os.path.isfile(p):
                    return p
            
            if os.path.exists(v_path) and os.path.isfile(v_path):
                return os.path.abspath(v_path)
            return None

        def _value_to_image_bytes(v):
            try:
                if is_image_like(v):
                    return self._tensor_to_bytes(v if len(getattr(v, "shape", [])) != 4 else v[0:1])
                if isinstance(v, Image.Image):
                    buf = pyio.BytesIO()
                    v.save(buf, format="PNG")
                    return buf.getvalue()
                if isinstance(v, bytes):
                    return v
                if isinstance(v, pyio.BytesIO):
                    return v.getvalue()
                if isinstance(v, str):
                    p = v.strip()
                    if len(p) > 0 and not _is_url_string(p):
                        try:
                            with open(p, "rb") as f:
                                return f.read()
                        except Exception:
                            return None
            except Exception:
                return None
            return None

        def _coerce_value(ftype, v):
            try:
                ft = (ftype or "text").strip().lower()
                ft = TYPE_ALIASES.get(ft, ft)
            except Exception:
                ft = "text"
            if ft == "number":
                def to_num(x):
                    if isinstance(x, bool):
                        return int(x)
                    if isinstance(x, (int, float)):
                        return x
                    if isinstance(x, str):
                        s = x.strip()
                        if not s:
                            return None
                        s = s.replace(",", "")
                        try:
                            if "." in s:
                                return float(s)
                            return int(s)
                        except:
                            m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
                            if m:
                                try:
                                    ss = m.group(0)
                                    return float(ss) if "." in ss else int(ss)
                                except:
                                    return None
                            return None
                    return None
                if isinstance(v, (list, tuple)):
                    for x in v:
                        nv = to_num(x)
                        if nv is not None:
                            return nv
                    return None
                return to_num(v)
            elif ft == "checkbox":
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(int(v))
                if isinstance(v, str):
                    s = v.strip().lower()
                    return s in ("1", "true", "yes", "y", "on", "是", "开")
                return bool(v)
            else:
                try:
                    return str(v)
                except Exception:
                    return ""

        def process_fields(raw_fields, raw_types):
            fields = {}
            field_types = {}
            
            def _norm_type(t):
                try:
                    s = str(t or "").strip().lower()
                except Exception:
                    return "text"
                return TYPE_ALIASES.get(s, s if s else "text")

            for name, value in raw_fields.items():
                if not name:
                    continue
                ftype = _norm_type(raw_types.get(name, "text"))
                field_types[name] = ftype
                
                if ftype in ("attachment", "url"):
                    has_gitee = bool(config.get("gitee_token")) and bool(config.get("gitee_owner")) and bool(config.get("gitee_repo"))
                    
                    val_list = value if isinstance(value, list) else [value]
                    
                    urls = []
                    attachments = []
                    attachment_tokens = []
                    
                    for v in val_list:
                        if isinstance(v, str):
                            real_path = _resolve_comfy_path(v)
                            if real_path:
                                try:
                                    with open(real_path, "rb") as f:
                                        vb = f.read()
                                    fname = os.path.basename(real_path)
                                    if ftype == "attachment":
                                        attachments.append(MediaItem(vb, fname))
                                    elif has_gitee:
                                        u = self._upload_file_gitee(vb, fname, config)
                                        if u:
                                            urls.append(u)
                                            logs.append(f"Uploaded: {u}")
                                        else:
                                            logs.append("Gitee Upload Failed")
                                    else:
                                        if _is_video_file(real_path):
                                            attachments.append(MediaItem(vb, fname))
                                            logs.append("Video fallback to attachment")
                                        else:
                                            du = self._image_bytes_to_data_url(vb)
                                            if du:
                                                urls.append(du)
                                                logs.append("Fallback: data-url")
                                except Exception as e:
                                    logs.append(f"File read error: {e}")
                            elif _is_url_string(v):
                                urls.append(v.strip())
                        
                        elif isinstance(v, dict):
                            try:
                                ftok = (v.get("file_token") or v.get("fileToken") or v.get("token") or "").strip()
                                if ftok:
                                    attachment_tokens.append({"file_token": ftok})
                                    continue
                                data_obj = v.get("data")
                                if isinstance(data_obj, dict):
                                    ftok2 = (data_obj.get("file_token") or data_obj.get("fileToken") or data_obj.get("token") or "").strip()
                                    if ftok2:
                                        attachment_tokens.append({"file_token": ftok2})
                                        continue
                            except Exception:
                                pass
                            try:
                                v_paths = []
                                if "filename" in v or "video_path" in v:
                                    v_paths.append(v.get("video_path") or v.get("filename"))
                                elif "filenames" in v and isinstance(v["filenames"], list):
                                    v_paths.extend(v["filenames"])
                                elif "waveform" in v and "sample_rate" in v:
                                    pass
                                elif "name" in v and ("subfolder" in v or "type" in v):
                                    v_paths.append(v.get("name"))
                                elif isinstance(v.get("data"), dict) and ("name" in v.get("data")):
                                    v_paths.append(v.get("data", {}).get("name"))
                                
                                v_sub = v.get("subfolder", "")
                                v_type = v.get("type", "input")
                                if isinstance(v.get("data"), dict):
                                    v_sub = v_sub or v.get("data", {}).get("subfolder", "")
                                    v_type = v_type or v.get("data", {}).get("type", "input")
                                
                                for v_path in v_paths:
                                    if isinstance(v_path, list):
                                        for sub_p in v_path:
                                            real_path = _resolve_comfy_path(sub_p, v_sub, v_type)
                                            if real_path:
                                                with open(real_path, "rb") as f:
                                                    vb = f.read()
                                                fname = os.path.basename(real_path)
                                                if ftype == "attachment":
                                                    attachments.append(MediaItem(vb, fname))
                                                elif has_gitee:
                                                    u = self._upload_file_gitee(vb, fname, config)
                                                    if u:
                                                        urls.append(u)
                                                        logs.append(f"Uploaded: {u}")
                                                else:
                                                    if ftype == "url":
                                                        if _is_video_file(real_path):
                                                            attachments.append(MediaItem(vb, fname))
                                                            logs.append("Video URL fallback to attachment")
                                                        else:
                                                            du = self._image_bytes_to_data_url(vb)
                                                            if du:
                                                                urls.append(du)
                                    else:
                                        real_path = _resolve_comfy_path(v_path, v_sub, v_type)
                                        if real_path:
                                             with open(real_path, "rb") as f:
                                                vb = f.read()
                                             fname = os.path.basename(real_path)
                                             if ftype == "attachment":
                                                 attachments.append(MediaItem(vb, fname))
                                             elif has_gitee:
                                                 u = self._upload_file_gitee(vb, fname, config)
                                                 if u:
                                                     urls.append(u)
                                                     logs.append(f"Uploaded: {u}")
                                             else:
                                                 if _is_video_file(real_path):
                                                     attachments.append(MediaItem(vb, fname))
                                                     logs.append("Video fallback to attachment")
                                                 else:
                                                     du = self._image_bytes_to_data_url(vb)
                                                     if du:
                                                         urls.append(du)
                                                         logs.append("Fallback: data-url")
                                        else:
                                            logs.append(f"Video file not found: {v_path}")
                            except Exception as e:
                                logs.append(f"Video dict read error: {e}")

                        if (isinstance(v, dict) and "waveform" in v and "sample_rate" in v) or (hasattr(v, "waveform") and hasattr(v, "sample_rate")) or "LazyAudioMap" in type(v).__name__:
                            print(f"[FeishuBitable] Processing audio object: {type(v)}")
                            try:
                                ab = self._audio_to_bytes(v)
                                if ab:
                                    fname = f"audio_{uuid.uuid4().hex}.wav"
                                    if ftype == "attachment":
                                        attachments.append(MediaItem(ab, fname))
                                    elif has_gitee:
                                        u = self._upload_file_gitee(ab, fname, config)
                                        if u:
                                            urls.append(u)
                                    else:
                                        attachments.append(MediaItem(ab, fname))
                                else:
                                    print("[FeishuBitable] Audio conversion returned None")
                            except Exception as e:
                                print(f"[FeishuBitable] Audio processing error: {e}")
                                import traceback
                                traceback.print_exc()
                                logs.append(f"Audio processing error: {e}")
                            # Continue to next item in val_list
                            continue
                        
                        elif hasattr(v, "get_stream_source") or hasattr(v, "save_to") or hasattr(v, "file_path") or hasattr(v, "path") or hasattr(v, "filename") or "VideoFromComponents" in type(v).__name__:
                            print(f"[FeishuBitable] Processing video-like object: {v}")
                            print(f"[FeishuBitable] Object type: {type(v)}")
                            try:
                                source_path = getattr(v, "file_path", None) or getattr(v, "path", None) or getattr(v, "filename", None)
                                print(f"[FeishuBitable] Initial source_path: {source_path}")
                                source_bytes = None
                                
                                if not source_path and hasattr(v, "get_stream_source"):
                                    print("[FeishuBitable] Trying get_stream_source()")
                                    try:
                                        stream_src = v.get_stream_source()
                                        if isinstance(stream_src, str):
                                            source_path = stream_src
                                            print(f"[FeishuBitable] get_stream_source returned path: {source_path}")
                                        elif hasattr(stream_src, "read"):
                                            print("[FeishuBitable] get_stream_source returned stream")
                                            if hasattr(stream_src, "getvalue"):
                                                source_bytes = stream_src.getvalue()
                                            else:
                                                stream_src.seek(0)
                                                source_bytes = stream_src.read()
                                            print(f"[FeishuBitable] Stream bytes read: {len(source_bytes) if source_bytes else 0}")
                                    except Exception as e:
                                        print(f"[FeishuBitable] get_stream_source failed: {e}")
                                        # Proceed to save_to fallback
                                
                                # If no path and no stream bytes, try save_to (VideoFromComponents)
                                if not source_path and not source_bytes and (hasattr(v, "save_to") or "VideoFromComponents" in type(v).__name__):
                                    print(f"[FeishuBitable] Attempting v.save_to for {v}")
                                    try:
                                        from comfy_api.latest import Types
                                        temp_dir = folder_paths.get_temp_directory()
                                        if not temp_dir:
                                            temp_dir = folder_paths.get_output_directory()
                                        
                                        temp_name = f"feishu_vid_{uuid.uuid4().hex}.mp4"
                                        temp_path = os.path.join(temp_dir, temp_name)
                                        print(f"[FeishuBitable] Temp video path: {temp_path}")
                                        
                                        # Use "auto" codec to be safe, or "libx264" for mp4
                                        # SaveVideo uses: format=Types.VideoContainer(format), codec=codec
                                        # We enforce mp4 container.
                                        v.save_to(temp_path, format=Types.VideoContainer("mp4"), codec="auto")
                                        
                                        if os.path.exists(temp_path):
                                            fsize = os.path.getsize(temp_path)
                                            print(f"[FeishuBitable] Temp video saved. Size: {fsize}")
                                            if fsize > 0:
                                                with open(temp_path, "rb") as f:
                                                    source_bytes = f.read()
                                                fname = temp_name
                                                try:
                                                    os.remove(temp_path)
                                                except:
                                                    pass
                                            else:
                                                print("[FeishuBitable] Temp video is empty!")
                                        else:
                                            print("[FeishuBitable] Temp video file not found after save_to")
                                    except Exception as e:
                                        err_msg = f"Video save_to failed: {e}"
                                        print(f"[FeishuBitable] {err_msg}")
                                        import traceback
                                        traceback.print_exc()
                                        logs.append(err_msg)

                                if source_path:
                                    real_path = _resolve_comfy_path(source_path)
                                    if real_path:
                                        with open(real_path, "rb") as f:
                                            source_bytes = f.read()
                                        fname = os.path.basename(real_path)
                                    else:
                                        logs.append(f"Video object path not found: {source_path}")
                                elif not source_bytes:
                                     pass
                                
                                if source_bytes:
                                    fname = getattr(v, "filename", f"video_{uuid.uuid4().hex}.mp4")
                                    if ftype == "attachment":
                                        attachments.append(MediaItem(source_bytes, fname))
                                    elif has_gitee:
                                        u = self._upload_file_gitee(source_bytes, fname, config)
                                        if u:
                                            urls.append(u)
                                    else:
                                        attachments.append(MediaItem(source_bytes, fname))
                            except Exception as e:
                                print(f"[FeishuBitable] Video processing loop error: {e}")
                                import traceback
                                traceback.print_exc()
                                logs.append(f"Video object error: {e}")
                        
                        else:
                            try:
                                if is_image_like(v) and hasattr(v, "shape") and len(v.shape) == 4 and int(v.shape[0]) > 1:
                                    for b in range(int(v.shape[0])):
                                        ib = self._tensor_to_bytes(v[b:b+1])
                                        if ftype == "attachment":
                                            attachments.append(ib)
                                        elif has_gitee:
                                            u = self._upload_image_gitee(ib, config)
                                            if u:
                                                urls.append(u)
                                            elif not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    urls.append(du)
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                urls.append(du)
                                else:
                                    ib = _value_to_image_bytes(v)
                                    if ib:
                                        if ftype == "attachment":
                                            attachments.append(ib)
                                        elif has_gitee:
                                            u = self._upload_image_gitee(ib, config)
                                            if u:
                                                urls.append(u)
                                            elif not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    urls.append(du)
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                urls.append(du)
                            except Exception:
                                pass

                    if ftype == "attachment":
                        if attachment_tokens and attachments:
                            fields[name] = {"__bitable_attachment_tokens": attachment_tokens, "__bitable_attachment_uploads": attachments}
                        elif attachment_tokens:
                            fields[name] = attachment_tokens
                        else:
                            fields[name] = attachments
                    else:
                        if ftype == "url":
                            if has_gitee and urls:
                                fields[name] = "\n".join(urls)
                            else:
                                fallback_name = f"{name}附件"
                                field_types[fallback_name] = "attachment"
                                att2 = []
                                if attachments:
                                    att2.extend(attachments)
                                if not att2:
                                    for vv in val_list:
                                         if not _is_url_string(vv):
                                             ib = _value_to_image_bytes(vv)
                                             if ib: att2.append(ib)
                                if att2:
                                    fields[fallback_name] = att2
                                    logs.append(f"URL fallback to attachment: {fallback_name}")
                        else:
                            if urls:
                                fields[name] = "\n".join(urls)

                else:
                    ftype_current = ftype
                    if isinstance(value, list):
                        sep = "\n\n-----------\n\n"
                        parts = []
                        if TYPE_ALIASES.get(ftype_current, ftype_current) == "number":
                            num_val = None
                            for v in value:
                                nv = _coerce_value(ftype_current, v)
                                if isinstance(nv, (int, float)):
                                    num_val = nv
                                    break
                            if num_val is not None:
                                if isinstance(num_val, int) and abs(num_val) > MAX_SAFE_INT:
                                    fallback_name = f"{name}文本"
                                    field_types[fallback_name] = "text"
                                    fields[fallback_name] = str(value[0] if len(value) > 0 else num_val)
                                    logs.append(f"Number overflow fallback to text: {fallback_name}")
                                else:
                                    fields[name] = num_val
                            else:
                                logs.append(f"Number convert fail: {name}")
                        else:
                            for v in value:
                                if _is_url_string(v):
                                    parts.append(v.strip())
                                else:
                                    s = str(v)
                                    if s.strip(): parts.append(s)
                            fields[name] = sep.join(parts) if parts else ""
                    else:
                        val = _coerce_value(ftype_current, value)
                        if val is not None:
                             if TYPE_ALIASES.get(ftype_current, ftype_current) == "number" and isinstance(val, int) and abs(val) > MAX_SAFE_INT:
                                fallback_name = f"{name}文本"
                                field_types[fallback_name] = "text"
                                fields[fallback_name] = str(value)
                                logs.append(f"Number overflow fallback to text: {fallback_name}")
                             else:
                                fields[name] = val
                        else:
                            logs.append(f"Value convert fail: {name}")
            
            return fields, field_types

        def push_one(app_token, table_id, v_id, record_idx, record_action, match_field, match_value, record_id_val, fields, field_types):
            client = FeishuBitableClient(config.get("feishu_app_id"), config.get("feishu_app_secret"))
            resolved_app_token = client.resolve_app_token(app_token, table_id)
            if resolved_app_token != app_token:
                print(f"[FeishuBitable] app_token resolved to: {resolved_app_token}")
            
            required = []
            for k in fields.keys():
                ft = field_types.get(k, "text")
                required.append({"name": k, "type": ft})
            created = client.ensure_fields(resolved_app_token, table_id, required)
            for n, c, t in created:
                if c in (200, 201):
                    logs.append(f"Field Created: {n}")
                else:
                    logs.append(f"Field Create Fail[{n}]: {c} {t}")
            
            name_to_id = client.list_fields_map(resolved_app_token, table_id)
            fields_info = client.list_fields_info(resolved_app_token, table_id)
            print(f"[FeishuBitable] name_to_id size={len(name_to_id)}")
            
            fields_payload = {}
            if name_to_id:
                for k, v in fields.items():
                    if k in name_to_id:
                        if isinstance(v, dict) and field_types.get(k) == "attachment" and ("__bitable_attachment_tokens" in v or "__bitable_attachment_uploads" in v):
                            base_tokens = v.get("__bitable_attachment_tokens") if isinstance(v.get("__bitable_attachment_tokens"), list) else []
                            uploads = v.get("__bitable_attachment_uploads") if isinstance(v.get("__bitable_attachment_uploads"), list) else []
                            tokens = []
                            for t in base_tokens:
                                if isinstance(t, dict) and ("file_token" in t or "fileToken" in t):
                                    ft = t.get("file_token") or t.get("fileToken")
                                    if ft:
                                        tokens.append({"file_token": ft})
                            for idx, ib in enumerate(uploads):
                                try:
                                    if isinstance(ib, MediaItem):
                                        ftok = client.upload_file(resolved_app_token, ib.data, ib.filename)
                                    else:
                                        ftok = client.upload_attachment(resolved_app_token, ib, f"image_{uuid.uuid4().hex}.png")
                                    if ftok:
                                        tokens.append({"file_token": ftok})
                                        logs.append(f"Attachment Uploaded: {ftok}")
                                except Exception as e:
                                    logs.append(f"Attachment Upload Error: {str(e)}")
                            target_name = k
                            try:
                                finfo = fields_info.get(k, {})
                                if str(finfo.get("ui_type", "")).lower() != "attachment" and finfo.get("type") != 17:
                                    target_name = f"{k}附件"
                                    if target_name not in name_to_id:
                                        sc, st = client.create_field(resolved_app_token, table_id, target_name, "attachment")
                                        logs.append(f"Auto Create Attachment Field[{target_name}]: {sc}")
                                        if sc in (200, 201):
                                            try:
                                                import time
                                                time.sleep(0.5)
                                                rj = json.loads(st)
                                                fid = rj.get("data", {}).get("field", {}).get("field_id")
                                                if fid:
                                                    target_name = fid
                                            except Exception:
                                                pass
                                            name_to_id = client.list_fields_map(resolved_app_token, table_id)
                                            fields_info = client.list_fields_info(resolved_app_token, table_id)
                            except Exception:
                                pass
                            if tokens:
                                fields_payload[target_name] = tokens
                        elif isinstance(v, list) and v and (isinstance(v[0], dict) and ("file_token" in v[0] or "fileToken" in v[0])) and field_types.get(k) == "attachment":
                            tokens = []
                            for t in v:
                                if isinstance(t, dict):
                                    ft = t.get("file_token") or t.get("fileToken")
                                    if ft:
                                        tokens.append({"file_token": ft})
                            if tokens:
                                fields_payload[k] = tokens
                        elif isinstance(v, list) and v and (isinstance(v[0], (bytes, bytearray)) or isinstance(v[0], MediaItem)) and field_types.get(k) == "attachment":
                            tokens = []
                            for idx, ib in enumerate(v):
                                try:
                                    if isinstance(ib, MediaItem):
                                        ftok = client.upload_file(resolved_app_token, ib.data, ib.filename)
                                    else:
                                        ftok = client.upload_attachment(resolved_app_token, ib, f"image_{uuid.uuid4().hex}.png")
                                    if ftok:
                                        tokens.append({"file_token": ftok})
                                        logs.append(f"Attachment Uploaded: {ftok}")
                                except Exception as e:
                                    logs.append(f"Attachment Upload Error: {str(e)}")
                            
                            target_name = k
                            try:
                                finfo = fields_info.get(k, {})
                                if str(finfo.get("ui_type", "")).lower() != "attachment" and finfo.get("type") != 17:
                                    target_name = f"{k}附件"
                                    if target_name not in name_to_id:
                                        sc, st = client.create_field(resolved_app_token, table_id, target_name, "attachment")
                                        logs.append(f"Auto Create Attachment Field[{target_name}]: {sc}")
                                        if sc in (200, 201):
                                            try:
                                                import time
                                                time.sleep(0.5)
                                                rj = json.loads(st)
                                                fid = rj.get("data", {}).get("field", {}).get("field_id")
                                                if fid:
                                                    target_name = fid
                                            except Exception:
                                                pass
                                            name_to_id = client.list_fields_map(resolved_app_token, table_id)
                                            fields_info = client.list_fields_info(resolved_app_token, table_id)
                            except Exception:
                                pass
                            
                            if tokens:
                                fields_payload[target_name] = tokens
                        else:
                            fields_payload[k] = v
                    else:
                         if isinstance(v, list) and v and (isinstance(v[0], (bytes, bytearray)) or isinstance(v[0], MediaItem)) and field_types.get(k) == "attachment":
                            sc, st = client.create_field(resolved_app_token, table_id, k, "attachment")
                            logs.append(f"Auto Create Attachment Field[{k}]: {sc}")
                            target_key = k
                            if sc in (200, 201):
                                try:
                                    import time
                                    time.sleep(0.5)
                                    rj = json.loads(st)
                                    fid = rj.get("data", {}).get("field", {}).get("field_id")
                                    if fid: target_key = fid
                                except Exception: pass
                                tokens = []
                                for ib in v:
                                    try:
                                        if isinstance(ib, MediaItem):
                                            ftok = client.upload_file(resolved_app_token, ib.data, ib.filename)
                                        else:
                                            ftok = client.upload_attachment(resolved_app_token, ib, f"image_{uuid.uuid4().hex}.png")
                                        if ftok: tokens.append({"file_token": ftok})
                                    except Exception: pass
                                if tokens: fields_payload[target_key] = tokens
                         else:
                             pass
            else:
                fields_payload = fields
            
            print(f"[FeishuBitable] payload_by_name_filtered count={len(fields_payload)}")
            
            def _as_rich_text(v):
                s = str(v or "")
                return [{"text": s, "type": "text"}] if len(s) > 0 else []
            def _to_rich_payload(p):
                rp = {}
                for k, v in p.items():
                    if isinstance(v, str): rp[k] = _as_rich_text(v)
                    else: rp[k] = v
                return rp

            target_record_id = None
            should_update = False
            
            if record_action == "update_index" and record_idx > 0:
                print(f"[FeishuBitable] Attempting update for row {record_idx}")
                curr_idx = 0
                pg_token = None
                while True:
                    recs = client.list_records(resolved_app_token, table_id, v_id if (v_id or "").strip() else None, 100, pg_token)
                    if not recs or not recs.get("items"): break
                    items_list = recs.get("items", [])
                    if curr_idx + len(items_list) >= record_idx:
                        offset = record_idx - curr_idx - 1
                        if 0 <= offset < len(items_list):
                            target_record_id = items_list[offset].get("record_id")
                        break
                    curr_idx += len(items_list)
                    if not recs.get("has_more"): break
                    pg_token = recs.get("page_token")
                
                if target_record_id:
                    should_update = True
                    logs.append(f"Found record[{record_idx}]: {target_record_id}")
                else:
                    logs.append(f"Record[{record_idx}] not found, skip update")
                    return
            elif record_action == "update_id" and record_id_val:
                print(f"[FeishuBitable] Attempting update by ID: {record_id_val}")
                target_record_id = record_id_val
                should_update = True
            elif record_action == "update_match" and match_field:
                print(f"[FeishuBitable] Attempting match update: {match_field} = {match_value}")
                safe_val = str(match_value or "").replace('"', '\\"')
                filter_str = f'CurrentValue.[{match_field}] = "{safe_val}"'
                recs = client.list_records(resolved_app_token, table_id, v_id if (v_id or "").strip() else None, 20, None, filter=filter_str)
                if recs and recs.get("items"):
                    target_record_id = recs.get("items")[0].get("record_id")
                    should_update = True
                    logs.append(f"Match found: {target_record_id}")
                else:
                    logs.append(f"Match not found, append new")

            if collect_only:
                op = "update" if bool(should_update) else "create"
                collected_ops.append({
                    "op": op,
                    "app_token": resolved_app_token,
                    "table_id": table_id,
                    "view_id": v_id if (v_id or "").strip() else "",
                    "record_id": str(target_record_id or "").strip(),
                    "fields": fields_payload,
                    "fields_rich": _to_rich_payload(fields_payload),
                })
                return

            try:
                print(f"[FeishuBitable] Sending {'update' if should_update else 'create'}_record. Fields keys: {list(fields_payload.keys())}")
                if should_update:
                    http_status, text = client.update_record(resolved_app_token, table_id, target_record_id, fields_payload)
                else:
                    http_status, text = client.create_record(resolved_app_token, table_id, fields_payload, v_id if (v_id or "").strip() else None)
            except Exception as e:
                logs.append(f"{'Update' if should_update else 'Create'} record error: {str(e)}")
                http_status, text = 0, str(e)
            
            success = False
            need_retry_rich = False
            try:
                j = json.loads(text)
                api_code = j.get("code", -1)
                success = (http_status in (200, 201)) and (api_code == 0)
                need_retry_rich = (http_status in (200, 201)) and (api_code == 1254002)
                print(f"[FeishuBitable] Push http={http_status} api_code={api_code}")
            except Exception:
                success = http_status in (200, 201)
            
            if (not success) and need_retry_rich:
                rich_payload = _to_rich_payload(fields_payload)
                try:
                    if should_update:
                        http_status, text = client.update_record(resolved_app_token, table_id, target_record_id, rich_payload)
                    else:
                        http_status, text = client.create_record(resolved_app_token, table_id, rich_payload, v_id if (v_id or "").strip() else None)
                except Exception as e:
                    http_status, text = 0, str(e)
                try:
                    j = json.loads(text)
                    success = (http_status in (200, 201)) and (j.get("code", -1) == 0)
                except Exception:
                    success = http_status in (200, 201)
            
            if success:
                logs.append(f"Feishu Bitable[{table_id}]: OK")
                rid = ""
                if should_update:
                    rid = str(target_record_id or "").strip()
                else:
                    try:
                        j = json.loads(text)
                        data = j.get("data") or {}
                        if isinstance(data, dict):
                            rid = str(data.get("record_id") or "").strip()
                            if not rid and isinstance(data.get("record"), dict):
                                rid = str((data.get("record") or {}).get("record_id") or "").strip()
                            if not rid and isinstance(data.get("records"), list) and data.get("records"):
                                first = data.get("records")[0]
                                if isinstance(first, dict):
                                    rid = str(first.get("record_id") or "").strip()
                    except Exception:
                        rid = ""
                if rid:
                    record_ids.append(rid)
            else:
                logs.append(f"Feishu Bitable[{table_id}]: Fail({http_status}) {text}")

        if items:
            for it in items:
                ridx = 0
                raction = it.get("record_action", "append")
                try: ridx = int(it.get("record_index") or 0)
                except: ridx = 0
                
                if ridx > 0 and raction == "append" and "record_action" not in it:
                     raction = "update_index"
                
                app_token_val = it.get("app_token", "")
                table_id_val = it.get("table_id", "")
                if not (app_token_val and table_id_val):
                     logs.append(f"Skip item: missing token/table")
                     continue
                
                p_fields, p_types = process_fields(it.get("fields", {}), it.get("field_types", {}))
                
                push_one(app_token_val, table_id_val, it.get("view_id", ""), ridx, raction, it.get("match_field"), it.get("match_value"), it.get("record_id"), p_fields, p_types)
        else:
            app_token = config.get("bitable_app_token", "") or ""
            table_id = config.get("bitable_table_id", "") or ""
            if not (app_token and table_id):
                logs.append("No Bitable target in config")
                print("[FeishuBitable] No Bitable target in config")
            else:
                # Should not happen as we convert legacy fields to items at the top
                pass

        rid_out = ""
        if record_ids:
            if len(record_ids) == 1:
                rid_out = record_ids[0]
            else:
                rid_out = ",".join([str(x) for x in record_ids if str(x).strip()])
        if collect_only:
            return (collected_ops, " | ".join(logs))
        return (rid_out, " | ".join(logs))

_BITABLE_ERROR_MONITOR_LOCK = threading.RLock()
_BITABLE_ERROR_MONITOR_ENABLED = False
_BITABLE_ERROR_MONITOR_STARTED = False
_BITABLE_ERROR_MONITOR_SENDING = False
_BITABLE_ERROR_MONITOR_LAST_SENT_TS = 0.0
_BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS = 3
_BITABLE_ERROR_MONITOR_CONFIG = None
_BITABLE_ERROR_MONITOR_MAX_CHARS = 6000
_BITABLE_ERROR_MONITOR_PUSH_DETAILS = True
_BITABLE_ERROR_MONITOR_RECENT = []
_BITABLE_ERROR_MONITOR_QUEUE = []
_BITABLE_ERROR_MONITOR_EVENT = threading.Event()
_BITABLE_ERROR_MONITOR_EXEC_PATCHED = False
_BITABLE_ERROR_MONITOR_EXEC_ORIG = None
_BITABLE_ERROR_MONITOR_EXECUTE_PATCHED = False
_BITABLE_ERROR_MONITOR_EXECUTE_ORIG = None
_BITABLE_ERROR_MONITOR_AUTOCONFIGURED = False
_BITABLE_ERROR_MONITOR_BOOTSTRAPPED = False
_BITABLE_ERROR_MONITOR_HOOKED_EXCEPTHOOK = False
_BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED = False
_BITABLE_ERROR_MONITOR_LAST_PROMPT = None
_BITABLE_ERROR_MONITOR_LAST_CONFIG_SRC_ID = None
_BITABLE_ERROR_MONITOR_LAST_MONITOR_NODE_ID = None
_BITABLE_ERROR_MONITOR_LAST_CONFIG_NODE_ID = None
_BITABLE_ERROR_MONITOR_PROMPT_HANDLER_RETRY_STARTED = False
_BITABLE_ERROR_MONITOR_DEBUG = str(os.getenv("FEISHU_BITABLE_DEBUG", "")).strip().lower() in ("1", "true", "yes", "on")
_BITABLE_ERROR_MONITOR_DEBUG_SEEN = set()

def _bitable_error_monitor_debug(tag, msg):
    if not _BITABLE_ERROR_MONITOR_DEBUG:
        return
    try:
        print(f"[FeishuBitable][ErrorMonitor][DEBUG][{tag}] {msg}")
    except Exception:
        pass

def _bitable_error_monitor_set_last_prompt(prompt):
    global _BITABLE_ERROR_MONITOR_LAST_PROMPT
    if not isinstance(prompt, dict):
        return
    with _BITABLE_ERROR_MONITOR_LOCK:
        _BITABLE_ERROR_MONITOR_LAST_PROMPT = prompt
    _bitable_error_monitor_debug("prompt", f"saved prompt nodes={len(prompt)}")

def _bitable_error_monitor_get_link_src(v):
    if isinstance(v, list) and len(v) == 2:
        return v[0]
    return None

def _bitable_error_monitor_pick_target(config):
    if not isinstance(config, dict):
        return None
    items = config.get("bitable_items")
    if isinstance(items, list) and items:
        for it in reversed(items):
            if isinstance(it, dict) and (it.get("app_token") or "").strip() and (it.get("table_id") or "").strip():
                return it.copy()
    app_token = (config.get("bitable_app_token") or "").strip()
    table_id = (config.get("bitable_table_id") or "").strip()
    view_id = (config.get("bitable_view_id") or "").strip()
    if app_token and table_id:
        return {"app_token": app_token, "table_id": table_id, "view_id": view_id}
    return None

def _bitable_error_monitor_render_fields(template_fields, context):
    out = {}
    if not isinstance(template_fields, dict):
        return out
    for k, v in template_fields.items():
        key = str(k).strip()
        if not key:
            continue
        if isinstance(v, str):
            try:
                out[key] = v.format(**context)
            except Exception:
                out[key] = v
        else:
            out[key] = v
    return out

def _bitable_error_monitor_guess_type(v):
    if isinstance(v, bool):
        return "checkbox"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list) and v:
        if isinstance(v[0], dict) and ("file_token" in v[0] or "fileToken" in v[0]):
            return "attachment"
    return "text"

def _bitable_error_monitor_coerce_fields(raw_fields, context):
    if not isinstance(raw_fields, dict):
        return {}
    out = {}
    for k, v in raw_fields.items():
        kk = str(k).strip()
        if not kk:
            continue
        if isinstance(v, str):
            try:
                out[kk] = v.format(**context)
            except Exception:
                out[kk] = v
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[kk] = v
            continue
        if isinstance(v, (list, dict)):
            out[kk] = v
            continue
        try:
            out[kk] = str(v)
        except Exception:
            out[kk] = ""
    return out

def _bitable_error_monitor_extract_summary(text):
    t = str(text or "")
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if not lines:
        return ""
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if line and set(line) <= {"^"}:
            continue
        if "Error" in line or "Exception" in line or "Traceback" in line:
            return line
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if line and set(line) <= {"^"}:
            continue
        if "!!! Exception during processing !!!" in line:
            continue
        if "RuntimeError" in line:
            return line
    return lines[-1]

def _bitable_error_monitor_sanitize_traceback(text):
    s = str(text or "")
    if not s.strip():
        return ""
    out_lines = []
    for line in s.splitlines():
        t = line.rstrip("\r\n")
        if t.strip() and set(t.strip()) <= {"^"}:
            continue
        out_lines.append(t)
    cleaned = "\n".join(out_lines).strip()
    return cleaned

def _bitable_error_monitor_extract_custom_fields_from_prompt(prompt):
    if not isinstance(prompt, dict):
        return {}, {}
    fields = {}
    field_types = {}
    for _, nobj in prompt.items():
        if not isinstance(nobj, dict):
            continue
        ct = nobj.get("class_type")
        if ct not in ("FeishuBitableFieldNode", "FeishuBitableFieldNode.Comfy"):
            continue
        fn = str(_bitable_error_monitor_prompt_get_input(nobj, "field_name") or "").strip()
        ft = str(_bitable_error_monitor_prompt_get_input(nobj, "field_type") or "").strip()
        fv_raw = None
        if isinstance(nobj.get("inputs"), dict):
            fv_raw = nobj.get("inputs", {}).get("field_value")
        fv = _bitable_error_monitor_resolve_value_from_prompt(prompt, fv_raw)
        if fn and (fv is not None):
            fields[fn] = fv
            if ft:
                field_types[fn] = ft
    return fields, field_types

def _bitable_error_monitor_collect_pre_config_chain(prompt, start_node_id, max_hops=200):
    if not isinstance(prompt, dict):
        return []

    def _get_node(nid):
        return prompt.get(nid) or prompt.get(str(nid))

    def _node_score(node_obj):
        if not isinstance(node_obj, dict):
            return 0
        ct = node_obj.get("class_type")
        if ct in ("FeishuBitableFieldNode", "FeishuBitableFieldNode.Comfy"):
            return 10
        if ct in ("FeishuBitableUpdateRowNode", "FeishuBitableUpdateRowNode.Comfy", "FeishuBitableUpdateIDNode", "FeishuBitableUpdateIDNode.Comfy", "FeishuBitableMatchNode", "FeishuBitableMatchNode.Comfy"):
            return 5
        if ct in ("FeishuBitableConfigNode", "FeishuBitableConfigNode.Comfy"):
            return 3
        return 0

    def _get_predecessors(node_obj):
        if not isinstance(node_obj, dict):
            return []
        inputs = node_obj.get("inputs")
        if not isinstance(inputs, dict):
            return []

        preds = []

        nxt = _bitable_error_monitor_get_link_src(inputs.get("pre_config"))
        if nxt is not None:
            return [nxt]

        ct = node_obj.get("class_type")
        if ct in ("AnySwitch", "AnySwitch.Comfy"):
            a = _bitable_error_monitor_get_link_src(inputs.get("优先输入"))
            b = _bitable_error_monitor_get_link_src(inputs.get("备用输入"))
            if a is not None:
                preds.append(a)
            if b is not None:
                preds.append(b)
            return preds

        if ct in ("AnyBooleanSwitch", "AnyBooleanSwitch.Comfy"):
            a = _bitable_error_monitor_get_link_src(inputs.get("输入"))
            if a is not None:
                preds.append(a)
            return preds

        if ct in ("ComfySwitchNode", "ComfySoftSwitchNode"):
            on_true = _bitable_error_monitor_get_link_src(inputs.get("on_true"))
            on_false = _bitable_error_monitor_get_link_src(inputs.get("on_false"))
            sw_raw = inputs.get("switch")
            sw = sw_raw if isinstance(sw_raw, bool) else _bitable_error_monitor_resolve_value_from_prompt(prompt, sw_raw)
            if isinstance(sw, bool):
                chosen = on_true if sw else on_false
                other = on_false if sw else on_true
                if chosen is not None:
                    preds.append(chosen)
                if other is not None:
                    preds.append(other)
                return preds
            if on_true is not None:
                preds.append(on_true)
            if on_false is not None:
                preds.append(on_false)
            return preds

        link_sources = []
        for vv in inputs.values():
            sid = _bitable_error_monitor_get_link_src(vv)
            if sid is not None:
                link_sources.append(sid)
        if len(link_sources) == 1:
            return [link_sources[0]]
        return []

    memo = {}

    def _best_chain(nid, visiting):
        if nid is None:
            return []
        if nid in memo:
            return memo[nid]
        if nid in visiting:
            return []
        visiting.add(nid)

        node_obj = _get_node(nid)
        preds = _get_predecessors(node_obj)
        best = [nid]
        best_score = _node_score(node_obj)

        for p in preds:
            ch = _best_chain(p, visiting)
            if not ch:
                cand = [nid]
            else:
                cand = ch + [nid]
            if len(cand) > int(max_hops or 200):
                cand = cand[-int(max_hops or 200):]
            s = 0
            for x in cand:
                s += _node_score(_get_node(x))
            if (s > best_score) or (s == best_score and len(cand) < len(best)):
                best = cand
                best_score = s

        visiting.remove(nid)
        memo[nid] = best
        return best

    return _best_chain(start_node_id, set())

def _bitable_error_monitor_extract_chain_item(prompt, config_src_id):
    if not isinstance(prompt, dict):
        return {}
    chain_ids = _bitable_error_monitor_collect_pre_config_chain(prompt, config_src_id)
    if not chain_ids:
        return {}
    ordered = list(chain_ids)

    fields = {}
    field_types = {}
    record_action = "append"
    record_index = 0
    record_id = ""
    match_field = ""
    match_value = None

    for nid in ordered:
        nobj = prompt.get(nid) or prompt.get(str(nid))
        if not isinstance(nobj, dict):
            continue
        ct = nobj.get("class_type")
        if ct in ("FeishuBitableFieldNode", "FeishuBitableFieldNode.Comfy"):
            fn = str(_bitable_error_monitor_prompt_get_input(nobj, "field_name") or "").strip()
            ft = str(_bitable_error_monitor_prompt_get_input(nobj, "field_type") or "").strip()
            fv_raw = None
            if isinstance(nobj.get("inputs"), dict):
                fv_raw = nobj.get("inputs", {}).get("field_value")
            fv = _bitable_error_monitor_resolve_value_from_prompt(prompt, fv_raw)
            if _BITABLE_ERROR_MONITOR_DEBUG:
                try:
                    _bitable_error_monitor_debug("fieldnode", f"id={nid} name={fn} raw={fv_raw} resolved={fv}")
                    if (fv is None) and isinstance(fv_raw, list) and len(fv_raw) == 2:
                        sid = fv_raw[0]
                        sobj = prompt.get(sid) or prompt.get(str(sid))
                        if isinstance(sobj, dict):
                            ins = sobj.get("inputs")
                            _bitable_error_monitor_debug("fieldnode", f"src_id={sid} src_type={sobj.get('class_type')} src_input_keys={list(ins.keys()) if isinstance(ins, dict) else None}")
                        else:
                            _bitable_error_monitor_debug("fieldnode", f"src_id={sid} src_node_missing")
                except Exception:
                    pass
            if fn and (fv is not None):
                fields[fn] = fv
                if ft:
                    field_types[fn] = ft
        elif ct in ("FeishuBitableUpdateRowNode", "FeishuBitableUpdateRowNode.Comfy"):
            ri = _bitable_error_monitor_prompt_get_input(nobj, "record_index")
            try:
                record_index = int(ri or 0)
            except Exception:
                record_index = 0
            if record_index > 0:
                record_action = "update_index"
        elif ct in ("FeishuBitableUpdateIDNode", "FeishuBitableUpdateIDNode.Comfy"):
            rid = str(_bitable_error_monitor_prompt_get_input(nobj, "record_id") or "").strip()
            if rid:
                record_id = rid
                record_action = "update_id"
        elif ct in ("FeishuBitableMatchNode", "FeishuBitableMatchNode.Comfy"):
            mf = str(_bitable_error_monitor_prompt_get_input(nobj, "match_field") or "").strip()
            mv_raw = None
            if isinstance(nobj.get("inputs"), dict):
                mv_raw = nobj.get("inputs", {}).get("match_value")
            mv = _bitable_error_monitor_resolve_value_from_prompt(prompt, mv_raw)
            if mf and (mv is not None) and (str(mv).strip() != ""):
                match_field = mf
                match_value = mv
                record_action = "update_match"

    return {
        "fields": fields,
        "field_types": field_types,
        "record_action": record_action,
        "record_index": record_index,
        "record_id": record_id,
        "match_field": match_field,
        "match_value": match_value,
    }

def _bitable_error_monitor_find_monitor_from_prompt(prompt):
    if not isinstance(prompt, dict):
        return None
    chosen = None
    for nid, nobj in prompt.items():
        if not isinstance(nobj, dict):
            continue
        ct = nobj.get("class_type")
        if ct not in ("FeishuBitableErrorMonitorNode", "FeishuBitableErrorMonitorNode.Comfy"):
            continue
        ev = _bitable_error_monitor_prompt_get_input_any(prompt, nobj, "enabled")
        if chosen is None:
            chosen = (nid, nobj)
        if isinstance(ev, bool) and ev is True:
            return (nid, nobj)
    return chosen

def _bitable_error_monitor_should_trigger(chunk_text):
    s = str(chunk_text or "")
    if "Traceback (most recent call last)" in s:
        return True
    if "Traceback" in s and "most recent call last" in s:
        return True
    if "ERROR" in s:
        return True
    if "Exception:" in s:
        return True
    if "Error:" in s:
        return True
    if "RuntimeError" in s:
        return True
    return False

def _bitable_error_monitor_enqueue(ts, text, force=False):
    global _BITABLE_ERROR_MONITOR_RECENT, _BITABLE_ERROR_MONITOR_QUEUE
    with _BITABLE_ERROR_MONITOR_LOCK:
        if not _BITABLE_ERROR_MONITOR_ENABLED or _BITABLE_ERROR_MONITOR_SENDING:
            return
        t = str(text or "")
        if (not force) and (not _bitable_error_monitor_should_trigger(t)):
            return
        now_str = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if force:
            trimmed = t[-(_BITABLE_ERROR_MONITOR_MAX_CHARS):] if t else ""
            _BITABLE_ERROR_MONITOR_QUEUE.append({"time": now_str, "text": trimmed, "forced": True})
            if len(_BITABLE_ERROR_MONITOR_QUEUE) > 20:
                _BITABLE_ERROR_MONITOR_QUEUE = _BITABLE_ERROR_MONITOR_QUEUE[-20:]
            _BITABLE_ERROR_MONITOR_EVENT.set()
            return

        if t:
            _BITABLE_ERROR_MONITOR_RECENT.append(t if t.endswith("\n") else (t + "\n"))
            if len(_BITABLE_ERROR_MONITOR_RECENT) > 400:
                _BITABLE_ERROR_MONITOR_RECENT = _BITABLE_ERROR_MONITOR_RECENT[-400:]
        combined = "".join(_BITABLE_ERROR_MONITOR_RECENT)[-(_BITABLE_ERROR_MONITOR_MAX_CHARS):]
        _BITABLE_ERROR_MONITOR_QUEUE.append({"time": now_str, "text": combined, "forced": False})
        if len(_BITABLE_ERROR_MONITOR_QUEUE) > 20:
            _BITABLE_ERROR_MONITOR_QUEUE = _BITABLE_ERROR_MONITOR_QUEUE[-20:]
        _BITABLE_ERROR_MONITOR_EVENT.set()

def _bitable_error_monitor_enqueue_execution_error(ts, exception_type, exception_message, traceback_text):
    global _BITABLE_ERROR_MONITOR_QUEUE
    with _BITABLE_ERROR_MONITOR_LOCK:
        if not _BITABLE_ERROR_MONITOR_ENABLED or _BITABLE_ERROR_MONITOR_SENDING:
            return
        _BITABLE_ERROR_MONITOR_QUEUE.append({
            "time": ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kind": "execution_error",
            "exception_type": str(exception_type or ""),
            "exception_message": str(exception_message or ""),
            "traceback": str(traceback_text or ""),
        })
        if len(_BITABLE_ERROR_MONITOR_QUEUE) > 20:
            _BITABLE_ERROR_MONITOR_QUEUE = _BITABLE_ERROR_MONITOR_QUEUE[-20:]
        _BITABLE_ERROR_MONITOR_EVENT.set()

def _bitable_error_monitor_patch_execution():
    global _BITABLE_ERROR_MONITOR_EXEC_PATCHED, _BITABLE_ERROR_MONITOR_EXEC_ORIG, _BITABLE_ERROR_MONITOR_EXECUTE_PATCHED, _BITABLE_ERROR_MONITOR_EXECUTE_ORIG
    if _BITABLE_ERROR_MONITOR_EXEC_PATCHED and _BITABLE_ERROR_MONITOR_EXECUTE_PATCHED:
        return
    try:
        import execution as comfy_execution
        if not hasattr(comfy_execution, "PromptExecutor"):
            return
        if not _BITABLE_ERROR_MONITOR_EXEC_PATCHED:
            orig = comfy_execution.PromptExecutor.handle_execution_error
            _BITABLE_ERROR_MONITOR_EXEC_ORIG = orig

            def _wrapped_handle_execution_error(self, prompt_id, prompt, current_outputs, executed, error, ex):
                try:
                    try:
                        _bitable_error_monitor_try_autoconfig_from_prompt(prompt)
                        _bitable_error_monitor_set_last_prompt(prompt)
                    except Exception:
                        pass
                    et = ""
                    em = ""
                    tb = ""
                    if isinstance(error, dict):
                        et = str(error.get("exception_type") or "")
                        em = str(error.get("exception_message") or "")
                        tb = error.get("traceback") or ""
                    if isinstance(tb, list):
                        tb = "".join(tb)
                    if ex is not None:
                        try:
                            ex_type = type(ex).__name__
                            if not et:
                                et = ex_type
                            if not em:
                                em = str(ex)
                            tb_ex = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
                            if tb_ex and ("Traceback" in tb_ex or "File " in tb_ex):
                                tb_s = str(tb or "").strip()
                                if (not tb_s) or (len(tb_s) < 30) or (set(tb_s) <= {"^"}) or (("Traceback" in tb_ex) and ("Traceback" not in tb_s)):
                                    tb = tb_ex
                        except Exception:
                            pass
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    _bitable_error_monitor_enqueue_execution_error(ts, et, em, tb)
                except Exception:
                    pass
                return orig(self, prompt_id, prompt, current_outputs, executed, error, ex)

            comfy_execution.PromptExecutor.handle_execution_error = _wrapped_handle_execution_error
            _BITABLE_ERROR_MONITOR_EXEC_PATCHED = True
            _bitable_error_monitor_debug("patch", "patched PromptExecutor.handle_execution_error")

        if not _BITABLE_ERROR_MONITOR_EXECUTE_PATCHED:
            orig_exec = comfy_execution.PromptExecutor.execute
            _BITABLE_ERROR_MONITOR_EXECUTE_ORIG = orig_exec

            def _wrapped_execute(self, prompt, prompt_id, extra_data={}, execute_outputs=[]):
                try:
                    _bitable_error_monitor_try_autoconfig_from_prompt(prompt)
                    _bitable_error_monitor_set_last_prompt(prompt)
                    _bitable_error_monitor_debug("execute", f"PromptExecutor.execute prompt_id={prompt_id} nodes={len(prompt) if isinstance(prompt, dict) else 'NA'}")
                except Exception:
                    pass
                return orig_exec(self, prompt, prompt_id, extra_data, execute_outputs)

            comfy_execution.PromptExecutor.execute = _wrapped_execute
            _BITABLE_ERROR_MONITOR_EXECUTE_PATCHED = True
            _bitable_error_monitor_debug("patch", "patched PromptExecutor.execute")
    except Exception:
        try:
            traceback.print_exc()
        except Exception:
            pass

def _bitable_error_monitor_patch_excepthook():
    global _BITABLE_ERROR_MONITOR_HOOKED_EXCEPTHOOK
    if _BITABLE_ERROR_MONITOR_HOOKED_EXCEPTHOOK:
        return
    try:
        import sys as _sys
        orig_sys = getattr(_sys, "excepthook", None)
        def _wrapped_sys_excepthook(exc_type, exc, tb):
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tb_text = "".join(traceback.format_exception(exc_type, exc, tb))
                _bitable_error_monitor_enqueue_execution_error(ts, getattr(exc_type, "__name__", "") or "", str(exc or ""), tb_text)
            except Exception:
                pass
            if callable(orig_sys):
                return orig_sys(exc_type, exc, tb)
            return None
        _sys.excepthook = _wrapped_sys_excepthook
    except Exception:
        pass

    try:
        import threading as _threading
        orig_th = getattr(_threading, "excepthook", None)
        def _wrapped_threading_excepthook(args):
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                et = getattr(getattr(args, "exc_type", None), "__name__", "") or ""
                em = str(getattr(args, "exc_value", "") or "")
                tb_obj = getattr(args, "exc_traceback", None)
                tb_text = ""
                try:
                    if tb_obj is not None:
                        tb_text = "".join(traceback.format_exception(getattr(args, "exc_type", None), getattr(args, "exc_value", None), tb_obj))
                except Exception:
                    tb_text = ""
                _bitable_error_monitor_enqueue_execution_error(ts, et, em, tb_text)
            except Exception:
                pass
            if callable(orig_th):
                return orig_th(args)
            return None
        if hasattr(_threading, "excepthook"):
            _threading.excepthook = _wrapped_threading_excepthook
    except Exception:
        pass
    _BITABLE_ERROR_MONITOR_HOOKED_EXCEPTHOOK = True

def _bitable_error_monitor_bootstrap():
    global _BITABLE_ERROR_MONITOR_BOOTSTRAPPED, _BITABLE_ERROR_MONITOR_STARTED
    if _BITABLE_ERROR_MONITOR_BOOTSTRAPPED:
        return
    try:
        try:
            _bitable_error_monitor_patch_execution()
        except Exception:
            pass
        try:
            _bitable_error_monitor_patch_excepthook()
        except Exception:
            pass
        try:
            _bitable_error_monitor_install_prompt_handler()
        except Exception:
            pass
        try:
            _bitable_error_monitor_start_prompt_handler_retry()
        except Exception:
            pass
        try:
            import app.logger as comfy_app_logger
            comfy_app_logger.on_flush(_bitable_error_monitor_on_flush)
        except Exception:
            pass
        if not _BITABLE_ERROR_MONITOR_STARTED:
            t = threading.Thread(target=_bitable_error_monitor_worker, name="AnySwitch_BitableErrorMonitor", daemon=True)
            t.start()
            _BITABLE_ERROR_MONITOR_STARTED = True
    finally:
        _BITABLE_ERROR_MONITOR_BOOTSTRAPPED = True

def _bitable_error_monitor_is_plain_value(v):
    return isinstance(v, (str, int, float, bool)) or v is None

def _bitable_error_monitor_prompt_get_input(node_obj, name):
    if not isinstance(node_obj, dict):
        return None
    inputs = node_obj.get("inputs")
    if not isinstance(inputs, dict):
        return None
    v = inputs.get(name)
    if _bitable_error_monitor_is_plain_value(v):
        return v
    return None

def _bitable_error_monitor_prompt_get_input_any(prompt, node_obj, name):
    v = _bitable_error_monitor_prompt_get_input(node_obj, name)
    if v is not None:
        return v
    if not isinstance(node_obj, dict):
        return None
    inputs = node_obj.get("inputs")
    if not isinstance(inputs, dict):
        return None
    raw = inputs.get(name)
    return _bitable_error_monitor_resolve_value_from_prompt(prompt, raw)

def _bitable_error_monitor_resolve_value_from_prompt(prompt, val):
    def _pick_from_inputs(node_obj):
        if not isinstance(node_obj, dict):
            return None
        inputs = node_obj.get("inputs")
        if not isinstance(inputs, dict):
            return None

        scalars = []
        for k, vv in inputs.items():
            if _bitable_error_monitor_is_plain_value(vv):
                if isinstance(vv, str):
                    if vv.strip() == "":
                        continue
                scalars.append((k, vv))

        if len(scalars) == 1:
            return scalars[0][1]

        if scalars:
            smap = {k: v for k, v in scalars}
            try:
                import nodes as comfy_nodes
                ct = node_obj.get("class_type")
                obj_class = comfy_nodes.NODE_CLASS_MAPPINGS.get(ct)
                if obj_class is not None and hasattr(obj_class, "INPUT_TYPES"):
                    it = obj_class.INPUT_TYPES()
                    ordered = []
                    if isinstance(it, dict):
                        req = it.get("required")
                        opt = it.get("optional")
                        if isinstance(req, dict):
                            ordered.extend(list(req.keys()))
                        if isinstance(opt, dict):
                            ordered.extend(list(opt.keys()))
                    if ordered:
                        rest = [k for k, _ in scalars if k not in ordered]
                        ordered = [k for k in ordered if k in smap] + sorted(rest)
                        parts = [f"{k}={smap.get(k)}" for k in ordered if k in smap]
                        if parts:
                            return " | ".join(parts)
            except Exception:
                pass

            ordered = sorted([k for k, _ in scalars])
            parts = [f"{k}={smap.get(k)}" for k in ordered if k in smap]
            if parts:
                return " | ".join(parts)
            return None

        wv = node_obj.get("widgets_values")
        if isinstance(wv, list):
            only_scalars = []
            for x in wv:
                if _bitable_error_monitor_is_plain_value(x):
                    if isinstance(x, str) and x.strip() == "":
                        continue
                    only_scalars.append(x)
            if len(only_scalars) == 1:
                return only_scalars[0]
            if only_scalars:
                parts = [f"w{i}={v}" for i, v in enumerate(only_scalars)]
                return " | ".join(parts)
        return None

    def _resolve(v, depth, seen):
        if _bitable_error_monitor_is_plain_value(v):
            return v
        if depth <= 0:
            return None
        if not isinstance(v, list) or len(v) != 2:
            return None
        if not isinstance(prompt, dict):
            return None
        src_id = v[0]
        if src_id in seen:
            return None
        seen.add(src_id)
        src = prompt.get(src_id) or prompt.get(str(src_id))
        if not isinstance(src, dict):
            return None

        got_simple = _pick_from_inputs(src)
        if got_simple is not None:
            return got_simple

        inputs = src.get("inputs")
        if isinstance(inputs, dict):
            for key in ("text", "value", "string", "prompt", "message", "input", "content", "name", "title", "positive", "negative", "正面提示词", "反面提示词", "内容", "文本"):
                vv = inputs.get(key)
                if _bitable_error_monitor_is_plain_value(vv):
                    if isinstance(vv, str):
                        if vv.strip() != "":
                            return vv
                    else:
                        return vv
            only_scalars = []
            for vv in inputs.values():
                if _bitable_error_monitor_is_plain_value(vv):
                    if isinstance(vv, str):
                        if vv.strip() != "":
                            only_scalars.append(vv)
                    else:
                        only_scalars.append(vv)
            if len(only_scalars) == 1:
                return only_scalars[0]

            only_strings = []
            for vv in inputs.values():
                if isinstance(vv, str) and vv.strip() != "":
                    only_strings.append(vv)
            if len(only_strings) == 1:
                return only_strings[0]

            for key in ("value", "text", "string", "prompt", "input"):
                vv = inputs.get(key)
                if isinstance(vv, list) and len(vv) == 2:
                    got = _resolve(vv, depth - 1, seen)
                    if got is not None:
                        return got
            link_values = []
            for vv in inputs.values():
                if isinstance(vv, list) and len(vv) == 2:
                    link_values.append(vv)
            if len(link_values) == 1:
                got = _resolve(link_values[0], depth - 1, seen)
                if got is not None:
                    return got

        wv = src.get("widgets_values")
        if isinstance(wv, list):
            only_scalars = []
            for x in wv:
                if _bitable_error_monitor_is_plain_value(x):
                    if isinstance(x, str):
                        if x.strip() != "":
                            only_scalars.append(x)
                    else:
                        only_scalars.append(x)
            if len(only_scalars) == 1:
                return only_scalars[0]
            only_strings = [x for x in wv if isinstance(x, str) and x.strip() != ""]
            if len(only_strings) == 1:
                return only_strings[0]

        return None

    return _resolve(val, 10, set())

def _bitable_error_monitor_try_autoconfig_from_prompt(prompt):
    global _BITABLE_ERROR_MONITOR_AUTOCONFIGURED, _BITABLE_ERROR_MONITOR_CONFIG, _BITABLE_ERROR_MONITOR_ENABLED, _BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS, _BITABLE_ERROR_MONITOR_MAX_CHARS, _BITABLE_ERROR_MONITOR_PUSH_DETAILS, _BITABLE_ERROR_MONITOR_LAST_CONFIG_SRC_ID, _BITABLE_ERROR_MONITOR_LAST_MONITOR_NODE_ID, _BITABLE_ERROR_MONITOR_LAST_CONFIG_NODE_ID
    if not isinstance(prompt, dict):
        return
    _bitable_error_monitor_set_last_prompt(prompt)

    mon_node_id = None
    mon_node = None
    mon_config_src_id = None
    mon_enabled = None
    mon_push_details = None
    mon_cooldown = None
    mon_max_chars = None

    for nid, nobj in prompt.items():
        if not isinstance(nobj, dict):
            continue
        ct = nobj.get("class_type")
        if ct not in ("FeishuBitableErrorMonitorNode", "FeishuBitableErrorMonitorNode.Comfy"):
            continue

        ev = _bitable_error_monitor_prompt_get_input_any(prompt, nobj, "enabled")
        pv = _bitable_error_monitor_prompt_get_input_any(prompt, nobj, "push_error_details")
        cv = _bitable_error_monitor_prompt_get_input_any(prompt, nobj, "cooldown_seconds")
        mv = _bitable_error_monitor_prompt_get_input_any(prompt, nobj, "max_chars")
        src = None
        if isinstance(nobj.get("inputs"), dict):
            src = _bitable_error_monitor_get_link_src(nobj.get("inputs", {}).get("config"))

        if mon_node is None:
            mon_node_id = nid
            mon_node = nobj
            mon_config_src_id = src
            if isinstance(ev, bool):
                mon_enabled = ev
            if isinstance(pv, bool):
                mon_push_details = pv
            if isinstance(cv, (int, float, str)):
                try:
                    mon_cooldown = int(cv)
                except Exception:
                    mon_cooldown = None
            if isinstance(mv, (int, float, str)):
                try:
                    mon_max_chars = int(mv)
                except Exception:
                    mon_max_chars = None

        if isinstance(ev, bool) and ev is True:
            mon_node_id = nid
            mon_node = nobj
            mon_config_src_id = src
            mon_enabled = ev
            if isinstance(pv, bool):
                mon_push_details = pv
            if isinstance(cv, (int, float, str)):
                try:
                    mon_cooldown = int(cv)
                except Exception:
                    mon_cooldown = None
            if isinstance(mv, (int, float, str)):
                try:
                    mon_max_chars = int(mv)
                except Exception:
                    mon_max_chars = None
            break

    if not mon_node:
        return

    cfg_node_id = None
    cfg_node = None
    if mon_config_src_id is not None:
        chain_ids = _bitable_error_monitor_collect_pre_config_chain(prompt, mon_config_src_id)
        for cid in reversed(chain_ids):
            cobj = prompt.get(cid) or prompt.get(str(cid))
            if isinstance(cobj, dict) and cobj.get("class_type") in ("FeishuBitableConfigNode", "FeishuBitableConfigNode.Comfy"):
                cfg_node_id = cid
                cfg_node = cobj
                break

    if cfg_node is None:
        for nid, nobj in prompt.items():
            if isinstance(nobj, dict) and nobj.get("class_type") in ("FeishuBitableConfigNode", "FeishuBitableConfigNode.Comfy"):
                cfg_node_id = nid
                cfg_node = nobj
                break
    if cfg_node is None:
        return

    app_token = str(_bitable_error_monitor_prompt_get_input_any(prompt, cfg_node, "app_token") or "").strip()
    table_id = str(_bitable_error_monitor_prompt_get_input_any(prompt, cfg_node, "table_id") or "").strip()
    view_id = str(_bitable_error_monitor_prompt_get_input_any(prompt, cfg_node, "view_id") or "").strip()
    app_id = str(_bitable_error_monitor_prompt_get_input_any(prompt, cfg_node, "feishu_app_id") or "").strip()
    app_secret = str(_bitable_error_monitor_prompt_get_input_any(prompt, cfg_node, "feishu_app_secret") or "").strip()
    if not (app_token and table_id and app_id and app_secret):
        return

    chain_item = {}
    if mon_config_src_id is not None:
        chain_item = _bitable_error_monitor_extract_chain_item(prompt, mon_config_src_id)
    fields = chain_item.get("fields") if isinstance(chain_item, dict) else None
    field_types = chain_item.get("field_types") if isinstance(chain_item, dict) else None
    record_action = chain_item.get("record_action") if isinstance(chain_item, dict) else None
    record_index = chain_item.get("record_index") if isinstance(chain_item, dict) else None
    record_id = chain_item.get("record_id") if isinstance(chain_item, dict) else None
    match_field = chain_item.get("match_field") if isinstance(chain_item, dict) else None
    match_value = chain_item.get("match_value") if isinstance(chain_item, dict) else None
    if not isinstance(fields, dict):
        fields = {}
    if not isinstance(field_types, dict):
        field_types = {}
    if not isinstance(record_action, str) or not record_action.strip():
        record_action = "append"
    try:
        record_index = int(record_index or 0)
    except Exception:
        record_index = 0
    record_id = str(record_id or "").strip()
    match_field = str(match_field or "").strip()

    item = {
        "app_token": app_token,
        "table_id": table_id,
        "view_id": view_id,
        "fields": fields,
        "field_types": field_types,
        "record_action": record_action,
        "record_index": record_index,
        "record_id": record_id,
        "match_field": match_field,
        "match_value": match_value,
    }
    config = {
        "bitable_app_token": app_token,
        "bitable_table_id": table_id,
        "bitable_view_id": view_id,
        "feishu_app_id": app_id,
        "feishu_app_secret": app_secret,
        "bitable_items": [item],
    }

    with _BITABLE_ERROR_MONITOR_LOCK:
        _BITABLE_ERROR_MONITOR_CONFIG = config
        _BITABLE_ERROR_MONITOR_AUTOCONFIGURED = True
        if mon_config_src_id is not None:
            _BITABLE_ERROR_MONITOR_LAST_CONFIG_SRC_ID = mon_config_src_id
        if mon_node_id is not None:
            _BITABLE_ERROR_MONITOR_LAST_MONITOR_NODE_ID = mon_node_id
        if cfg_node_id is not None:
            _BITABLE_ERROR_MONITOR_LAST_CONFIG_NODE_ID = cfg_node_id
        if mon_enabled is not None:
            _BITABLE_ERROR_MONITOR_ENABLED = bool(mon_enabled)
        if mon_push_details is not None:
            _BITABLE_ERROR_MONITOR_PUSH_DETAILS = bool(mon_push_details)
        if isinstance(mon_cooldown, int) and mon_cooldown >= 0:
            _BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS = mon_cooldown
        if isinstance(mon_max_chars, int):
            if mon_max_chars <= 0:
                pass
            elif mon_max_chars > 20000:
                _BITABLE_ERROR_MONITOR_MAX_CHARS = 20000
            else:
                _BITABLE_ERROR_MONITOR_MAX_CHARS = mon_max_chars

def _bitable_error_monitor_install_prompt_handler():
    global _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED
    if _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED:
        return
    try:
        from server import PromptServer
        ps = getattr(PromptServer, "instance", None)
        if ps is None:
            return
        def _on_prompt(json_data):
            try:
                if isinstance(json_data, dict):
                    p = json_data.get("prompt")
                    if isinstance(p, dict):
                        _bitable_error_monitor_try_autoconfig_from_prompt(p)
                        _bitable_error_monitor_set_last_prompt(p)
                        _bitable_error_monitor_debug("on_prompt", f"received prompt nodes={len(p)} keys_sample={list(p.keys())[:3]}")
            except Exception:
                pass
            return json_data
        ps.add_on_prompt_handler(_on_prompt)
        _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED = True
        _bitable_error_monitor_debug("patch", "installed PromptServer.on_prompt handler")
    except Exception:
        return

def _bitable_error_monitor_start_prompt_handler_retry():
    global _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_RETRY_STARTED
    if _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_RETRY_STARTED:
        return
    _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_RETRY_STARTED = True

    def _worker():
        while True:
            try:
                if _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED:
                    return
                _bitable_error_monitor_install_prompt_handler()
                if _BITABLE_ERROR_MONITOR_PROMPT_HANDLER_INSTALLED:
                    return
            except Exception:
                pass
            try:
                time.sleep(0.5)
            except Exception:
                return

    try:
        t = threading.Thread(target=_worker, name="AnySwitch_BitablePromptHook", daemon=True)
        t.start()
    except Exception:
        return

def _bitable_error_monitor_on_flush(entries):
    try:
        msgs = []
        for e in entries or []:
            if isinstance(e, dict) and "m" in e:
                msgs.append(e.get("m") or "")
        chunk = "".join(msgs)
        if not chunk:
            return
        _bitable_error_monitor_enqueue(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), chunk, force=False)
    except Exception:
        return

def _bitable_error_monitor_worker():
    global _BITABLE_ERROR_MONITOR_LAST_SENT_TS, _BITABLE_ERROR_MONITOR_SENDING
    while True:
        _BITABLE_ERROR_MONITOR_EVENT.wait()
        _BITABLE_ERROR_MONITOR_EVENT.clear()
        payload = None
        with _BITABLE_ERROR_MONITOR_LOCK:
            if not _BITABLE_ERROR_MONITOR_ENABLED:
                continue
            if _BITABLE_ERROR_MONITOR_QUEUE:
                payload = _BITABLE_ERROR_MONITOR_QUEUE.pop(0)
        if not payload:
            continue

        now = time.time()
        with _BITABLE_ERROR_MONITOR_LOCK:
            cd = int(_BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS or 0)
            if cd > 0 and (now - _BITABLE_ERROR_MONITOR_LAST_SENT_TS) < cd:
                continue
            _BITABLE_ERROR_MONITOR_LAST_SENT_TS = now
            _BITABLE_ERROR_MONITOR_SENDING = True
            cfg = _BITABLE_ERROR_MONITOR_CONFIG.copy() if isinstance(_BITABLE_ERROR_MONITOR_CONFIG, dict) else None

        try:
            if not cfg:
                continue
            target = _bitable_error_monitor_pick_target(cfg)
            if not target:
                continue
            _bitable_error_monitor_debug("worker", f"payload_kind={payload.get('kind','log')} enabled={_BITABLE_ERROR_MONITOR_ENABLED} push_details={_BITABLE_ERROR_MONITOR_PUSH_DETAILS}")
            app_id = (cfg.get("feishu_app_id") or "").strip()
            app_secret = (cfg.get("feishu_app_secret") or "").strip()
            if not (app_id and app_secret):
                continue

            client = FeishuBitableClient(app_id, app_secret)
            app_token = client.resolve_app_token(target.get("app_token") or "", target.get("table_id") or "")
            table_id = (target.get("table_id") or "").strip()
            view_id = (target.get("view_id") or "").strip() or None

            if payload.get("kind") == "execution_error":
                et = str(payload.get("exception_type") or "")
                em = str(payload.get("exception_message") or "")
                tb = _bitable_error_monitor_sanitize_traceback(payload.get("traceback") or "")
                err_line = f"{et}: {em}".strip(": ").strip()
                if err_line and set(err_line.strip()) <= {"^"}:
                    err_line = ""
                ctx = {
                    "time": payload.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": err_line or em or et,
                    "traceback": (err_line + "\n" + tb).strip() if tb else (err_line or ""),
                }
            else:
                text = payload.get("text") or ""
                text = _bitable_error_monitor_sanitize_traceback(text)
                summary = _bitable_error_monitor_extract_summary(text)
                ctx = {
                    "time": payload.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": summary,
                    "traceback": text,
                }
            extra_fields = _bitable_error_monitor_coerce_fields(target.get("fields"), ctx) if isinstance(target, dict) else {}
            prompt_snapshot = None
            config_src_id = None
            with _BITABLE_ERROR_MONITOR_LOCK:
                if isinstance(_BITABLE_ERROR_MONITOR_LAST_PROMPT, dict):
                    prompt_snapshot = _BITABLE_ERROR_MONITOR_LAST_PROMPT
                config_src_id = _BITABLE_ERROR_MONITOR_LAST_CONFIG_SRC_ID

            _bitable_error_monitor_debug("worker", f"have_prompt={'yes' if isinstance(prompt_snapshot, dict) else 'no'} config_src_id_cached={config_src_id}")

            if isinstance(prompt_snapshot, dict):
                mon = _bitable_error_monitor_find_monitor_from_prompt(prompt_snapshot)
                if mon is not None:
                    mn = mon[1]
                    if isinstance(mn, dict) and isinstance(mn.get("inputs"), dict):
                        found_src = _bitable_error_monitor_get_link_src(mn.get("inputs", {}).get("config"))
                        if found_src is not None:
                            config_src_id = found_src
                            _bitable_error_monitor_debug("worker", f"config_src_id_from_monitor={config_src_id}")

            if (config_src_id is None) and isinstance(prompt_snapshot, dict):
                mon_id = None
                with _BITABLE_ERROR_MONITOR_LOCK:
                    mon_id = _BITABLE_ERROR_MONITOR_LAST_MONITOR_NODE_ID
                if mon_id is not None:
                    mn = prompt_snapshot.get(mon_id) or prompt_snapshot.get(str(mon_id))
                    if isinstance(mn, dict) and isinstance(mn.get("inputs"), dict):
                        config_src_id = _bitable_error_monitor_get_link_src(mn.get("inputs", {}).get("config"))
                if config_src_id is None:
                    for nid, nobj in prompt_snapshot.items():
                        if not isinstance(nobj, dict):
                            continue
                        if nobj.get("class_type") not in ("FeishuBitableErrorMonitorNode", "FeishuBitableErrorMonitorNode.Comfy"):
                            continue
                        ev = _bitable_error_monitor_prompt_get_input_any(prompt_snapshot, nobj, "enabled")
                        if isinstance(ev, bool) and (not ev):
                            continue
                        if isinstance(nobj.get("inputs"), dict):
                            config_src_id = _bitable_error_monitor_get_link_src(nobj.get("inputs", {}).get("config"))
                            if config_src_id is not None:
                                break

            chain_item = {}
            if prompt_snapshot and (config_src_id is not None):
                chain_item = _bitable_error_monitor_extract_chain_item(prompt_snapshot, config_src_id)
            if _BITABLE_ERROR_MONITOR_DEBUG and isinstance(prompt_snapshot, dict) and (config_src_id is not None):
                try:
                    chain_ids_dbg = _bitable_error_monitor_collect_pre_config_chain(prompt_snapshot, config_src_id)
                    chain_types_dbg = []
                    for cid in chain_ids_dbg:
                        obj = prompt_snapshot.get(cid) or prompt_snapshot.get(str(cid))
                        chain_types_dbg.append(str(obj.get("class_type") if isinstance(obj, dict) else ""))
                    _bitable_error_monitor_debug("chain", f"chain_ids={chain_ids_dbg} chain_types={chain_types_dbg}")
                except Exception:
                    pass

            prompt_fields = {}
            prompt_types = {}
            chain_record_action = None
            chain_record_index = None
            chain_record_id = None
            chain_match_field = None
            chain_match_value = None
            if isinstance(chain_item, dict) and chain_item:
                prompt_fields = chain_item.get("fields") or {}
                prompt_types = chain_item.get("field_types") or {}
                chain_record_action = chain_item.get("record_action")
                chain_record_index = chain_item.get("record_index")
                chain_record_id = chain_item.get("record_id")
                chain_match_field = chain_item.get("match_field")
                chain_match_value = chain_item.get("match_value")
            elif prompt_snapshot:
                prompt_fields, prompt_types = _bitable_error_monitor_extract_custom_fields_from_prompt(prompt_snapshot)

            if isinstance(prompt_fields, dict) and prompt_fields:
                prompt_fields = _bitable_error_monitor_coerce_fields(prompt_fields, ctx)

            fields = {}
            if isinstance(prompt_fields, dict) and prompt_fields:
                fields.update(prompt_fields)
            if isinstance(extra_fields, dict) and extra_fields:
                fields.update(extra_fields)
            if _BITABLE_ERROR_MONITOR_DEBUG:
                try:
                    _bitable_error_monitor_debug("fields", f"prompt_fields_keys={list((prompt_fields or {}).keys())} extra_fields_keys={list((extra_fields or {}).keys())} final_keys={list(fields.keys())}")
                except Exception:
                    pass
            if _BITABLE_ERROR_MONITOR_PUSH_DETAILS:
                fields.update({"错误": ctx["error"], "错误时间": ctx["time"], "堆栈": ctx["traceback"]})
                if not fields:
                    fields = {"错误时间": ctx["time"]}
            else:
                if not fields:
                    continue

            existing_field_info = {}
            try:
                existing_field_info = client.list_fields_info(app_token, table_id) or {}
            except Exception:
                existing_field_info = {}

            required = []
            merged_types = {}
            if isinstance(prompt_types, dict) and prompt_types:
                merged_types.update(prompt_types)
            tmap = target.get("field_types") if isinstance(target, dict) else None
            if isinstance(tmap, dict) and tmap:
                merged_types.update(tmap)

            dropped = []
            if isinstance(existing_field_info, dict) and existing_field_info:
                for k in list(fields.keys()):
                    kk = str(k).strip()
                    if not kk:
                        fields.pop(k, None)
                        continue
                    if kk not in existing_field_info:
                        continue
                    try:
                        v = fields.get(k)
                        tt = (merged_types.get(kk) or "").strip() if isinstance(merged_types, dict) else ""
                        expected_ui = tt or _bitable_error_monitor_guess_type(v)
                        expected_map = client._map_field_type(expected_ui) if expected_ui else {}
                        expected_type = expected_map.get("type") if isinstance(expected_map, dict) else None
                        actual_type = existing_field_info.get(kk, {}).get("type") if isinstance(existing_field_info.get(kk), dict) else None
                        if (expected_type is not None) and (actual_type is not None) and (int(expected_type) != int(actual_type)):
                            actual_ui = str(existing_field_info.get(kk, {}).get("ui_type") or actual_type)
                            dropped.append(f"{kk}({expected_ui}->{actual_ui})")
                            fields.pop(k, None)
                    except Exception:
                        continue

            if dropped and _BITABLE_ERROR_MONITOR_PUSH_DETAILS:
                try:
                    tail = "字段类型不匹配已跳过: " + " | ".join(dropped)
                    if isinstance(ctx.get("error"), str) and ctx["error"].strip():
                        ctx["error"] = ctx["error"].strip() + " | " + tail
                    else:
                        ctx["error"] = tail
                    if "错误" in fields:
                        fields["错误"] = ctx["error"]
                except Exception:
                    pass

            for k, v in fields.items():
                kk = str(k).strip()
                if not kk:
                    continue
                tt = (merged_types.get(kk) or "").strip() if isinstance(merged_types, dict) else ""
                required.append({"name": kk, "type": tt or _bitable_error_monitor_guess_type(v)})
            try:
                client.ensure_fields(app_token, table_id, required)
            except Exception:
                pass

            record_action = (target.get("record_action") or "append").strip()
            record_id_val = (target.get("record_id") or "").strip()
            match_field = (target.get("match_field") or "").strip()
            match_value = target.get("match_value")
            record_idx = 0
            try:
                record_idx = int(target.get("record_index") or 0)
            except Exception:
                record_idx = 0

            if isinstance(chain_record_action, str) and chain_record_action.strip():
                record_action = chain_record_action.strip()
            if isinstance(chain_record_id, str) and chain_record_id.strip():
                record_id_val = chain_record_id.strip()
            if isinstance(chain_match_field, str) and chain_match_field.strip():
                match_field = chain_match_field.strip()
                match_value = chain_match_value
            if chain_record_index is not None:
                try:
                    record_idx = int(chain_record_index or 0)
                except Exception:
                    pass

            target_record_id = None
            should_update = False

            if record_action == "update_index" and record_idx > 0:
                curr_idx = 0
                pg_token = None
                while True:
                    recs = client.list_records(app_token, table_id, view_id, 100, pg_token)
                    if not recs or not recs.get("items"):
                        break
                    items_list = recs.get("items", [])
                    if curr_idx + len(items_list) >= record_idx:
                        offset = record_idx - curr_idx - 1
                        if 0 <= offset < len(items_list):
                            target_record_id = items_list[offset].get("record_id")
                        break
                    curr_idx += len(items_list)
                    if not recs.get("has_more"):
                        break
                    pg_token = recs.get("page_token")
                if target_record_id:
                    should_update = True
            elif record_action == "update_id" and record_id_val:
                target_record_id = record_id_val
                should_update = True
            elif record_action == "update_match" and match_field:
                safe_val = str(match_value or "").replace('"', '\\"')
                filter_str = f'CurrentValue.[{match_field}] = "{safe_val}"'
                recs = client.list_records(app_token, table_id, view_id, 20, None, filter=filter_str)
                if recs and recs.get("items"):
                    target_record_id = recs.get("items")[0].get("record_id")
                    should_update = True

            if should_update and target_record_id:
                sc, st = client.update_record(app_token, table_id, target_record_id, fields)
                if sc not in (200, 201):
                    print(f"[FeishuBitable][ErrorMonitor] Update failed: {sc} {str(st)[:200]}")
            else:
                sc, st = client.create_record(app_token, table_id, fields, view_id)
                if sc not in (200, 201):
                    print(f"[FeishuBitable][ErrorMonitor] Create failed: {sc} {str(st)[:200]}")
        except Exception:
            try:
                traceback.print_exc()
            except Exception:
                pass
        finally:
            with _BITABLE_ERROR_MONITOR_LOCK:
                _BITABLE_ERROR_MONITOR_SENDING = False

class FeishuBitableErrorMonitorNode:
    CATEGORY = "maoyu/多维表格"
    OUTPUT_NODE = True
    TITLE = "飞书表格错误监控 (Bitable Error Monitor)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableErrorMonitorNode",
                display_name="Feishu Bitable 错误监控（全局）",
                category="maoyu/多维表格",
                is_output_node=True,
                inputs=[
                    io.Custom("MESSAGE_CONFIG").Input("config"),
                    io.Boolean.Input("enabled", default=True, tooltip="开启后，ComfyUI 出现错误日志会自动写入多维表格"),
                    io.Boolean.Input("push_error_details", default=True, tooltip="是否写入错误详情（错误/时间/堆栈）"),
                    io.Int.Input("cooldown_seconds", default=3, tooltip="同一时间段内最多写入一次，避免刷屏"),
                    io.Int.Input("max_chars", default=6000, tooltip="最多截取多少字符写入（过长会被截断）"),
                ],
                outputs=[io.String.Output(display_name="日志")],
            )
        @classmethod
        def execute(cls, config, enabled: bool, push_error_details: bool, cooldown_seconds: int, max_chars: int) -> io.NodeOutput:
            global _BITABLE_ERROR_MONITOR_ENABLED, _BITABLE_ERROR_MONITOR_STARTED, _BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS, _BITABLE_ERROR_MONITOR_CONFIG, _BITABLE_ERROR_MONITOR_MAX_CHARS, _BITABLE_ERROR_MONITOR_PUSH_DETAILS

            if not isinstance(config, dict):
                raise ValueError("错误监控：config 必须连接 Feishu Bitable 配置节点输出。")

            try:
                _bitable_error_monitor_try_autoconfig_from_prompt(config.get("prompt"))
            except Exception:
                pass

            cd = int(cooldown_seconds or 0)
            if cd < 0:
                cd = 0
            mc = int(max_chars or 0)
            if mc <= 0:
                mc = 6000
            if mc > 20000:
                mc = 20000

            with _BITABLE_ERROR_MONITOR_LOCK:
                _BITABLE_ERROR_MONITOR_CONFIG = config.copy()
                _BITABLE_ERROR_MONITOR_COOLDOWN_SECONDS = cd
                _BITABLE_ERROR_MONITOR_MAX_CHARS = mc
                _BITABLE_ERROR_MONITOR_ENABLED = bool(enabled)
                _BITABLE_ERROR_MONITOR_PUSH_DETAILS = bool(push_error_details)

                if not _BITABLE_ERROR_MONITOR_STARTED:
                    try:
                        import app.logger as comfy_app_logger
                        comfy_app_logger.on_flush(_bitable_error_monitor_on_flush)
                    except Exception:
                        traceback.print_exc()
                    try:
                        _bitable_error_monitor_patch_execution()
                    except Exception:
                        traceback.print_exc()
                    try:
                        _bitable_error_monitor_patch_excepthook()
                    except Exception:
                        traceback.print_exc()
                    t = threading.Thread(target=_bitable_error_monitor_worker, name="AnySwitch_BitableErrorMonitor", daemon=True)
                    t.start()
                    _BITABLE_ERROR_MONITOR_STARTED = True

            status = "启用" if enabled else "关闭"
            details = "开启" if push_error_details else "关闭"
            return io.NodeOutput(f"错误监控已{status}，错误详情={details}，cooldown={cd}s max_chars={mc}")

NODE_CLASS_MAPPINGS = {
    "FeishuBitablePushNode": FeishuBitablePushNode.Comfy,
    "FeishuBitableConfigNode": FeishuBitableConfigNode.Comfy,
    "FeishuBitableUpdateRowNode": FeishuBitableUpdateRowNode.Comfy,
    "FeishuBitableUpdateIDNode": FeishuBitableUpdateIDNode.Comfy,
    "FeishuBitableMatchNode": FeishuBitableMatchNode.Comfy,
    "FeishuBitableFieldNode": FeishuBitableFieldNode.Comfy,
    "FeishuBitableErrorMonitorNode": FeishuBitableErrorMonitorNode.Comfy
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FeishuBitablePushNode": "Feishu Bitable (飞书多维表格)",
    "FeishuBitableConfigNode": "Feishu Bitable 配置",
    "FeishuBitableUpdateRowNode": "Feishu Bitable 更新行",
    "FeishuBitableUpdateIDNode": "Feishu Bitable 更新ID",
    "FeishuBitableMatchNode": "Feishu Bitable 匹配更新",
    "FeishuBitableFieldNode": "Feishu Bitable 字段",
    "FeishuBitableErrorMonitorNode": "Feishu Bitable 错误监控（全局）"
}

def _self_test(config):
    logs = []
    app_token = (config.get("app_token") or "").strip()
    table_id = (config.get("table_id") or "").strip()
    view_id = (config.get("view_id") or "").strip()
    app_id = (config.get("feishu_app_id") or "").strip()
    app_secret = (config.get("feishu_app_secret") or "").strip()
    if not (app_token and table_id and app_id and app_secret):
        print("[FeishuBitable][SelfTest] Missing required config")
        return
    client = FeishuBitableClient(app_id, app_secret)
    app_token = client.resolve_app_token(app_token, table_id)
    name_to_id = client.list_fields_map(app_token, table_id)
    existing_names = client.list_fields(app_token, table_id)
    ts = uuid.uuid4().hex[:8]
    fields_case1 = {
        "标题": f"自测-已有字段-{ts}",
        "备注": "测试1：只写入表格已有字段"
    }
    # 使用字段名，过滤只保留已存在的列，避免 1254002/1254045
    payload1 = {k: v for k, v in fields_case1.items() if k in existing_names}
    print(f"[FeishuBitable][SelfTest] Case1 payload_count={len(payload1)}")
    s1, t1 = client.create_record(app_token, table_id, payload1, view_id if view_id else None)
    print(f"[FeishuBitable][SelfTest] Case1 http={s1} body={str(t1)[:200]}")
    new_col = f"新建列_{ts}"
    fields_case2 = {
        "标题": f"自测-创建字段-{ts}",
        "备注": "测试2：创建表格不存在的字段",
        new_col: f"created_at_{ts}"
    }
    required = [{"name": k, "type": "text"} for k in fields_case2.keys()]
    created = client.ensure_fields(app_token, table_id, required)
    print(f"[FeishuBitable][SelfTest] Case2 ensure_fields_count={len(created)}")
    # 重新获取现有列名，按字段名构造 payload
    existing_names2 = client.list_fields(app_token, table_id)
    payload2 = {k: v for k, v in fields_case2.items() if k in existing_names2}
    print(f"[FeishuBitable][SelfTest] Case2 payload_count={len(payload2)}")
    s2, t2 = client.create_record(app_token, table_id, payload2, view_id if view_id else None)
    print(f"[FeishuBitable][SelfTest] Case2 http={s2} body={str(t2)[:200]}")

try:
    _bitable_error_monitor_bootstrap()
except Exception:
    pass

if __name__ == "__main__":
    import os
    cfg = {
        "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
        "table_id": os.getenv("FEISHU_BITABLE_TABLE_ID", ""),
        "view_id": os.getenv("FEISHU_BITABLE_VIEW_ID", ""),
        "feishu_app_id": os.getenv("FEISHU_APP_ID", ""),
        "feishu_app_secret": os.getenv("FEISHU_APP_SECRET", ""),
    }
    _self_test(cfg)
