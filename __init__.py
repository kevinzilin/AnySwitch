from .nodes import AnySwitch, AnyBooleanSwitch, AnyIsEmpty, AnyJsonGet

# 尝试导入子模块中的节点
# 使用 try-except 防止因为缺少依赖（如 numpy, PIL 等）导致整个插件加载失败

import os
import hashlib
import uuid
import traceback
import json

def _get_machine_guid() -> str:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        v, _ = winreg.QueryValueEx(k, "MachineGuid")
        return str(v or "").strip()
    except Exception:
        return ""

def _get_mac() -> str:
    try:
        n = uuid.getnode()
        if isinstance(n, int) and n > 0:
            return f"{n:012x}"
    except Exception:
        pass
    return ""

def _get_system_volume_serial() -> str:
    try:
        import ctypes
        from ctypes import wintypes
        root = os.environ.get("SystemDrive", "C:") + "\\"
        volume_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial_number = wintypes.DWORD()
        max_component_len = wintypes.DWORD()
        file_system_flags = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            wintypes.LPCWSTR(root),
            volume_name,
            261,
            ctypes.byref(serial_number),
            ctypes.byref(max_component_len),
            ctypes.byref(file_system_flags),
            fs_name,
            261,
        )
        if ok:
            return f"{int(serial_number.value):08x}"
    except Exception:
        pass
    return ""

def _device_code() -> str:
    mg = _get_machine_guid()
    mac = _get_mac()
    vs = _get_system_volume_serial()
    raw = f"AnySwitch|{mg}|{mac}|{vs}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()

def _import_anyswitch_submodule(module_basename: str):
    try:
        import sys
        import importlib
        import importlib.util
        import importlib.machinery
    except Exception as e:
        raise ImportError("import subsystem unavailable") from e

    base = str(module_basename or "").strip()
    if not base:
        raise ImportError("empty module name")

    fullname = __name__ + "." + base
    mod_dir = os.path.dirname(__file__)

    candidates = []
    candidates.append(os.path.join(mod_dir, base + ".pyd"))
    for suf in list(importlib.machinery.EXTENSION_SUFFIXES or []):
        candidates.append(os.path.join(mod_dir, base + suf))

    for p in candidates:
        if not os.path.exists(p):
            continue
        loader = importlib.machinery.ExtensionFileLoader(fullname, p)
        spec = importlib.util.spec_from_file_location(fullname, p, loader=loader)
        if spec is None:
            raise ImportError(f"failed to load spec for {base}")
        m = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = m
        loader.exec_module(m)
        return m

    raise ImportError(f"pyd module not found for {base}")

