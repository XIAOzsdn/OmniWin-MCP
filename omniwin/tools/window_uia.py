"""窗口组 + UIA 元素组工具.

窗口管理源自 CursorTouch (App/resize/switch) + shuyu-labs (Switch/Resize),
UIA 查询走 uiautomation 库 (国产, yinkaisheng 作品, 国内主流) 可选依赖,
未安装时降级为窗口枚举 + 文字查找提示.
"""

from __future__ import annotations

import os
import subprocess

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError
from .. import winapi


# ----------------------------------------------------------------------
@REGISTRY.register("launch_app",
                   "启动应用: 按名称从开始菜单找, 或直接给 exe 绝对路径。"
                   "兼容中文应用名 (开始菜单本地化名称解析)。",
                   danger=DANGER_MEDIUM)  # P1-6: 启动应用=拉起进程
def launch_app(name: str, args: str = "", cwd: str = "") -> dict:
    """name: 应用名 (如 notepad / calc / 微信) 或 exe 绝对路径
    args: 命令行参数 (可空)
    cwd: 工作目录 (可空)"""
    if os.path.isfile(name) and name.lower().endswith(".exe"):
        target = name
    else:
        # 从开始菜单 .lnk 搜索应用名 (兼容中文)
        target = _resolve_start_menu(name)
        if not target:
            raise ToolError(
                f"开始菜单里找不到应用 '{name}'。可尝试: ①用 exe 绝对路径 "
                f"②检查名称拼写 ③该应用可能未安装"
            )
    # N-P1-10 修复: args/cwd 之前未转义 (注入点), 且失败也报 launched
    cmd = f"Start-Process -FilePath {_psq(target)}"
    if args:
        cmd += f" -ArgumentList {_psq(args)}"
    if cwd:
        cmd += f" -WorkingDirectory {_psq(cwd)}"
    r = _ps(cmd)
    if r.returncode != 0:
        raise ToolError(f"启动失败: {r.stderr.strip()[:200]}")
    return {"launched": name, "resolved": target, "exit_code": r.returncode}


def _psq(value: str) -> str:
    """PowerShell 单引号字符串转义 (P0-1 注入修复的核心).

    PS 规则: 单引号字符串内 '' 表示一个字面单引号.
    所有拼进 _ps() 的参数必须先过这里, 否则攻击者可用 ' 闭合字符串注入任意命令.
    """
    return "'" + str(value).replace("'", "''") + "'"


def _ps(command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    # 强制 PowerShell 输出 UTF-8: 其默认输出编码跟随系统代码页 (GBK),
    # 而 Python 端可能是 UTF-8 模式, 中文内容 (如服务显示名) 会触发
    # UnicodeDecodeError 导致 stdout=None. 统一双向 UTF-8 一劳永逸.
    full = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; ' + command
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", full],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
        creationflags=0x08000000,
    )


def _resolve_start_menu(name: str) -> str:
    """在开始菜单目录里按名称模糊搜 .lnk, 返回最佳匹配路径."""
    dirs = [
        os.path.join(os.environ.get("APPDATA", ""),
                     "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("ProgramData", ""),
                     "Microsoft", "Windows", "Start Menu", "Programs"),
    ]
    best, best_score = None, -1
    want = name.lower().replace(" ", "")
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if not f.lower().endswith((".lnk", ".exe")):
                    continue
                stem = os.path.splitext(f)[0].lower().replace(" ", "")
                if want == stem:
                    return os.path.join(root, f)  # 精确命中直接返回
                if want in stem:
                    score = len(want) * 100 - len(stem)
                    if score > best_score:
                        best_score, best = score, os.path.join(root, f)
    return best or ""


# ----------------------------------------------------------------------
@REGISTRY.register("list_windows", "列出当前所有可见窗口: 标题 / 句柄 / 进程PID / 位置矩形。",
                   danger=DANGER_LOW)
def list_windows() -> dict:
    wins = winapi.list_windows()
    return {"count": len(wins), "windows": wins}


@REGISTRY.register("focus_window", "把指定句柄的窗口切到前台 (最小化状态会先恢复)。",
                   danger=DANGER_MEDIUM)  # P1-6: 抢焦点
def focus_window(hwnd: int) -> dict:
    """hwnd: 窗口句柄 (从 list_windows 拿)"""
    ok = winapi.focus_window(int(hwnd))
    if not ok:
        raise ToolError(f"无法聚焦窗口 hwnd={hwnd} (可能已关闭或无权限)")
    return {"focused": True, "hwnd": int(hwnd)}


@REGISTRY.register("switch_window",
                   "按窗口标题关键词切换应用 (等效人类 alt+tab 找窗口), 中英标题均可。",
                   danger=DANGER_MEDIUM)  # P1-6: 抢焦点
