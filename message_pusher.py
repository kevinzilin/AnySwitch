import json
import urllib.request
import urllib.parse
import hashlib
import base64
import time
import hmac
import io
import uuid
import requests
import numpy as np
from PIL import Image

class AnyType(str):
    """A special type that compares equal to any other type."""
    def __ne__(self, __value: object) -> bool:
        return False

    def __eq__(self, __value: object) -> bool:
        return True

    def __str__(self):
        return "*"

ANY = AnyType("*")

class DingTalkConfigNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "dingtalk_token": ("STRING", {"default": "", "multiline": False, "placeholder": "输入Token或完整Webhook地址"}),
                "dingtalk_secret": ("STRING", {"default": "", "multiline": False, "placeholder": "加签密钥(可选)"}),
                "pre_config": ("MESSAGE_CONFIG",),
            }
        }
    
    RETURN_TYPES = ("MESSAGE_CONFIG",)
    RETURN_NAMES = ("配置信息",)
    FUNCTION = "create_config"
    CATEGORY = "maoyu/message"
    TITLE = "钉钉配置 (DingTalk Config)"

    def create_config(self, dingtalk_token="", dingtalk_secret="", pre_config=None):
        config = pre_config.copy() if pre_config else {}
        
        # 初始化列表
        if "dingtalk_items" not in config:
            config["dingtalk_items"] = []
            
        # 如果有输入，则追加到列表
        if dingtalk_token.strip():
            item = {
                "token": dingtalk_token.strip(),
                "secret": dingtalk_secret.strip()
            }
            config["dingtalk_items"].append(item)
            
            # 兼容旧逻辑（保留最后一个作为默认值，防止其他节点直接读取）
            config["dingtalk_token"] = dingtalk_token.strip()
            config["dingtalk_secret"] = dingtalk_secret.strip()
            
        return (config,)

class FeishuConfigNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "feishu_webhook": ("STRING", {"default": "", "multiline": False, "placeholder": "完整Webhook地址"}),
                "feishu_secret": ("STRING", {"default": "", "multiline": False, "placeholder": "签名校验密钥(可选)"}),
                "pre_config": ("MESSAGE_CONFIG",),
            }
        }
    
    RETURN_TYPES = ("MESSAGE_CONFIG",)
    RETURN_NAMES = ("配置信息",)
    FUNCTION = "create_config"
    CATEGORY = "maoyu/message"
    TITLE = "飞书配置 (Feishu Config)"

    def create_config(self, feishu_webhook="", feishu_secret="", feishu_app_id="", feishu_app_secret="", pre_config=None):
        config = pre_config.copy() if pre_config else {}
        
        # 初始化列表
        if "feishu_items" not in config:
            config["feishu_items"] = []
            
        # 如果有输入，则追加到列表
        if feishu_webhook.strip():
            item = {
                "webhook": feishu_webhook.strip(),
                "secret": feishu_secret.strip(),
            }
            config["feishu_items"].append(item)
            
            # 兼容旧逻辑
            config["feishu_webhook"] = feishu_webhook.strip()
            config["feishu_secret"] = feishu_secret.strip()
            
        return (config,)

class GiteeConfigNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "gitee_token": ("STRING", {"default": "", "multiline": False, "placeholder": "Gitee 私人令牌"}),
                "gitee_owner": ("STRING", {"default": "", "multiline": False, "placeholder": "Gitee 用户名/组织名"}),
                "gitee_repo": ("STRING", {"default": "", "multiline": False, "placeholder": "Gitee 仓库名"}),
                "gitee_path": ("STRING", {"default": "images", "multiline": False, "placeholder": "存放路径 (例如 images)"}),
                "gitee_branch": ("STRING", {"default": "master", "multiline": False, "placeholder": "分支 (默认 master)"}),
                "pre_config": ("MESSAGE_CONFIG",),
            }
        }
    
    RETURN_TYPES = ("MESSAGE_CONFIG",)
    RETURN_NAMES = ("配置信息",)
    FUNCTION = "create_config"
    CATEGORY = "maoyu/message"
    TITLE = "Gitee图床配置 (Gitee Config)"

    def create_config(self, gitee_token="", gitee_owner="", gitee_repo="", gitee_path="images", gitee_branch="master", pre_config=None):
        config = pre_config.copy() if pre_config else {}
        if gitee_token.strip():
            config["gitee_token"] = gitee_token.strip()
        if gitee_owner.strip():
            config["gitee_owner"] = gitee_owner.strip()
        if gitee_repo.strip():
            config["gitee_repo"] = gitee_repo.strip()
        
        # 即使为空也更新，允许用户覆盖
        config["gitee_path"] = gitee_path.strip()
        config["gitee_branch"] = gitee_branch.strip()
        
        return (config,)

class MessagePushNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "config": ("MESSAGE_CONFIG",),
                "title": ("STRING", {"default": "ComfyUI 通知", "multiline": False}),
                "content": ("STRING", {"default": "任务已完成", "multiline": True}),
                "any_source": (ANY,), 
            },
            "optional": {}
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("推送日志",)
    FUNCTION = "push_message"
    CATEGORY = "maoyu/message"
    OUTPUT_NODE = True
    TITLE = "消息推送 (Message Push)"

    def _has_value(self, v):
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return len(v.strip()) > 0
        # 优先使用 size 属性（如 numpy/torch/tensor）
        try:
            size = getattr(v, "size", None)
            if size is not None:
                return int(size) > 0
        except Exception:
            pass
        # 回退：尝试长度
        try:
            return len(v) > 0
        except Exception:
            # 无法判断长度的对象，一律认为“有值”
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
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return buffered.getvalue()

    def _upload_image(self, image_bytes, config):
        # Gitee Upload
        token = config.get("gitee_token")
        owner = config.get("gitee_owner")
        repo = config.get("gitee_repo")
        path = config.get("gitee_path", "images")
        branch = config.get("gitee_branch", "master")

        if not (token and owner and repo):
            print("[MessagePusher] Gitee config missing")
            return None

        try:
            filename = f"{uuid.uuid4().hex}.png"
            # Ensure path doesn't start/end with slash
            path = path.strip("/")
            if path:
                full_path = f"{path}/{filename}"
            else:
                full_path = filename
            
            url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{full_path}"
            
            content_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            data = {
                "access_token": token,
                "content": content_base64,
                "message": f"upload from ComfyUI: {filename}",
                "branch": branch
            }
            
            res = requests.post(url, data=data, timeout=30)
            res_json = res.json()
            
            if res.status_code == 201:
                # Success
                download_url = res_json.get("content", {}).get("download_url")
                print(f"[MessagePusher] Gitee Upload Success: {download_url}")
                return download_url
            else:
                print(f"[MessagePusher] Gitee Upload Failed (Status {res.status_code}): {res_json}")
                return None
                
        except Exception as e:
            print(f"[MessagePusher] Gitee Upload Error: {e}")
            return None

    def push_message(self, config, title, content, any_source=None):
        logs = []
        
        if not self._has_value(any_source):
            log_str = "Trigger empty: skip push"
            print(f"[MessagePusher] {log_str}")
            return (log_str,)

        def is_image_like(x):
            try:
                if hasattr(x, "shape"):
                    d = len(x.shape)
                    if d == 4 or d == 3:
                        return True
            except Exception:
                return False
            return False

        text_parts = []
        image_bytes_list = []
        text_parts.append(str(content) if isinstance(content, str) else "")

        try:
            if isinstance(any_source, (list, tuple)):
                for idx, item in enumerate(any_source):
                    if is_image_like(item):
                        try:
                            if hasattr(item, "shape") and len(item.shape) == 4 and item.shape[0] > 1:
                                for b in range(int(item.shape[0])):
                                    img_batch = item[b:b+1]
                                    img_bytes = self._tensor_to_bytes(img_batch)
                                    image_bytes_list.append(img_bytes)
                            else:
                                img_bytes = self._tensor_to_bytes(item)
                                image_bytes_list.append(img_bytes)
                        except Exception as e:
                            logs.append(f"Image Error: {str(e)}")
                    else:
                        s = str(item)
                        if s.strip():
                            text_parts.append(s)
            elif is_image_like(any_source):
                if hasattr(any_source, "shape") and len(any_source.shape) == 4 and any_source.shape[0] > 1:
                    for b in range(int(any_source.shape[0])):
                        img_batch = any_source[b:b+1]
                        img_bytes = self._tensor_to_bytes(img_batch)
                        image_bytes_list.append(img_bytes)
                else:
                    img_bytes = self._tensor_to_bytes(any_source)
                    image_bytes_list.append(img_bytes)
            else:
                s = str(any_source)
                if s.strip():
                    text_parts.append(s)
        except Exception as e:
            logs.append(f"Process Error: {str(e)}")

        merged_content = text_parts[0] if text_parts else ""
        if len(text_parts) > 1:
            merged_content = (text_parts[0] + "\n\n-----------\n\n" + "\n\n-----------\n\n".join(text_parts[1:])).strip()

        image_urls = []
        for img_bytes in image_bytes_list:
            try:
                img_url = self._upload_image(img_bytes, config)
                image_urls.append(img_url)
                if img_url:
                    logs.append(f"Image Uploaded: {img_url}")
                elif config.get("gitee_token"):
                    logs.append("Gitee Upload Failed (Check console)")
            except Exception as e:
                logs.append(f"Image Upload Error: {str(e)}")

        # 1. DingTalk
        dingtalk_items = config.get("dingtalk_items", [])
        if not dingtalk_items and config.get("dingtalk_token"):
             dingtalk_items.append({
                 "token": config.get("dingtalk_token"),
                 "secret": config.get("dingtalk_secret")
             })

        for i, item in enumerate(dingtalk_items):
            try:
                res = self.push_dingtalk(item["token"], item.get("secret"), title, merged_content, image_urls)
                logs.append(f"DingTalk[{i}]: {res}")
            except Exception as e:
                logs.append(f"DingTalk[{i}]: Error({str(e)})")

        # 2. Feishu
        feishu_items = config.get("feishu_items", [])
        if not feishu_items and config.get("feishu_webhook"):
             feishu_items.append({
                 "webhook": config.get("feishu_webhook"),
                 "secret": config.get("feishu_secret"),
                 "app_id": config.get("feishu_app_id"),
                 "app_secret": config.get("feishu_app_secret")
             })
             
        for i, item in enumerate(feishu_items):
            try:
                res = self.push_feishu_item(item, title, merged_content, image_urls, image_bytes_list)
                logs.append(f"Feishu[{i}]: {res}")
            except Exception as e:
                logs.append(f"Feishu[{i}]: Error({str(e)})")

        # 3. ServerChan (Legacy, commented out)
        # if config.get("serverchan_key"):
        #     try:
        #         res = self.push_serverchan(config["serverchan_key"], title, content)
        #         logs.append(f"ServerChan: {res}")
        #     except Exception as e:
        #         logs.append(f"ServerChan: Error({str(e)})")
        
        if not logs:
            logs.append("No config provided")

        log_str = " | ".join(logs)
        print(f"[MessagePusher] {log_str}")
        return (log_str,)

    def _send_post_json(self, url, data):
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'), 
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))

    def push_dingtalk(self, token, secret, title, content, image_urls=None):
        # 处理 URL
        if token.startswith("http"):
            url = token
        else:
            url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
            
        # 处理加签
        if secret:
            timestamp = str(round(time.time() * 1000))
            secret_enc = secret.encode('utf-8')
            string_to_sign = '{}\n{}'.format(timestamp, secret)
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            if "?" in url:
                url = f"{url}&timestamp={timestamp}&sign={sign}"
            else:
                url = f"{url}?timestamp={timestamp}&sign={sign}"
        
        markdown_content = f"### {title}\n\n{content}"
        if image_urls:
            for u in image_urls:
                if u:
                    markdown_content += f"\n\n![image]({u})"

        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown_content
            }
        }
        
        res = self._send_post_json(url, data)
        if res.get("errcode") == 0:
            return "OK"
        return f"Fail({res.get('errmsg')})"

    def push_feishu_item(self, item_config, title, content, image_urls=None, image_bytes_list=None):
        webhook = item_config.get("webhook")
        secret = item_config.get("secret")
        app_id = None
        app_secret = None
        
        image_keys = []
        can_native = False
        if can_native:
            try:
                access_token = self._get_feishu_access_token(app_id, app_secret)
                if access_token:
                    for ib in image_bytes_list:
                        try:
                            k = self._upload_feishu_image(ib, access_token)
                            if k:
                                image_keys.append(k)
                        except Exception as e:
                            print(f"[MessagePusher] Feishu Image Upload Error: {e}")
            except Exception as e:
                print(f"[MessagePusher] Feishu Image Upload Error: {e}")

        # 构造消息
        data = {}
        
        if image_keys:
            data = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": title,
                            "content": [
                                [
                                    {"tag": "text", "text": f"{content}\n"}
                                ],
                                *([[{"tag": "img", "image_key": k}] for k in image_keys] if image_keys else [])
                            ]
                        }
                    }
                }
            }
        elif image_urls:
             data = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": title
                        },
                        "template": "blue"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": content
                            }
                        },
                        {
                            "tag": "hr"
                        },
                        {
                            "tag": "action",
                            "actions": [
                                *[{
                                    "tag": "button",
                                    "text": {"tag": "plain_text", "content": f"查看图片 {i+1}"},
                                    "url": u,
                                    "type": "primary"
                                } for i, u in enumerate([uu for uu in image_urls if uu])]
                            ]
                        }
                    ]
                }
            }
        else:
            data = {
                "msg_type": "text",
                "content": {
                    "text": f"{title}\n{content}"
                }
            }
        
        # 处理加签
        if secret:
            timestamp = str(int(time.time()))
            string_to_sign = '{}\n{}'.format(timestamp, secret)
            hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')
            data["timestamp"] = timestamp
            data["sign"] = sign
            
        res = self._send_post_json(webhook, data)
        if res.get("code") == 0:
            return "OK"
        return f"Fail({res.get('msg')})"

    # 保留旧方法名以防万一，但不再使用
    def push_feishu(self, config, title, content, image_url=None, image_opt=None):
        # 兼容性包装：调用 push_feishu_item
        # 但由于 push_feishu 签名依赖 config 字典，这里简单构造一个 item
        item = {
            "webhook": config.get("feishu_webhook"),
            "secret": config.get("feishu_secret"),
            "app_id": config.get("feishu_app_id"),
            "app_secret": config.get("feishu_app_secret")
        }
        image_bytes = None
        if image_opt is not None:
             image_bytes = self._tensor_to_bytes(image_opt)
        return self.push_feishu_item(item, title, content, image_url, image_bytes)

    def push_serverchan(self, key, title, content):
        # https://sctapi.ftqq.com/{key}.send
        if key.startswith("http"):
            # 用户填了完整 URL ? 
            url = key
        else:
            url = f"https://sctapi.ftqq.com/{key}.send"
            
        # Server酱通常支持 form data，但也支持 json
        # 标题长度限制 32
        data = {
            "title": title,
            "desp": content
        }
        
        res = self._send_post_json(url, data)
        if res.get("code") == 0:
            return "OK"
        return f"Fail({res.get('message')})"

NODE_CLASS_MAPPINGS = {
    "DingTalkConfigNode": DingTalkConfigNode,
    "FeishuConfigNode": FeishuConfigNode,
    "GiteeConfigNode": GiteeConfigNode,
    "MessagePushNode": MessagePushNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DingTalkConfigNode": "DingTalk Config (钉钉配置)",
    "FeishuConfigNode": "Feishu Config (飞书配置)",
    "GiteeConfigNode": "Gitee Config (Gitee图床配置)",
    "MessagePushNode": "Message Push (消息推送)"
}
