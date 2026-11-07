"""输入组工具 - 鼠标/键盘/文字输入 (CursorTouch 路线: SendInput 注入)."""

from __future__ import annotations

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM
from .. import winapi


@REGISTRY.register("click", "鼠标点击。可指定坐标(不传则点当前位置), 支持左/右/中键, 单击/双击/三击。",
                   danger=DANGER_MEDIUM)  # P1-6: 点击可触发任意 UI (含删除确认按钮)
def click(x: int | None = None, y: int | None = None,
          button: str = "left", times: int = 1) -> str:
    """x: 像素X坐标(可省略)
    y: 像素Y坐标(可省略)
    button: left / right / middle
    times: 点击次数(1=单击 2=双击 3=三击)"""
    if button not in ("left", "right", "middle"):
        raise ValueError("button 必须是 left/right/middle")
    winapi.click(x, y, button, times)
    where = f"({x},{y})" if (x is not None and y is not None) else "当前光标处"
    return f"已 {button} 键点击 {where} {times} 次"


@REGISTRY.register("move_mouse", "移动鼠标光标到指定坐标。", danger=DANGER_LOW)
def move_mouse(x: int, y: int) -> str:
    """x: 像素X坐标
    y: 像素Y坐标"""
    winapi.mouse_move(x, y)
    return f"光标已移动到 ({x},{y})"


@REGISTRY.register("drag", "从 (x1,y1) 按住拖拽到 (x2,y2), 用于拖文件、滑块、框选。",
                   danger=DANGER_LOW)
def drag(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> str:
    """x1: 起点X
    y1: 起点Y
    x2: 终点X
    y2: 终点Y
    duration_ms: 拖拽时长(毫秒)"""
    winapi.drag(x1, y1, x2, y2, duration_ms)
    return f"已从 ({x1},{y1}) 拖拽到 ({x2},{y2})"


@REGISTRY.register("scroll", "滚动滚轮。amount 正数=向上/右, 负数=向下/左。",
                   danger=DANGER_LOW)
def scroll(amount: int = -3, horizontal: bool = False) -> str:
    """amount: 滚动格数, 正=上/右, 负=下/左
    horizontal: true 则横向滚动"""
    winapi.scroll(amount, horizontal)
    return f"已滚动 {'横向' if horizontal else '纵向'} {amount} 格"


@REGISTRY.register("type_text", "在当前焦点位置输入文字 (Unicode 注入, 支持中文, 不经过输入法)。",
                   danger=DANGER_MEDIUM)
def type_text(text: str, clear_first: bool = False) -> str:
    """text: 要输入的文本
    clear_first: true 则先 Ctrl+A 全选再覆盖"""
    if clear_first:
        winapi.shortcut("ctrl+a")
    winapi.type_text(text)
    return f"已输入 {len(text)} 个字符"


@REGISTRY.register("press_key", "按单个键, 如 'enter' / 'esc' / 'f5' / 'a'。",
                   danger=DANGER_MEDIUM)  # P1-6: 按键可触发删除确认等 UI 操作
def press_key(key: str) -> str:
    """key: 键名 (enter/esc/tab/space/f1..f12/单字符)"""
    winapi.press_key(key)
    return f"已按下 {key}"


@REGISTRY.register("shortcut", "组合键, 如 'ctrl+c' / 'alt+tab' / 'win+r'。",
                   danger=DANGER_MEDIUM)
def shortcut(keys: str) -> str:
    """keys: 加号连接的组合, 至少两键"""
    winapi.shortcut(keys)
    return f"已执行组合键 {keys}"


@REGISTRY.register("wait", "暂停指定秒数 (操作间留缓冲, 如等窗口响应)。",
                   danger=DANGER_LOW)
def wait(seconds: float = 1.0) -> str:
    """seconds: 秒数 (0.1 - 60)"""
    seconds = max(0.1, min(60.0, float(seconds)))
    import time
    time.sleep(seconds)
    return f"已等待 {seconds} 秒"