def switch_window(title_keyword: str) -> dict:
    """title_keyword: 标题包含的关键词 (如 '记事本' / 'Chrome')"""
    for w in winapi.list_windows():
        if title_keyword.lower() in w["title"].lower():
            ok = winapi.focus_window(w["hwnd"])
            if not ok:  # N12: 失败不再假报成功
                raise ToolError(f"聚焦窗口失败: {w['title'][:60]}")
            return {"switched": True, "window": w}
    raise ToolError(f"没有找到标题含 '{title_keyword}' 的窗口, 可先 list_windows 看看")


@REGISTRY.register("resize_window",
                   "调整窗口位置和大小 (move_window + resize 合一)。",
                   danger=DANGER_MEDIUM)
def resize_window(hwnd: int, x: int, y: int, width: int, height: int) -> dict:
    """hwnd: 窗口句柄
    x: 新左上角X
    y: 新左上角Y
    width: 新宽度
    height: 新高度"""
    SWP_NOZORDER = 0x0004
    ok = winapi.user32.SetWindowPos(int(hwnd), 0, x, y, width, height, SWP_NOZORDER)
    if not ok:
        raise ToolError(f"SetWindowPos 失败 hwnd={hwnd}")
    return {"moved": True, "rect": [x, y, x + width, y + height]}


@REGISTRY.register("window_action",
                   "窗口动作: minimize / maximize / restore / close。关闭窗口为危险操作。",
                   danger=DANGER_MEDIUM,
                   requires_confirm=False)
def window_action(hwnd: int, action: str) -> dict:
    """hwnd: 窗口句柄
    action: minimize / maximize / restore / close"""
    actions = {
        "minimize": (winapi.user32.ShowWindow, winapi.SW_MINIMIZE),
        "maximize": (winapi.user32.ShowWindow, winapi.SW_MAXIMIZE),
        "restore": (winapi.user32.ShowWindow, winapi.SW_RESTORE),
    }
    if action in actions:
        fn, arg = actions[action]
        fn(int(hwnd), arg)
        return {"done": action, "hwnd": int(hwnd)}
    if action == "close":
        winapi.user32.PostMessageW(int(hwnd), winapi.WM_CLOSE, 0, 0)
        return {"done": "close(已发送关闭消息)", "hwnd": int(hwnd)}
    raise ValueError("action 必须是 minimize/maximize/restore/close")


# ======================================================================
# UIA 组 (uiautomation 可选依赖)
# ======================================================================
def _get_uia():
    try:
        import uiautomation as auto  # type: ignore
        return auto
    except ImportError:
        raise ToolError(
            "UIA 增强件未安装。请运行: pip install uiautomation "
            "(国产 UI 自动化库, 支持 UIA 元素树)。装完重启本服务器。"
        )


@REGISTRY.register("get_state",
                   "捕获桌面状态: 前台窗口 + 其 UI 元素树 (按钮/输入框/菜单, "
                   "含名称与坐标)。纯文本模型点按钮靠它。",
                   danger=DANGER_LOW)
def get_state(depth: int = 3, include_screenshot: bool = False) -> dict:
    """depth: 元素树深度 (1-4, 越深越全但越慢, 运行时强制 clamp)
    include_screenshot: 同时附截图路径"""
    depth = max(1, min(int(depth), 4))  # N-P1-11: 40^6≈41亿次访问的爆炸防护
    auto = _get_uia()
    ctrl = auto.GetFocusedControl() or auto.GetRootControl()
    tree = _walk_uia(ctrl, depth)
    out: dict = {"focused_window": ctrl.Name or "", "elements": tree}
    if include_screenshot:
        png = winapi.capture_screen_png(None)
        out["screenshot"] = _save_png(png)
    return out


def _save_png(png: bytes) -> str:
    import tempfile, time, uuid  # N7: uuid 后缀防同秒覆盖
    p = os.path.join(tempfile.gettempdir(),
                     f"omniwin_state_{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}.png")
    with open(p, "wb") as f:
        f.write(png)
    return p


