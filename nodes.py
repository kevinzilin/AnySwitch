from comfy_execution.graph import ExecutionBlocker

class AnyType(str):
    """A special type that compares equal to any other type."""
    def __ne__(self, __value: object) -> bool:
        return False

    def __eq__(self, __value: object) -> bool:
        return True

    def __str__(self):
        return "*"

ANY = AnyType("*")

class AnySwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "优先输入": (ANY,),
                "备用输入": (ANY,)
            }
        }

    RETURN_TYPES = ("BOOLEAN", ANY)
    RETURN_NAMES = ("是否启用优先", "输出结果")
    FUNCTION = "check"
    CATEGORY = "maoyu/utils"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def check(self, 优先输入=None, 备用输入=None):
        # 如果优先输入不为空，则认为激活（使用优先输入）
        is_active = 优先输入 is not None
        output_data = 优先输入 if is_active else 备用输入
        return (is_active, output_data)

class AnyBooleanSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入": (ANY,),
                "开关": ("BOOLEAN", {"default": True, "label_on": "开启", "label_off": "关闭"}),
            }
        }

    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出结果",)
    FUNCTION = "process"
    CATEGORY = "maoyu/utils"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def process(self, 开关, 输入=None):
        if 开关:
            return (输入,)
        else:
            return (ExecutionBlocker(None),)

class AnyIsEmpty:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "input_data": (ANY,),
            }
        }

    RETURN_TYPES = ("BOOLEAN",)
    RETURN_NAMES = ("是否为空",)
    FUNCTION = "check_empty"
    CATEGORY = "maoyu/utils"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def check_empty(self, input_data=None):
        # 1. 优先判断是否为 None
        if input_data is None:
            return (True,)
        
        # 2. 尝试判断长度 (针对列表、字符串、字典等容器)
        # 注意：不直接使用 if not input_data，因为这样会误判 0, False 等有效值
        try:
            if hasattr(input_data, "__len__") and len(input_data) == 0:
                return (True,)
        except:
            # 如果获取长度出错（例如某些特殊的 tensor），则保守认为不为空
            pass
            
        return (False,)
