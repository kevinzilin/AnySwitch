from .nodes import AnySwitch, AnyBooleanSwitch

NODE_CLASS_MAPPINGS = {
    "AnySwitch": AnySwitch,
    "AnyBooleanSwitch": AnyBooleanSwitch
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnySwitch": "万能判断切换 (Any Switch)",
    "AnyBooleanSwitch": "万能开关 (Any Boolean Switch)"
}
