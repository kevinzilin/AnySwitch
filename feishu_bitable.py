import json
import os
import base64
import io as pyio
import uuid
import re
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

    def list_records(self, app_token, table_id, view_id=None, page_size=20, page_token=None, filter=None):
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
    CATEGORY = "maoyu/message"
    TITLE = "飞书表格配置 (Feishu Bitable Config)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableConfigNode",
                display_name="Feishu Bitable 配置",
                category="maoyu/message",
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
    CATEGORY = "maoyu/message"
    TITLE = "更新指定行 (Update Row)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableUpdateRowNode",
                display_name="Feishu Bitable 更新行",
                category="maoyu/message",
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
            
            # 查找或创建一个未完成的配置项
            target_index = -1
            if config["bitable_items"]:
                # 如果最后一个项没有 app_token（即尚未与 ConfigNode 绑定），则复用它
                if not config["bitable_items"][-1].get("app_token"):
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
    CATEGORY = "maoyu/message"
    TITLE = "更新记录ID (Update ID)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableUpdateIDNode",
                display_name="Feishu Bitable 更新ID",
                category="maoyu/message",
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
            
            # 查找或创建一个未完成的配置项
            target_index = -1
            if config["bitable_items"]:
                if not config["bitable_items"][-1].get("app_token"):
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
    CATEGORY = "maoyu/message"
    TITLE = "匹配字段更新 (Match Field)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableMatchNode",
                display_name="Feishu Bitable 匹配更新",
                category="maoyu/message",
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
            
            # 查找或创建一个未完成的配置项
            target_index = -1
            if config["bitable_items"]:
                if not config["bitable_items"][-1].get("app_token"):
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
    CATEGORY = "maoyu/message"
    TITLE = "表格字段 (Bitable Field)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitableFieldNode",
                display_name="Feishu Bitable 字段",
                category="maoyu/message",
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
            
            # 查找或创建一个未完成的配置项
            target_index = -1
            if config["bitable_items"]:
                # 如果最后一个项没有 app_token（即尚未与 ConfigNode 绑定），则复用它
                if not config["bitable_items"][-1].get("app_token"):
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
    CATEGORY = "maoyu/message"
    OUTPUT_NODE = True
    TITLE = "飞书多维表格 (Feishu Bitable)"
    class Comfy(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="FeishuBitablePushNode",
                display_name="Feishu Bitable (飞书多维表格)",
                category="maoyu/message",
                is_output_node=True,
                outputs=[io.String.Output(display_name="写入日志")],
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
                return io.NodeOutput(f"Error: {str(e)}")

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
                                v_paths = []
                                if "filename" in v or "video_path" in v:
                                    v_paths.append(v.get("video_path") or v.get("filename"))
                                elif "filenames" in v and isinstance(v["filenames"], list):
                                    v_paths.extend(v["filenames"])
                                elif "waveform" in v and "sample_rate" in v:
                                    pass
                                
                                v_sub = v.get("subfolder", "")
                                v_type = v.get("type", "input")
                                
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
                        if isinstance(v, list) and v and (isinstance(v[0], (bytes, bytearray)) or isinstance(v[0], MediaItem)) and field_types.get(k) == "attachment":
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

        return (" | ".join(logs),)

NODE_CLASS_MAPPINGS = {
    "FeishuBitablePushNode": FeishuBitablePushNode.Comfy,
    "FeishuBitableConfigNode": FeishuBitableConfigNode.Comfy,
    "FeishuBitableUpdateRowNode": FeishuBitableUpdateRowNode.Comfy,
    "FeishuBitableUpdateIDNode": FeishuBitableUpdateIDNode.Comfy,
    "FeishuBitableMatchNode": FeishuBitableMatchNode.Comfy,
    "FeishuBitableFieldNode": FeishuBitableFieldNode.Comfy
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FeishuBitablePushNode": "Feishu Bitable (飞书多维表格)",
    "FeishuBitableConfigNode": "Feishu Bitable 配置",
    "FeishuBitableUpdateRowNode": "Feishu Bitable 更新行",
    "FeishuBitableUpdateIDNode": "Feishu Bitable 更新ID",
    "FeishuBitableMatchNode": "Feishu Bitable 匹配更新",
    "FeishuBitableFieldNode": "Feishu Bitable 字段"
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
