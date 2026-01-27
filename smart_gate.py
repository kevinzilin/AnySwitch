import re

class SmartGate:
    """
    通用智能网关
    功能：不进行检测，仅接收外部数据（VLM文本或数字分数），解析后决定是否熔断。
    """
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                # 这是一个通用的输入接口，支持 String (VLM输出) 或 Float (其他节点评分)
                # 在 ComfyUI 中，你可以用 Primitive Node 转换，或者强制连接 String/Float
                "score_source": ("STRING,FLOAT,INT", {"forceInput": True}),
                "threshold": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                # 逻辑模式：大于阈值通过、小于阈值通过
                "logic_mode": (["Score > Threshold (Pass)", "Score < Threshold (Pass)"],),
            }
        }

    RETURN_TYPES = ("IMAGE", "FLOAT", "STRING")
    RETURN_NAMES = ("image_output", "parsed_score", "gate_status")

    # 定义输出别名 
    RETURN_NAMES = ("图像", "评分数值", "调试信息") 
    FUNCTION = "execute_gate"
    CATEGORY = "maoyu/utils"

    def execute_gate(self, image, score_source, threshold, logic_mode):
        score = 0.0
        
        # --- 1. 智能解析输入数据 ---
        # 无论输入是什么，尝试提取出数字
        
        if isinstance(score_source, (float, int)):
            # 如果直接是数字
            score = float(score_source)
        elif isinstance(score_source, str):
            # 如果是 VLM 的文本，例如 "Score: 8.5\nReason: Good..."
            # 使用正则提取文本中出现的第一个浮点数
            match = re.search(r"Score:\s*([-+]?\d*\.\d+|\d+)", score_source, re.IGNORECASE)
            if match:
                score = float(match.group(1))
            else:
                # 备用方案：尝试提取文本中任何数字
                fallback = re.search(r"([-+]?\d*\.\d+|\d+)", score_source)
                if fallback:
                    score = float(fallback.group(1))
                else:
                    print(f"[Gate] 警告: 无法从文本中解析分数: '{score_source}'，默认设为 0")
                    score = 0.0
        else:
            print(f"[Gate] 未知输入类型: {type(score_source)}，默认设为 0")
            score = 0.0

        # --- 2. 逻辑判断 ---
        is_passed = False
        
        if logic_mode == "Score > Threshold (Pass)":
            # 分数越高越好模式 (如 VLM 打分 0-10)
            if score >= threshold:
                is_passed = True
        else:
            # 分数越低越好模式 (如 错误率/loss)
            if score <= threshold:
                is_passed = True

        # --- 3. 执行熔断 ---
        status_msg = f"Gate: {'✅ Pass' if is_passed else '❌ Block'} | Score: {score:.2f} | Threshold: {threshold}"
        print(f"[SmartGate] {status_msg}")

        if is_passed:
            return (image, score, "Passed")
        else:
            # 熔断！返回 None，利用 ComfyUI 的 lazy evaluation 停止后续节点
            return (None, score, "Blocked")

# 注册节点
NODE_CLASS_MAPPINGS = {
    "SmartGate": SmartGate
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartGate": "Smart Gate (VLM熔断器)"
}