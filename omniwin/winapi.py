"""Windows API ctypes 公共辅助层 (零依赖).

集中封装: SendInput (鼠标键盘), GDI 截图, 窗口枚举, 剪贴板.
全部用纯 ctypes 直调系统 DLL, 不依赖任何第三方包.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# P2-10 修复: 声明 Per-Monitor DPI awareness, 否则进程是 DPI-unaware,
# 125% 缩放下截图/点击坐标系被虚拟化到 1536x864 (物理 1920x1080), 截图损失 44% 清晰度
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

# ======================================================================
# 常量
# ======================================================================
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0040
MOUSEEVENTF_MIDDLEUP = 0x0080
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN = 0x0D
VK_BACK = 0x08
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_ESCAPE = 0x1B

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
SM_CXSCREEN = 0
SM_CYSCREEN = 1


# ======================================================================
# SendInput 结构
# ======================================================================
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG), ("dy", wt.LONG),
        ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    _fields_ = [
        ("type", wt.DWORD),
        ("union", _U),
    ]


def _send_input(inp: _INPUT) -> None:
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        raise OSError("SendInput 调用失败 (可能被安全软件拦截)")


# ======================================================================
# 鼠标
# ======================================================================
def screen_size() -> tuple[int, int]:
    return (
        user32.GetSystemMetrics(SM_CXSCREEN),
        user32.GetSystemMetrics(SM_CYSCREEN),
    )


def _to_absolute(x: int, y: int) -> tuple[int, int]:
    """像素坐标 -> SendInput 绝对坐标 (0..65535)."""
    w, h = screen_size()
    return int(x * 65535 / max(w - 1, 1)), int(y * 65535 / max(h - 1, 1))


def mouse_move(x: int, y: int) -> None:
    ax, ay = _to_absolute(int(x), int(y))
    inp = _INPUT(INPUT_MOUSE)
    inp.union.mi.dx, inp.union.mi.dy = ax, ay
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    _send_input(inp)


def mouse_button(down: bool, button: str = "left") -> None:
    flag = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }[button]
    inp = _INPUT(INPUT_MOUSE)
    inp.union.mi.dwFlags = flag[0] if down else flag[1]
    _send_input(inp)


def click(x: int | None = None, y: int | None = None,
          button: str = "left", times: int = 1,
          interval_ms: int = 60) -> None:
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.02)
    for _ in range(max(1, times)):
        mouse_button(True, button)
        time.sleep(0.03)
        mouse_button(False, button)
        if times > 1:
            time.sleep(interval_ms / 1000)


def scroll(amount: int, horizontal: bool = False) -> None:
    """正值向上/向右, 负值向下/向左; amount 单位为系统格数(通常 3 格/格)."""
    inp = _INPUT(INPUT_MOUSE)
    inp.union.mi.mouseData = int(amount) * 120
    inp.union.mi.dwFlags = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    _send_input(inp)


def drag(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
    mouse_move(x1, y1)
    time.sleep(0.05)
    mouse_button(True)
    steps = max(2, duration_ms // 25)
    for i in range(1, steps + 1):
        mouse_move(
            x1 + (x2 - x1) * i // steps,
            y1 + (y2 - y1) * i // steps,
        )
        time.sleep(0.025)
    mouse_button(False)


# ======================================================================
# 键盘
# ======================================================================
_VK_MAP = {
    "ctrl": VK_CONTROL, "control": VK_CONTROL, "alt": VK_MENU,
    "shift": VK_SHIFT, "win": VK_LWIN, "enter": VK_RETURN, "return": VK_RETURN,
    "tab": VK_TAB, "esc": VK_ESCAPE, "escape": VK_ESCAPE, "backspace": VK_BACK,
    "space": 0x20, "delete": 0x2E, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "capslock": 0x14,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _vk_for(ch: str) -> int:
    """单字符/名称 -> 虚拟键码."""
    low = ch.lower()
    if low in _VK_MAP:
        return _VK_MAP[low]
    if len(ch) == 1:
        vk = user32.VkKeyScanW(ord(ch[0]))
        if vk != -1:
            return vk & 0xFF
    raise ValueError(f"无法识别的按键: {ch!r}")


def _key_press(vk: int, up: bool = False) -> None:
    inp = _INPUT(INPUT_KEYBOARD)
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    _send_input(inp)


def press_key(key: str) -> None:
    _key_press(_vk_for(key))
    time.sleep(0.02)
    _key_press(_vk_for(key), up=True)


def shortcut(keys: str) -> None:
    """组合键, 如 'ctrl+alt+tab' 或 'win+r'."""
    parts = [p.strip() for p in keys.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("shortcut 至少需要两个键, 例如 'ctrl+c'")
    mods, last = parts[:-1], parts[-1]
    vks = [_vk_for(m) for m in mods]
    for v in vks:
        _key_press(v)
    time.sleep(0.05)
    _key_press(_vk_for(last))
    time.sleep(0.1)   # 最后键按住 100ms (真人键速, 确保轮询/热键检测采样到)
    _key_press(_vk_for(last), up=True)
    for v in reversed(vks):
        _key_press(v, up=True)


def type_text(text: str, interval_ms: int = 5) -> None:
    """Unicode 逐字符输入 (KEYEVENTF_UNICODE), 支持中文, 不受输入法拦截影响.

    P2-11 修复: wScan 是 UTF-16 码元 (WORD), emoji 等非 BMP 字符 (U+1F600)
    会被截断。现拆成高低代理对分别发送。
    """
    units: list[int] = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF:  # 非 BMP: UTF-16 代理对
            cp -= 0x10000
            units.append(0xD800 + (cp >> 10))          # 高代理
            units.append(0xDC00 + (cp & 0x3FF))        # 低代理
        else:
            units.append(cp)
    for u in units:
        inp = _INPUT(INPUT_KEYBOARD)
        inp.union.ki.wScan = u
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE
        _send_input(inp)
        inp2 = _INPUT(INPUT_KEYBOARD)
        inp2.union.ki.wScan = u
        inp2.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _send_input(inp2)
        if interval_ms:
            time.sleep(interval_ms / 1000)


def get_cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ======================================================================
# GDI 截图 (纯 Win32, 零依赖)
# ======================================================================
def capture_screen_png(region: tuple[int, int, int, int] | None = None) -> bytes:
    """GDI 截屏并编码为 PNG (zlib + 手写 PNG 块, 标准库实现).

    region: (left, top, right, bottom) 像素坐标; None 则全屏.
    返回 PNG 字节流.
    """
    import struct
    import zlib

    if region is None:
        w, h = screen_size()
        left, top, right, bottom = 0, 0, w, h
    else:
        left, top, right, bottom = (int(v) for v in region)
        w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        raise ValueError(f"无效截图区域: {region}")

    # P3-9 修复: GDI 句柄是 64 位指针, ctypes 默认 32 位 int 返回值会截断
    # (与剪贴板部分同款坑)。显式声明 restype/argtypes。
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetDC.restype = ctypes.c_void_p  # P3-9 修正: GetDC 属于 user32
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    try:
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, left, top, 0x00CC0020)  # SRCCOPY
        # 取位图像素 (32bpp BGRA, top-down)
        class _BMIH(ctypes.Structure):
            _fields_ = [
                ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
            ]

        class _BMI(ctypes.Structure):
            _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wt.DWORD * 3)]

        bmi = _BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0):
            raise OSError("GetDIBits 失败")
        # BGRA -> PNG 的 RGB 行数据 (每行前加 filter byte 0)
        raw = bytearray()
        src = buf.raw
        row_len = w * 4
        for row in range(h):
            raw.append(0)  # PNG filter: None
            base = row * row_len
            line = src[base:base + row_len]
            for x in range(0, row_len, 4):
                b, g, r = line[x], line[x + 1], line[x + 2]
                raw += bytes((r, g, b))

        # 组装 PNG
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8bit RGB
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b"")
        )
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


# ======================================================================
# 窗口枚举
# ======================================================================
_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9
WM_CLOSE = 0x0010


def list_windows(visible_only: bool = True) -> list[dict]:
    """枚举顶层窗口, 返回 [(hwnd, title, pid, visible, rect)]."""
    results: list[dict] = []

    @ _WNDENUMPROC
    def _cb(hwnd: int, _lparam: int) -> bool:
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if visible_only and not title.strip():
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results.append({
            "hwnd": hwnd,
            "title": title,
            "pid": pid.value,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
        })
        return True

    user32.EnumWindows(_cb, 0)
    return results


def focus_window(hwnd: int) -> bool:
    """切前台; 最小化则先恢复."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))


# ======================================================================
# 剪贴板 (Unicode 文本)
# ======================================================================
def clipboard_get_text() -> str:
    if not user32.OpenClipboard(None):
        raise OSError("打不开剪贴板")
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        # 显式声明 64 位指针返回值 (ctypes 默认 32 位 int 会截断句柄)
        user32.GetClipboardData.restype = ctypes.c_void_p
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        ptr = kernel32.GlobalLock(h)
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set_text(text: str) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise OSError("打不开剪贴板")
    try:
        user32.EmptyClipboard()
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            raise OSError("GlobalAlloc 失败")
        ptr = kernel32.GlobalLock(h)
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(ctypes.c_void_p(h))
            raise OSError("SetClipboardData 失败")
        # 成功后系统接管内存, 不 GlobalFree
    finally:
        user32.CloseClipboard()