# 1. dir_path 模块
try:
    from .dir_path import NODE_CLASS_MAPPINGS as _dir_nodes
    from .dir_path import NODE_DISPLAY_NAME_MAPPINGS as _dir_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from dir_path.py. Error: {e}\033[0m")
    traceback.print_exc()
    _dir_nodes = {}
    _dir_display_names = {}

# 2. smart_gate 模块
try:
    from .smart_gate import NODE_CLASS_MAPPINGS as _gate_nodes
    from .smart_gate import NODE_DISPLAY_NAME_MAPPINGS as _gate_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from smart_gate.py. Error: {e}\033[0m")
    traceback.print_exc()
    _gate_nodes = {}
    _gate_display_names = {}


# 5. message_pusher 模块
try:
    from .message_pusher import NODE_CLASS_MAPPINGS as _message_nodes
    from .message_pusher import NODE_DISPLAY_NAME_MAPPINGS as _message_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from message_pusher.py. Error: {e}\033[0m")
    traceback.print_exc()
    _message_nodes = {}
    _message_display_names = {}

# 6. 多维表格（写入/字段组装/错误监控）模块
try:
    from .feishu_bitable_write_single import NODE_CLASS_MAPPINGS as _bitable_nodes
    from .feishu_bitable_write_single import NODE_DISPLAY_NAME_MAPPINGS as _bitable_display_names
except Exception as e:
    print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from feishu_bitable_write_single.py. Error: {e}\033[0m")
    traceback.print_exc()
    _bitable_nodes = {}
    _bitable_display_names = {}

_auth_hint_printed = False

def _print_auth_hint_once():
    global _auth_hint_printed
    if _auth_hint_printed:
        return
    _auth_hint_printed = True
    dc = ""
    try:
        dc = _device_code()
    except Exception:
        dc = ""
    print("\033[33m[AnySwitch] 未检测到有效授权：已隐藏“多维表格-查询工具/批量写入”节点。\033[0m")
    if dc:
        print(f"\033[33m[AnySwitch] 设备码（复制给作者获取离线授权）：{dc}\033[0m")
        print(f"\033[33m[AnySwitch] 授权文件路径：{os.path.join(os.path.dirname(__file__), 'license.lic')}\033[0m")

def _safe_load_protected(module_name: str):
    try:
        m = _import_anyswitch_submodule(module_name)
        nodes = getattr(m, "NODE_CLASS_MAPPINGS", {}) if m is not None else {}
        names = getattr(m, "NODE_DISPLAY_NAME_MAPPINGS", {}) if m is not None else {}
        return nodes, names
    except ImportError as e:
        if "unlicensed" in str(e).lower():
            _print_auth_hint_once()
            return {}, {}
        print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from {module_name}. Error: {e}\033[0m")
        traceback.print_exc()
        return {}, {}
    except Exception as e:
        print(f"\033[33m[AnySwitch] Warning: Failed to load nodes from {module_name}. Error: {e}\033[0m")
        traceback.print_exc()
        return {}, {}

_bitable_query_nodes, _bitable_query_display_names = _safe_load_protected("feishu_bitable_query_tools")
_bitable_write_nodes, _bitable_write_display_names = _safe_load_protected("feishu_bitable_write_batch")

def _patch_force_query_behavior():
    cls = None
    try:
        cls = (_bitable_query_nodes or {}).get("FeishuBitableQueryRecordsNode")
    except Exception:
        cls = None
    if cls is None:
        return
    if getattr(cls, "_anyswitch_force_query_patched", False):
        return
    cls._anyswitch_force_query_patched = True

    def _stable_fingerprint(v):
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        try:
            return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            try:
                return str(v)
            except Exception:
                return repr(v)

    @classmethod
    def IS_CHANGED(c, *args, **kwargs):
        if bool(kwargs.get("force_query", False)):
            import time
            return time.time_ns()
        try:
            payload = {k: _stable_fingerprint(v) for k, v in (kwargs or {}).items()}
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8", errors="ignore")
            return hashlib.sha256(raw).hexdigest()
        except Exception:
            return None

    cls.IS_CHANGED = IS_CHANGED

    if hasattr(cls, "fingerprint_inputs"):
        old_fingerprint_inputs = cls.fingerprint_inputs

        @classmethod
        def fingerprint_inputs(c, *args, **kwargs):
            if bool(kwargs.get("force_query", False)):
                import time
                return time.time_ns()
            return old_fingerprint_inputs(*args, **kwargs)

        cls.fingerprint_inputs = fingerprint_inputs

    if hasattr(cls, "execute"):
        try:
            from comfy_api.latest import io as _io_anyswitch
        except Exception:
            _io_anyswitch = None

        old_execute = cls.execute

        @classmethod
        def execute(c, *args, **kwargs):
            import time
            run_id = int(time.time_ns())
            out = old_execute(*args, **kwargs)
            if _io_anyswitch is None:
                return out
            try:
                if isinstance(out, _io_anyswitch.NodeOutput):
                    args2 = list(out.args or ())
                    if len(args2) >= 5:
                        try:
                            args2[4] = f"run_id={run_id} | {str(args2[4] or '')}"
                        except Exception:
                            pass
                    return _io_anyswitch.NodeOutput(*args2, ui=out.ui, expand=out.expand, block_execution=getattr(out, "block_execution", None))
                if isinstance(out, dict) and "result" in out:
                    res = out.get("result")
                    if isinstance(res, (list, tuple)) and len(res) >= 5:
                        res = list(res)
                        try:
                            res[4] = f"run_id={run_id} | {str(res[4] or '')}"
                        except Exception:
                            pass
                        out["result"] = tuple(res)
                    return out
            except Exception:
                return out
            return out

        cls.execute = execute

_patch_force_query_behavior()

# === 汇总所有节点 ===
NODE_CLASS_MAPPINGS = {}
# 合并子模块的节点
NODE_CLASS_MAPPINGS.update(_dir_nodes)
NODE_CLASS_MAPPINGS.update(_gate_nodes)
NODE_CLASS_MAPPINGS.update(_message_nodes)
NODE_CLASS_MAPPINGS.update(_bitable_nodes)
NODE_CLASS_MAPPINGS.update(_bitable_query_nodes)
NODE_CLASS_MAPPINGS.update(_bitable_write_nodes)

# 合并主模块的节点
NODE_CLASS_MAPPINGS.update({
    "AnySwitch": AnySwitch,
    "AnyBooleanSwitch": AnyBooleanSwitch,
    "AnyIsEmpty": AnyIsEmpty,
    "AnyJsonGet": AnyJsonGet
})

NODE_DISPLAY_NAME_MAPPINGS = {}
# 合并子模块的显示名称
NODE_DISPLAY_NAME_MAPPINGS.update(_dir_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_gate_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_message_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_bitable_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_bitable_query_display_names)
NODE_DISPLAY_NAME_MAPPINGS.update(_bitable_write_display_names)
# 合并主模块的显示名称
NODE_DISPLAY_NAME_MAPPINGS.update({
    "AnySwitch": "万能判断切换 (Any Switch)",
    "AnyBooleanSwitch": "万能开关 (Any Boolean Switch)",
    "AnyIsEmpty": "万能判空 (Any Is Empty)",
    "AnyJsonGet": "JSON取值 (JSON Get)"
})

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
