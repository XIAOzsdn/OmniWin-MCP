"""人类管控层 - OmniWin 的独有卖点.

任何时刻按 Ctrl+Alt+Shift+P:
- 立即冻结所有 AI 工具调用 (control_status / pause 除外)
- 冻结期间 AI 收到明确错误: SERVER_PAUSED, 提示人类已接管
- **解冻只能由人类再次按热键完成** —— resume 工具不在豁免名单里,
  AI (即使被提示注入劫持) 无法自己解除人类的冻结 (N-P0-5 修复)

设计融合:
- CursorTouch 的 "用户接管" 思路 (物理输入优先于 AI)
- danielsimonjr 的 "确认护栏" 思路 (破坏性动作需要人类点头)
延伸: 两者统一成 "冻结闸门 + 热键开关", 冻结状态对 AI 完全透明可查询,
但解冻钥匙只握在人类手里 —— 冻结是强制约束而非协作式互信.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time

from .registry import REGISTRY, DANGER_LOW, ToolError

# ----------------------------------------------------------------------
# 热键定义: Ctrl+Alt+Shift+P  (MOD_CONTROL=2 | MOD_ALT=1 | MOD_SHIFT=4)
# ----------------------------------------------------------------------
USER32 = ctypes.windll.user32
KERNEL32 = ctypes.windll.kernel32


class ControlGate:
    """冻结闸门: 全局热键 + 状态查询."""

    def __init__(self) -> None:
        self._paused = False
        self._paused_at: float | None = None
        self._pause_count = 0
        self._lock = threading.Lock()
        self._poll_thread: threading.Thread | None = None
        self._hotkey_ok: bool | None = None  # None=未启动 True/False=注册结果
        self._last_toggle = 0.0  # 防抖: 同一次按键的重复信号去重 (0.6s 窗口)

    # ------------------------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    def check_gated(self, tool_name: str) -> None:
        """工具调用前检查闸门; 冻结时抛错 (control 类工具豁免)."""
        if self._paused and tool_name not in _ALWAYS_ALLOWED:
            paused_since = (
                time.strftime("%H:%M:%S", time.localtime(self._paused_at))
                if self._paused_at
                else "?"
            )
            raise ToolError(
                f"SERVER_PAUSED: 人类已按 Ctrl+Alt+Shift+P 冻结了 AI 操作"
                f" (自 {paused_since} 起, 本次会话第 {self._pause_count} 次冻结)。"
                f"包括 resume 在内的所有工具均不可用 —— 解冻钥匙只握在人类手里,"
                f"请提示用户再次按 Ctrl+Alt+Shift+P 恢复。"
            )

    # ------------------------------------------------------------------
    def toggle(self) -> bool:
        with self._lock:
            now = time.time()
            # 防抖: RegisterHotKey 与轮询通道会对同一次按键各触发一次,
            # 0.6s 内的第二次触发视为重复, 忽略 (否则两次 toggle 相互抵消)
            if now - self._last_toggle < 0.6:
                return self._paused
            self._last_toggle = now
            self._paused = not self._paused
            if self._paused:
                self._paused_at = time.time()
                self._pause_count += 1
            else:
                self._paused_at = None
            return self._paused

    # ------------------------------------------------------------------
    def resume(self) -> bool:
        with self._lock:
            if self._paused:
                self._paused = False
                self._paused_at = None
                return True
            return False

    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "state": "paused" if self._paused else "running",
            "paused_since": (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(self._paused_at)
                )
                if self._paused_at
                else None
            ),
            "pause_count_this_session": self._pause_count,
            "hotkey": "Ctrl+Alt+Shift+P (切换冻结/恢复)",
            "hotkey_registered": self._hotkey_ok,
        }

    # ------------------------------------------------------------------
    def start_hotkey_listener(self) -> bool:
        """启动热键监听: 采用单一 GetAsyncKeyState 轮询通道 (15ms).

        设计说明: 曾尝试 RegisterHotKey + 轮询双通道, 实测双通道对同一次
        按键重复触发且 RegisterHotKey 的 WM_HOTKEY 在系统高负载下延迟可达
        秒级 (超过防抖窗口), 造成状态随机翻转 —— 已移除。轮询通道对物理
        按键与注入按键统一有效, 无时序竞争, CPU 开销可忽略 (4 次 API/30ms).
        """
        if self._poll_thread is not None:
            return True
        self._poll_thread = threading.Thread(
            target=_poll_runner, daemon=True, name="omniwin-hotkey-poll"
        )
        self._poll_thread.start()
        self._hotkey_ok = True
        return True


# ----------------------------------------------------------------------
def _toast(title: str, message: str) -> None:
    """冻结/恢复的即时视觉反馈: Windows 气泡通知 (PowerShell 代理, 零依赖).

    关键: 必须在独立线程执行 —— PowerShell 冷启动 2-5 秒, 若在轮询线程
    同步执行会阻塞热键采样, 导致下一次按键完全丢失 (实测踩坑).
    """
    def _run() -> None:
        try:
            import subprocess
            # N-P0-7 修复: title/message 是 AI 可控字符串, 直接拼进 PS 单引号
            # 字符串可注入任意命令 (审查报告第三个零门槛入口)。按 PS 规则转义。
            esc = lambda s: str(s).replace("'", "''")
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI."
                "Notifications, ContentType = WindowsRuntime] | Out-Null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]"
                "::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]"
                "::ToastText02);"
                "$x=$t.GetXml();$x.GetElementsByTagName('text').Item(0).AppendChild("
                "$x.CreateTextNode('" + esc(title) + "'))|Out-Null;"
                "$x.GetElementsByTagName('text').Item(1).AppendChild("
                "$x.CreateTextNode('" + esc(message) + "'))|Out-Null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToast"
                "Notifier('OmniWin-MCP').Show("
                "[Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=10,
                stdin=subprocess.DEVNULL,  # N-P1-9: 防止吃掉 MCP 协议流
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except Exception:
            pass  # 通知失败不影响闸门功能

    threading.Thread(target=_run, daemon=True, name="omniwin-toast").start()


# 冻结期间仍然可用的工具 (仅管控与状态查询)
# N-P0-5 修复: resume 移出豁免名单 —— 冻结是强制约束而非协作式互信,
# 被提示注入劫持的 AI 不能自己解除人类的冻结。解冻只认热键。
# (pause 保留豁免是安全的: pause 工具内部有 if not GATE.paused 保护, 不会解冻)
_ALWAYS_ALLOWED = {"control_status", "pause"}

GATE = ControlGate()


# ----------------------------------------------------------------------
# 热键检测: GetAsyncKeyState 组合键轮询 (单一通道)
# ----------------------------------------------------------------------
_POLL_KEYS = (0x11, 0x12, 0x10, 0x50)  # ctrl, alt, shift, P
_POLL_INTERVAL = 0.015  # 15ms (防止错过短按键脉冲)
_POLL_COOLDOWN = 0.5   # 触发后全键释放再保持 0.5s 才重新武装


def _poll_runner() -> None:
    """轮询组合键: 四键全按下 → 触发; 之后等全键释放+冷却期再武装, 防连发."""
    armed = True
    release_since: float | None = None
    while True:
        all_down = all(
            USER32.GetAsyncKeyState(vk) & 0x8000 for vk in _POLL_KEYS
        )
        if armed and all_down:
            now_paused = GATE.toggle()
            _toast(
                "OmniWin-MCP 已冻结" if now_paused else "OmniWin-MCP 已恢复",
                "AI 操作已被人类拦截, 再按一次恢复"
                if now_paused else "AI 操作已恢复可用",
            )
            armed = False
            release_since = None
            print(
                f"[poll] toggle → {'paused' if now_paused else 'running'}",
                file=sys.stderr, flush=True)
        elif not armed:
            if all_down:
                release_since = None
            else:
                if release_since is None:
                    release_since = time.time()
                elif time.time() - release_since >= _POLL_COOLDOWN:
                    armed = True
        time.sleep(_POLL_INTERVAL)


# ----------------------------------------------------------------------
# 管控工具注册 (永远不被冻结拦截)
# ----------------------------------------------------------------------
@REGISTRY.register(
    "control_status",
    "查询人类管控闸门状态: AI 操作当前是 running 还是 paused, 热键是否生效, "
    "本次会话被冻结过几次。冻结期间唯一可用的查询工具。",
    danger=DANGER_LOW,
)
def control_status() -> dict:
    return GATE.status()


@REGISTRY.register(
    "pause",
    "主动冻结所有 AI 桌面操作 (AI 自我也可发起), 效果等同人类按 Ctrl+Alt+Shift+P。"
    "冻结期间除管控工具外全部工具返回 SERVER_PAUSED。",
    danger=DANGER_LOW,
)
def pause() -> dict:
    # N3 修复: toggle 有 0.6s 防抖, 人类刚按过热键时 AI 的 pause 会被静默吞掉
    # 造成假成功反馈。现在轮询重试直到真实冻结 (最多 0.8s)。
    for _ in range(16):
        if not GATE.paused:
            GATE.toggle()
        if GATE.paused:
            break
        time.sleep(0.05)
    return GATE.status()


@REGISTRY.register(
    "resume",
    "解除冻结 (仅当 AI 自己 pause 且人类未介入时有效)。"
    "若冻结由人类热键发起, 本工具同样被闸门拦截 —— 解冻钥匙只握在人类手里。",
    danger=DANGER_LOW,
)
def resume() -> dict:
    GATE.resume()
    return GATE.status()
