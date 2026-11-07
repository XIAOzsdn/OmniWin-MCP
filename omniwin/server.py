"""MCP stdio JSON-RPC 协议核心 (零第三方依赖).

协议实现参考 MCP 官方规范 (2024-11-05 / 2025-06-18 均兼容):
- initialize            握手, 返回 serverInfo + capabilities
- notifications/initialized  客户端初始化完成通知 (无响应)
- ping                  心跳
- tools/list            全量工具清单 (含 JSON Schema)
- tools/call            执行工具
传输层: stdin/stdout, 每行一个 JSON-RPC 2.0 消息 (newline-delimited).
日志走 stderr, 绝不污染 stdout 协议流.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from . import SERVER_NAME, __version__
from .control import GATE
from .registry import REGISTRY, ConfirmRequired, ToolError

# 自定义 JSON-RPC 错误码 (应用层语义)
ERR_TOOL = -32000          # 工具执行失败
ERR_CONFIRM = -32001       # 危险操作缺少 confirm=true
ERR_PAUSED = -32002        # 人类已冻结 (SERVER_PAUSED)
ERR_NOT_FOUND = -32601     # 方法不存在


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id: Any, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str, data: Any = None) -> None:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    _send({"jsonrpc": "2.0", "id": req_id, "error": err})


def _log(msg: str) -> None:
    """stderr 日志 (timestamped, 参考 danielsimonjr v0.7.7 的日志实践)."""
    import time
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {SERVER_NAME}: {msg}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------
def _handle_initialize(req_id: Any, params: dict) -> None:
    client_proto = params.get("protocolVersion", "2025-06-18")
    _result(
        req_id,
        {
            "protocolVersion": client_proto,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": SERVER_NAME,
                "version": __version__,
                "vendor": "OmniWin (融合 CursorTouch / shuyu-labs / danielsimonjr 三家之长)",
            },
            "instructions": (
                "全能视窗 MCP: 桌面自动化 + OCR + 系统管理 + 安全护栏。"
                "危险操作需 confirm=true; 人类随时可按 Ctrl+Alt+Shift+P 冻结全部操作, "
                "此时工具返回 SERVER_PAUSED, 可用 control_status 查询状态。"
            ),
        },
    )


def _handle_tools_list(req_id: Any) -> None:
    _result(req_id, {"tools": REGISTRY.list_tools()})


def _handle_tools_call(req_id: Any, params: dict) -> None:
    name = params.get("name", "")
    args = params.get("arguments") or {}
    if req_id is None:
        return  # P2-13 修复: JSON-RPC 通知 (无 id) 不得返回响应

    # P2-14 修复: 按 MCP 规范, 工具执行错误放 result.isError=true,
    # 而不是 JSON-RPC error (后者会被客户端当协议错误吞掉)。
    # 错误码语义保留在文本标记里: [CONFIRM_REQUIRED -32001] / [SERVER_PAUSED -32002]
    try:
        GATE.check_gated(name)
    except ToolError as e:
        _result(req_id, {"content": [
            {"type": "text", "text": f"[SERVER_PAUSED -32002] {e}"}],
            "isError": True})
        return

    try:
        text = REGISTRY.call(name, args)
        _result(
            req_id,
            {"content": [{"type": "text", "text": text}], "isError": False},
        )
    except ConfirmRequired as e:
        _result(req_id, {"content": [
            {"type": "text", "text": f"[CONFIRM_REQUIRED -32001] {e}"}],
            "isError": True})
    except ToolError as e:
        _result(req_id, {"content": [
            {"type": "text", "text": f"[TOOL_ERROR -32000] {e}"}],
            "isError": True})
    except TypeError as e:
        _result(req_id, {"content": [
            {"type": "text", "text": f"[TOOL_ERROR -32000] 参数错误: {e}"}],
            "isError": True})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        _result(req_id, {"content": [
            {"type": "text",
             "text": f"[TOOL_ERROR -32000] 工具 {name} 执行异常: {type(e).__name__}: {e}"}],
            "isError": True})


# ----------------------------------------------------------------------
def serve(hotkey: bool = True) -> None:
    """主循环: 逐行读 stdin, 解析 JSON-RPC, 派发."""
    # 增强件自举: 把 exe/源码旁的持久 enhancements/ 目录注入 sys.path,
    # 使 install_enhancement 装的包在重启后可被 import
    from .enhancer import bootstrap_enhancement_path
    bootstrap_enhancement_path()
    # 强制 UTF-8 双向流 (PyInstaller exe 下管道默认走系统 GBK, 会把中文 JSON 写坏)
    import io
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", line_buffering=True)
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    except AttributeError:
        pass  # 无缓冲句柄的极端环境 (如 pythonw)

    if hotkey and GATE.start_hotkey_listener():
        _log(f"热键监听已启动 Ctrl+Alt+Shift+P ({REGISTRY.count} 个工具就绪)")
    else:
        if hotkey:
            _log("警告: 全局热键注册失败, 仍可用 pause/resume 工具管控")
        _log(f"启动完成, {REGISTRY.count} 个工具就绪 (热键监听未启用)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, f"JSON 解析失败: {line[:120]}")
            continue

        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            _handle_initialize(req_id, msg.get("params") or {})
        elif method == "notifications/initialized":
            _log("客户端握手完成")
        elif method == "ping":
            _result(req_id, {})
        elif method == "tools/list":
            _handle_tools_list(req_id)
        elif method == "tools/call":
            _handle_tools_call(req_id, msg.get("params") or {})
        elif method.startswith("notifications/"):
            pass  # 其他通知静默忽略 (P2-13: 通知一律不回响应)
        elif req_id is not None:
            _error(req_id, ERR_NOT_FOUND, f"未知方法: {method}")
        # 无 id 的未知通知忽略

    _log("stdin 关闭, 服务器退出")