def _walk_uia(ctrl, depth: int, max_children: int = 40) -> list:
    if depth <= 0:
        return []
    items = []
    try:
        for i, child in enumerate(ctrl.GetChildren()):
            if i >= max_children:
                items.append({"note": f"...(子元素过多已截断)"})
                break
            try:
                rect = child.BoundingRectangle
                node = {
                    "name": (child.Name or "")[:80],
                    "type": child.ControlTypeName,
                    "rect": [rect.left, rect.top, rect.right, rect.bottom],
                    "center": [(rect.left + rect.right) // 2,
                               (rect.top + rect.bottom) // 2],
                }
            except Exception:
                continue
            kids = _walk_uia(child, depth - 1, max_children)
            if kids:
                node["children"] = kids
            items.append(node)
    except Exception:
        pass
    return items


@REGISTRY.register("find_element",
                   "按名称/类型在当前前台窗口找 UI 元素 (UIA 无障碍树), 返回坐标。"
                   "找到后坐标可直接给 click。",
                   danger=DANGER_LOW)
def find_element(name: str = "", control_type: str = "",
                 depth: int = 5) -> dict:
    """name: 元素名称关键词 (按钮文字等)
    control_type: 元素类型 (Button/Edit/MenuItem...)
    depth: 搜索深度"""
    auto = _get_uia()
    if not name and not control_type:
        raise ValueError("name 和 control_type 至少给一个")
    root = auto.GetFocusedControl() or auto.GetRootControl()
    found = []

    def _walk(ctrl, d):
        if len(found) >= 10 or d <= 0:
            return
        for child in ctrl.GetChildren():
            try:
                match_n = (not name or name.lower() in (child.Name or "").lower())
                match_t = (not control_type or
                           control_type.lower() in child.ControlTypeName.lower())
                if match_n and match_t:
                    r = child.BoundingRectangle
                    found.append({
                        "name": (child.Name or "")[:80],
                        "type": child.ControlTypeName,
                        "center": [(r.left + r.right) // 2, (r.top + r.bottom) // 2],
                        "rect": [r.left, r.top, r.right, r.bottom],
                    })
            except Exception:
                pass
            _walk(child, d - 1)

    _walk(root, depth)
    return {"found": len(found), "elements": found}


@REGISTRY.register("wait_for_element",
                   "轮询等待某 UI 元素出现 (如等窗口加载完), 出现返回其坐标。",
                   danger=DANGER_LOW)
def wait_for_element(name: str, timeout_seconds: int = 15,
                     depth: int = 4) -> dict:
    """name: 元素名称关键词
    timeout_seconds: 最长等待秒数 (上限 120)
    depth: 搜索深度 (1-4, N-P1-11: 之前无深度限制会全树无限递归)"""
    import time as _t
    auto = _get_uia()
    timeout_seconds = max(1, min(int(timeout_seconds), 120))
    depth = max(1, min(int(depth), 4))
    deadline = _t.time() + timeout_seconds
    while _t.time() < deadline:
        root = auto.GetFocusedControl() or auto.GetRootControl()

        def _walk(ctrl, d):
            if d <= 0:
                return None
            for child in ctrl.GetChildren():
                try:
                    if name.lower() in (child.Name or "").lower():
                        r = child.BoundingRectangle
                        return {"name": child.Name, "center": [
                            (r.left + r.right) // 2, (r.top + r.bottom) // 2]}
                except Exception:
                    pass
                hit = _walk(child, d - 1)  # N-P1-11: 补深度限制
                if hit:
                    return hit
            return None

        hit = _walk(root, depth)
        if hit:
            return {"appeared": True, **hit}
        _t.sleep(0.8)
    return {"appeared": False, "name": name, "message": "超时未出现"}


@REGISTRY.register("interact_element",
                   "直接对 UIA 元素执行操作 (点击/聚焦/展开/选中/赋值), "
                   "比坐标点击更稳 (不受窗口遮挡影响)。",
                   danger=DANGER_MEDIUM)
def interact_element(name: str, action: str = "click", value: str = "") -> dict:
    """name: 元素名称关键词
    action: click / focus / expand / select / setvalue
    value: setvalue 时要写入的值"""
    auto = _get_uia()
    root = auto.GetFocusedControl() or auto.GetRootControl()
    target = None

    def _walk(ctrl):
        nonlocal target
        if target:
            return
        for child in ctrl.GetChildren():
            try:
                if name.lower() in (child.Name or "").lower():
                    target = child
                    return
            except Exception:
                pass
            _walk(child)

    _walk(root)
    if target is None:
        raise ToolError(f"未找到名称含 '{name}' 的元素")
    import time as _t
    if action == "click":
        target.Click(simulateMove=False, waitTime=0.1)
    elif action == "focus":
        target.SetFocus()
    elif action == "expand":
        target.Expand()
    elif action == "select":
        target.Select()
    elif action == "setvalue":
        vp = target.GetValuePattern() if hasattr(target, "GetValuePattern") else None
        if vp is None:
            raise ToolError(f"元素 '{name}' 不支持 ValuePattern (无法 setvalue)")
        vp.SetValue(value)  # N6: 之前未判空, 不支持时抛裸 AttributeError
    else:
        raise ValueError("action 必须是 click/focus/expand/select/setvalue")
    return {"done": action, "element": name, "value": value or None}
