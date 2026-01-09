from .nodes import AnySwitch, AnyBooleanSwitch, AnyIsEmpty
from .dir_path import NODE_CLASS_MAPPINGS as _dir_nodes
from .dir_path import NODE_DISPLAY_NAME_MAPPINGS as _dir_display_names

NODE_CLASS_MAPPINGS = {}
NODE_CLASS_MAPPINGS.update(_dir_nodes)
NODE_CLASS_MAPPINGS.update({
    "AnySwitch": AnySwitch,
    "AnyBooleanSwitch": AnyBooleanSwitch,
    "AnyIsEmpty": AnyIsEmpty
})

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnySwitch": "万能判断切换 (Any Switch)",
    "AnyBooleanSwitch": "万能开关 (Any Boolean Switch)",
    "AnyIsEmpty": "万能判空 (Any Is Empty)"
}
NODE_DISPLAY_NAME_MAPPINGS.update(_dir_display_names)
