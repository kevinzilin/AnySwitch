from .nodes import AnySwitch, AnyBooleanSwitch, AnyIsEmpty

# 尝试导入子模块中的节点
# 使用 try-except 防止因为缺少依赖（如 numpy, PIL 等）导致整个插件加载失败

# 1. dir_path 模块
try:
    from .dir_path import NODE_CLASS_MAPPINGS as _dir_nodes
    from .dir_path import NODE_DISPLAY_NAME_MAPPINGS as _dir_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from dir_path.py. Error: {e}\033[0m")
    _dir_nodes = {}
    _dir_display_names = {}

# 2. smart_gate 模块
try:
    from .smart_gate import NODE_CLASS_MAPPINGS as _gate_nodes
    from .smart_gate import NODE_DISPLAY_NAME_MAPPINGS as _gate_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from smart_gate.py. Error: {e}\033[0m")
    _gate_nodes = {}
    _gate_display_names = {}


# 5. message_pusher 模块
try:
    from .message_pusher import NODE_CLASS_MAPPINGS as _message_nodes
    from .message_pusher import NODE_DISPLAY_NAME_MAPPINGS as _message_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from message_pusher.py. Error: {e}\033[0m")
    _message_nodes = {}
    _message_display_names = {}

# 6. 多维表格 模块
try:
    from .feishu_bitable import NODE_CLASS_MAPPINGS as _bitable_nodes
    from .feishu_bitable import NODE_DISPLAY_NAME_MAPPINGS as _bitable_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from feishu_bitable.py. Error: {e}\033[0m")
    _bitable_nodes = {}
    _bitable_display_names = {}

# === 汇总所有节点 ===
NODE_CLASS_MAPPINGS = {}
# 合并子模块的节点
NODE_CLASS_MAPPINGS.update(_dir_nodes)
NODE_CLASS_MAPPINGS.update(_gate_nodes)
NODE_CLASS_MAPPINGS.update(_message_nodes)
NODE_CLASS_MAPPINGS.update(_bitable_nodes)

# 合并主模块的节点
NODE_CLASS_MAPPINGS.update({
    "AnySwitch": AnySwitch,
    "AnyBooleanSwitch": AnyBooleanSwitch,
    "AnyIsEmpty": AnyIsEmpty
})

NODE_DISPLAY_NAME_MAPPINGS = {}
# 合并子模块的显示名称
NODE_DISPLAY_NAME_MAPPINGS.update(_dir_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_gate_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_message_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_bitable_display_names)
# 合并主模块的显示名称
NODE_DISPLAY_NAME_MAPPINGS.update({
    "AnySwitch": "万能判断切换 (Any Switch)",
    "AnyBooleanSwitch": "万能开关 (Any Boolean Switch)",
    "AnyIsEmpty": "万能判空 (Any Is Empty)"
})

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
