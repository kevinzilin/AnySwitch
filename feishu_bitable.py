import json
import os
import base64
import io as pyio
import uuid
import requests
import numpy as np
from PIL import Image
from comfy_api.latest import io

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
        url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
        headers = {"Authorization": f"Bearer {t}"}
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"file_name": filename, "parent_type": "bitable_image", "parent_node": app_token, "size": str(len(image_bytes))}
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
                    io.String.Input("app_token", default="", tooltip="飞书多维表格 App Token"),
                    io.String.Input("table_id", default="", tooltip="数据表 ID"),
                    io.String.Input("view_id", default="", tooltip="视图 ID（可选）"),
                    io.String.Input("feishu_app_id", default="", tooltip="飞书应用 App ID（用于鉴权）", optional=True),
                    io.String.Input("feishu_app_secret", default="", tooltip="飞书应用 App Secret（用于鉴权）", optional=True),
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, app_token: str, table_id: str, view_id: str, feishu_app_id: str, feishu_app_secret: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_items" not in config:
                config["bitable_items"] = []
            if app_token.strip() and table_id.strip():
                config["bitable_items"].append({
                    "app_token": app_token.strip(),
                    "table_id": table_id.strip(),
                    "view_id": view_id.strip()
                })
            if feishu_app_id.strip():
                config["feishu_app_id"] = feishu_app_id.strip()
            if feishu_app_secret.strip():
                config["feishu_app_secret"] = feishu_app_secret.strip()
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
                    io.String.Input("field_name", default="标题", tooltip="多维表格列名"),
                    io.AnyType.Input("field_value", optional=True),
                    io.Combo.Input("field_type", options=[
                        *TYPE_OPTIONS_DISPLAY
                    ], default="文本", tooltip="字段类型"),
                    io.Custom("MESSAGE_CONFIG").Input("pre_config", optional=True),
                ],
                outputs=[io.Custom("MESSAGE_CONFIG").Output(display_name="配置信息")],
            )
        @classmethod
        def execute(cls, field_name: str, field_value, field_type: str, pre_config=None) -> io.NodeOutput:
            config = pre_config.copy() if pre_config else {}
            if "bitable_fields" not in config:
                config["bitable_fields"] = []
            name = (field_name or "").strip()
            if name:
                config["bitable_fields"].append({
                    "name": name,
                    "value": field_value,
                    "type": field_type
                })
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

    def _upload_image_gitee(self, image_bytes, config):
        token = config.get("gitee_token")
        owner = config.get("gitee_owner")
        repo = config.get("gitee_repo")
        path = config.get("gitee_path", "images")
        branch = config.get("gitee_branch", "master")
        if not (token and owner and repo):
            return None
        try:
            filename = f"{uuid.uuid4().hex}.png"
            path = path.strip("/")
            full_path = f"{path}/{filename}" if path else filename
            url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{full_path}"
            content_base64 = base64.b64encode(image_bytes).decode('utf-8')
            data = {"access_token": token, "content": content_base64, "message": f"upload: {filename}", "branch": branch}
            res = requests.post(url, data=data, timeout=30)
            j = res.json()
            if res.status_code == 201:
                return j.get("content", {}).get("download_url")
        except Exception:
            return None
        return None
    
    def _image_bytes_to_data_url(self, image_bytes):
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return None

    def push_bitable(self, config):
        logs = []
        fields = {}
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

        extra_fields = config.get("bitable_fields", [])
        print(f"[FeishuBitable] extra_fields count={len(extra_fields)}")
        field_types = {}
        def _norm_type(t):
            try:
                s = str(t or "").strip().lower()
            except Exception:
                return "text"
            return TYPE_ALIASES.get(s, s if s else "text")
        for f in extra_fields:
            name = f.get("name")
            ftype = _norm_type((f.get("type") or "text").strip().lower())
            value = f.get("value")
            if not name:
                continue
            field_types[name] = ftype
            if ftype in ("attachment", "url"):
                has_gitee = bool(config.get("gitee_token")) and bool(config.get("gitee_owner")) and bool(config.get("gitee_repo"))
                if isinstance(value, list):
                    urls = []
                    attachments = []
                    for v in value:
                        if _is_url_string(v):
                            urls.append(v.strip())
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
                                                logs.append(f"Uploaded: {u}")
                                            elif config.get("gitee_token"):
                                                logs.append("Gitee Upload Failed")
                                            if not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    urls.append(du)
                                                    logs.append("Fallback: data-url")
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                urls.append(du)
                                                logs.append("Fallback: data-url")
                                else:
                                    ib = _value_to_image_bytes(v)
                                    if ib:
                                        if ftype == "attachment":
                                            attachments.append(ib)
                                        elif has_gitee:
                                            u = self._upload_image_gitee(ib, config)
                                            if u:
                                                urls.append(u)
                                                logs.append(f"Uploaded: {u}")
                                            elif config.get("gitee_token"):
                                                logs.append("Gitee Upload Failed")
                                            if not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    urls.append(du)
                                                    logs.append("Fallback: data-url")
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                urls.append(du)
                                                logs.append("Fallback: data-url")
                            except Exception:
                                pass
                    if ftype == "attachment":
                        fields[name] = attachments
                    else:
                        if ftype == "url":
                            if has_gitee and urls:
                                fields[name] = "\n".join(urls)
                            else:
                                # 无图床时，URL列改为写附件到“列名附件”
                                fallback_name = f"{name}附件"
                                field_types[fallback_name] = "attachment"
                                # 尝试从原值重新收集附件
                                att2 = []
                                try:
                                    for vv in value:
                                        if _is_url_string(vv):
                                            continue
                                        if is_image_like(vv) and hasattr(vv, "shape") and len(vv.shape) == 4 and int(vv.shape[0]) > 1:
                                            for b in range(int(vv.shape[0])):
                                                ibb = self._tensor_to_bytes(vv[b:b+1])
                                                att2.append(ibb)
                                        else:
                                            ibb = _value_to_image_bytes(vv)
                                            if ibb:
                                                att2.append(ibb)
                                except Exception:
                                    pass
                                if att2:
                                    fields[fallback_name] = att2
                                    logs.append(f"URL fallback to attachment: {fallback_name}")
                        else:
                            if urls:
                                fields[name] = "\n".join(urls)
                else:
                    if _is_url_string(value):
                        fields[name] = value.strip()
                    else:
                        try:
                            if is_image_like(value) and hasattr(value, "shape") and len(value.shape) == 4 and int(value.shape[0]) > 1:
                                if ftype == "attachment":
                                    attachments = []
                                    for b in range(int(value.shape[0])):
                                        ib = self._tensor_to_bytes(value[b:b+1])
                                        attachments.append(ib)
                                    fields[name] = attachments
                                else:
                                    urls = []
                                    for b in range(int(value.shape[0])):
                                        ib = self._tensor_to_bytes(value[b:b+1])
                                        if has_gitee:
                                            u = self._upload_image_gitee(ib, config)
                                            if u:
                                                urls.append(u)
                                                logs.append(f"Uploaded: {u}")
                                            elif config.get("gitee_token"):
                                                logs.append("Gitee Upload Failed")
                                            if not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    urls.append(du)
                                                    logs.append("Fallback: data-url")
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                urls.append(du)
                                                logs.append("Fallback: data-url")
                                    if urls:
                                        if ftype == "url":
                                            if has_gitee:
                                                fields[name] = "\n".join(urls)
                                            else:
                                                # 无图床时，URL列改为写附件到“列名附件”
                                                fallback_name = f"{name}附件"
                                                field_types[fallback_name] = "attachment"
                                                att_single = []
                                                try:
                                                    for b in range(int(value.shape[0])):
                                                        ibb = self._tensor_to_bytes(value[b:b+1])
                                                        att_single.append(ibb)
                                                except Exception:
                                                    pass
                                                if att_single:
                                                    fields[fallback_name] = att_single
                                                    logs.append(f"URL fallback to attachment: {fallback_name}")
                                        else:
                                            fields[name] = "\n".join(urls)
                            else:
                                ib = _value_to_image_bytes(value)
                                if ib:
                                    if ftype == "attachment":
                                        fields[name] = [ib]
                                    elif has_gitee:
                                        u = self._upload_image_gitee(ib, config)
                                        if u:
                                            fields[name] = u
                                            logs.append(f"Uploaded: {u}")
                                        elif config.get("gitee_token"):
                                            logs.append("Gitee Upload Failed")
                                        if not u:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                if ftype == "url":
                                                    # 无图床：改为附件列
                                                    fallback_name = f"{name}附件"
                                                    field_types[fallback_name] = "attachment"
                                                    fields[fallback_name] = [ib]
                                                    logs.append(f"URL fallback to attachment: {fallback_name}")
                                                else:
                                                    fields[name] = du
                                                logs.append("Fallback: data-url")
                                    else:
                                        du = self._image_bytes_to_data_url(ib)
                                        if du:
                                            if ftype == "url":
                                                fallback_name = f"{name}附件"
                                                field_types[fallback_name] = "attachment"
                                                fields[fallback_name] = [ib]
                                                logs.append(f"URL fallback to attachment: {fallback_name}")
                                            else:
                                                fields[name] = du
                                            logs.append("Fallback: data-url")
                                else:
                                    fields[name] = str(value)
                        except Exception:
                            fields[name] = str(value)
            else:
                if isinstance(value, list):
                    sep = "\n\n-----------\n\n"
                    parts = []
                    for v in value:
                        if _is_url_string(v):
                            s = v.strip()
                            if s:
                                parts.append(s)
                        elif is_image_like(v):
                            try:
                                if hasattr(v, "shape") and len(v.shape) == 4 and int(v.shape[0]) > 1:
                                    for b in range(int(v.shape[0])):
                                        ib = self._tensor_to_bytes(v[b:b+1])
                                        if ib:
                                            if bool(config.get("gitee_token")) and bool(config.get("gitee_owner")) and bool(config.get("gitee_repo")):
                                                u = self._upload_image_gitee(ib, config)
                                                if u:
                                                    parts.append(u)
                                                    logs.append(f"Uploaded: {u}")
                                                elif config.get("gitee_token"):
                                                    logs.append("Gitee Upload Failed")
                                                if not u:
                                                    du = self._image_bytes_to_data_url(ib)
                                                    if du:
                                                        parts.append(du)
                                                        logs.append("Fallback: data-url")
                                            else:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    parts.append(du)
                                                    logs.append("Fallback: data-url")
                                else:
                                    ib = _value_to_image_bytes(v)
                                    if ib:
                                        if bool(config.get("gitee_token")) and bool(config.get("gitee_owner")) and bool(config.get("gitee_repo")):
                                            u = self._upload_image_gitee(ib, config)
                                            if u:
                                                parts.append(u)
                                                logs.append(f"Uploaded: {u}")
                                            elif config.get("gitee_token"):
                                                logs.append("Gitee Upload Failed")
                                            if not u:
                                                du = self._image_bytes_to_data_url(ib)
                                                if du:
                                                    parts.append(du)
                                                    logs.append("Fallback: data-url")
                                        else:
                                            du = self._image_bytes_to_data_url(ib)
                                            if du:
                                                parts.append(du)
                                                logs.append("Fallback: data-url")
                            except Exception:
                                s = str(v)
                                if s.strip():
                                    parts.append(s)
                        else:
                            s = str(v)
                            if s.strip():
                                parts.append(s)
                    fields[name] = sep.join(parts) if parts else ""
                else:
                    fields[name] = str(value)

        items = config.get("bitable_items", [])
        print(f"[FeishuBitable] bitable_items count={len(items)}")

        def push_one(app_token, table_id, v_id):
            client = FeishuBitableClient(config.get("feishu_app_id"), config.get("feishu_app_secret"))
            resolved_app_token = client.resolve_app_token(app_token, table_id)
            if resolved_app_token != app_token:
                print(f"[FeishuBitable] app_token resolved to: {resolved_app_token}")
            required = []
            # 1. 先把 explicit 的配置加进去，构建一个名字集合
            _explicit_names = set()
            for f in extra_fields:
                if f.get("name"):
                    required.append({"name": f.get("name"), "type": f.get("type", "text")})
                    _explicit_names.add(f.get("name"))
            
            # 2. 再把 fields 里生成出来的 key 加进去，如果还没加过的话
            for k in fields.keys():
                if k not in _explicit_names:
                    # 优先从 field_types 获取类型（这里包含了 fallback 的附件列类型）
                    ft = field_types.get(k, "text")
                    required.append({"name": k, "type": ft})
            created = client.ensure_fields(resolved_app_token, table_id, required)
            for n, c, t in created:
                if c in (200, 201):
                    logs.append(f"Field Created: {n}")
                    print(f"[FeishuBitable] Field Created: {n}")
                else:
                    logs.append(f"Field Create Fail[{n}]: {c} {t}")
                    print(f"[FeishuBitable] Field Create Fail[{n}]: {c} {t}")
            # 将字段名转换为 field_id，再写入记录
            name_to_id = client.list_fields_map(resolved_app_token, table_id)
            fields_info = client.list_fields_info(resolved_app_token, table_id)
            print(f"[FeishuBitable] name_to_id size={len(name_to_id)}")
            # 仅按现有“列名”过滤，发送字段名 -> 值，避免 1254045（要求 field_name）
            fields_payload = {}
            if name_to_id:
                for k, v in fields.items():
                    if k in name_to_id:
                        if isinstance(v, list) and v and isinstance(v[0], (bytes, bytearray)) and field_types.get(k) == "attachment":
                            tokens = []
                            for idx, ib in enumerate(v):
                                try:
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
                                            # 解析返回的 field_id
                                            try:
                                                import time
                                                time.sleep(0.5) # 等待字段创建生效
                                                rj = json.loads(st)
                                                fid = rj.get("data", {}).get("field", {}).get("field_id")
                                                if fid:
                                                    target_name = fid
                                                    print(f"[FeishuBitable] Use new field_id: {fid}")
                                            except Exception:
                                                pass
                                            # 刷新映射
                                            name_to_id = client.list_fields_map(resolved_app_token, table_id)
                                            fields_info = client.list_fields_info(resolved_app_token, table_id)
                            except Exception as e:
                                logs.append(f"Attachment Field Check Error: {str(e)}")
                            if tokens:
                                fields_payload[target_name] = tokens
                        else:
                            fields_payload[k] = v
                    else:
                        # 新列未存在但我们要写附件：自动创建后写入
                        if isinstance(v, list) and v and isinstance(v[0], (bytes, bytearray)) and field_types.get(k) == "attachment":
                            sc, st = client.create_field(resolved_app_token, table_id, k, "attachment")
                            logs.append(f"Auto Create Attachment Field[{k}]: {sc}")
                            target_key = k
                            if sc in (200, 201):
                                try:
                                    import time
                                    time.sleep(0.5)
                                    rj = json.loads(st)
                                    fid = rj.get("data", {}).get("field", {}).get("field_id")
                                    if fid:
                                        target_key = fid
                                        print(f"[FeishuBitable] Use new field_id: {fid}")
                                except Exception:
                                    pass
                                name_to_id = client.list_fields_map(resolved_app_token, table_id)
                                fields_info = client.list_fields_info(resolved_app_token, table_id)
                                tokens = []
                                for ib in v:
                                    try:
                                        ftok = client.upload_attachment(resolved_app_token, ib, f"image_{uuid.uuid4().hex}.png")
                                        if ftok:
                                            tokens.append({"file_token": ftok})
                                            logs.append(f"Attachment Uploaded: {ftok}")
                                    except Exception as e:
                                        logs.append(f"Attachment Upload Error: {str(e)}")
                                if tokens:
                                    fields_payload[target_key] = tokens
                        else:
                            # 非附件类型的新列，直接尝试创建文本列
                            sc, st = client.create_field(resolved_app_token, table_id, k, field_types.get(k, "text"))
                            logs.append(f"Auto Create Field[{k}]: {sc}")
                            target_key = k
                            if sc in (200, 201):
                                try:
                                    import time
                                    time.sleep(0.5)
                                    rj = json.loads(st)
                                    fid = rj.get("data", {}).get("field", {}).get("field_id")
                                    if fid:
                                        target_key = fid
                                        print(f"[FeishuBitable] Use new field_id: {fid}")
                                except Exception:
                                    pass
                                name_to_id = client.list_fields_map(resolved_app_token, table_id)
                                fields_info = client.list_fields_info(resolved_app_token, table_id)
                                fields_payload[target_key] = v
                print(f"[FeishuBitable] payload_by_name_filtered count={len(fields_payload)}")
            else:
                fields_payload = fields
                print(f"[FeishuBitable] payload_by_name count={len(fields_payload)}")
            def _as_rich_text(v):
                s = str(v or "")
                return [{"text": s, "type": "text"}] if len(s) > 0 else []
            def _to_rich_payload(p):
                rp = {}
                for k, v in p.items():
                    if isinstance(v, str):
                        rp[k] = _as_rich_text(v)
                    else:
                        rp[k] = v
                return rp
            try:
                http_status, text = client.create_record(resolved_app_token, table_id, fields_payload, v_id if (v_id or "").strip() else None)
            except Exception as e:
                logs.append(f"Create record error: {str(e)}")
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
                print(f"[FeishuBitable] Push http={http_status} body_not_json")
                success = http_status in (200, 201)
            if (not success) and need_retry_rich:
                rich_payload = _to_rich_payload(fields_payload)
                try:
                    http_status, text = client.create_record(resolved_app_token, table_id, rich_payload, v_id if (v_id or "").strip() else None)
                except Exception as e:
                    logs.append(f"Create record retry error: {str(e)}")
                    http_status, text = 0, str(e)
                try:
                    j = json.loads(text)
                    api_code = j.get("code", -1)
                    success = (http_status in (200, 201)) and (api_code == 0)
                    print(f"[FeishuBitable] Retry http={http_status} api_code={api_code}")
                except Exception:
                    success = http_status in (200, 201)
            if success:
                logs.append(f"Feishu Bitable[{table_id}]: OK")
            else:
                logs.append(f"Feishu Bitable[{table_id}]: Fail({http_status}) {text}")

        if items:
            for it in items:
                push_one(it.get("app_token", ""), it.get("table_id", ""), it.get("view_id", ""))
        else:
            # 兼容老参数：当未使用配置节点时，允许直接填写
            app_token = config.get("bitable_app_token", "") or ""
            table_id = config.get("bitable_table_id", "") or ""
            if not (app_token and table_id):
                logs.append("No Bitable target in config")
                print("[FeishuBitable] No Bitable target in config")
            else:
                push_one(app_token, table_id, "")

        return (" | ".join(logs),)

NODE_CLASS_MAPPINGS = {
    "FeishuBitablePushNode": FeishuBitablePushNode.Comfy,
    "FeishuBitableConfigNode": FeishuBitableConfigNode.Comfy,
    "FeishuBitableFieldNode": FeishuBitableFieldNode.Comfy
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FeishuBitablePushNode": "Feishu Bitable (飞书多维表格)",
    "FeishuBitableConfigNode": "Feishu Bitable 配置",
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
