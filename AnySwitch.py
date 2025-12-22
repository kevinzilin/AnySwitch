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
    CATEGORY = "utils"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def check(self, 优先输入=None, 备用输入=None):
        # 如果优先输入不为空，则认为激活（使用优先输入）
        is_active = 优先输入 is not None
        output_data = 优先输入 if is_active else 备用输入
        return (is_active, output_data)


NODE_CLASS_MAPPINGS = {
    "AnySwitch" : AnySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnySwitch": "万能判断切换 (Any Switch)"
}