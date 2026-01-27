import json
import urllib.request
import urllib.parse
import hashlib
import base64
import time
import hmac

class AnyType(str):
    """A special type that compares equal to any other type."""
    def __ne__(self, __value: object) -> bool:
        return False

    def __eq__(self, __value: object) -> bool:
        return True

    def __str__(self):
        return "*"

ANY = AnyType("*")

class MessageConfigNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "dingtalk_token": ("STRING", {"default": "", "multiline": False, "placeholder": "输入Token或完整Webhook地址"}),
                "dingtalk_secret": ("STRING", {"default": "", "multiline": False, "placeholder": "加签密钥(可选)"}),
                "feishu_webhook": ("STRING", {"default": "", "multiline": False, "placeholder": "完整Webhook地址"}),
                "feishu_secret": ("STRING", {"default": "", "multiline": False, "placeholder": "签名校验密钥(可选)"}),
                # "serverchan_key": ("STRING", {"default": "", "multiline": False, "placeholder": "SendKey"}),
            }
        }
    
    RETURN_TYPES = ("MESSAGE_CONFIG",)
    RETURN_NAMES = ("配置信息",)
    FUNCTION = "create_config"
    CATEGORY = "maoyu/message"
    TITLE = "消息推送配置 (Message Config)"

    def create_config(self, dingtalk_token="", dingtalk_secret="", feishu_webhook="", feishu_secret=""):
        config = {
            "dingtalk_token": dingtalk_token.strip(),
            "dingtalk_secret": dingtalk_secret.strip(),
            "feishu_webhook": feishu_webhook.strip(),
            "feishu_secret": feishu_secret.strip(),
            # "serverchan_key": serverchan_key.strip()
        }
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
            "optional": {
                # "image_opt": ("IMAGE",), # 预留，暂未实现图片上传
            }
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

    def push_message(self, config, title, content, any_source=None, image_opt=None):
        logs = []
        
        # 触发器判定：只有“有值”才推送
        if not self._has_value(any_source):
            log_str = "Trigger empty: skip push"
            print(f"[MessagePusher] {log_str}")
            return (log_str,)
        
        # 1. DingTalk
        if config.get("dingtalk_token"):
            try:
                res = self.push_dingtalk(config["dingtalk_token"], config["dingtalk_secret"], title, content)
                logs.append(f"DingTalk: {res}")
            except Exception as e:
                logs.append(f"DingTalk: Error({str(e)})")

        # 2. Feishu
        if config.get("feishu_webhook"):
            try:
                res = self.push_feishu(config["feishu_webhook"], config["feishu_secret"], title, content)
                logs.append(f"Feishu: {res}")
            except Exception as e:
                logs.append(f"Feishu: Error({str(e)})")

        # 3. ServerChan
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

    def push_dingtalk(self, token, secret, title, content):
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
        
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n{content}"
            }
        }
        
        res = self._send_post_json(url, data)
        if res.get("errcode") == 0:
            return "OK"
        return f"Fail({res.get('errmsg')})"

    def push_feishu(self, webhook, secret, title, content):
        url = webhook
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
            
        res = self._send_post_json(url, data)
        # 飞书成功返回 code: 0
        if res.get("code") == 0:
            return "OK"
        return f"Fail({res.get('msg')})"

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
    "MessageConfigNode": MessageConfigNode,
    "MessagePushNode": MessagePushNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MessageConfigNode": "Message Config (推送配置)",
    "MessagePushNode": "Message Push (消息推送)"
}
