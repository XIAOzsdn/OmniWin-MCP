"""安全组 (签名校验/Defender/防火墙) + 注册表组 + 网络组 + 杂项组."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError
from .window_uia import _ps, _psq


# ======================================================================
# 安全组 (danielsimonjr 同款)
# ======================================================================
@REGISTRY.register("verify_signature",
                   "校验文件数字签名 (发行者/是否可信), 下载的工具先验一下再跑。",
                   danger=DANGER_LOW)
def verify_signature(path: str) -> dict:
    """path: 文件绝对路径"""
    # P0-1 修复: path 之前直接拼进 PS, 单引号闭合即可注入任意命令
    r = _ps(
        f"$sig = Get-AuthenticodeSignature {_psq(path)}; "
        "$sig | Select-Object Status, StatusMessage, "
        "@{n='signer';e={$_.SignerCertificate.Subject}} | ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise ToolError(f"签名查询失败: {r.stderr[:200]}")
    return data if data else {"status": "查询失败"}


@REGISTRY.register("defender_status", "Windows Defender 状态 (是否启用/实时保护/病毒库版本)。",
                   danger=DANGER_LOW)
def defender_status() -> dict:
    r = _ps(
        "Get-MpComputerStatus | Select-Object AMServiceEnabled, "
        "RealTimeProtectionEnabled, AntivirusSignatureLastUpdated, "
        "AntivirusSignatureVersion, QuickScanEndTime | ConvertTo-Json -Compress"
    )
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise ToolError(f"Defender 查询失败: {r.stderr[:200]}")


@REGISTRY.register("firewall_status", "查看防火墙各配置文件 (域/专用/公用) 开启状态。",
                   danger=DANGER_LOW)
def firewall_status() -> dict:
    r = _ps(
        "Get-NetFirewallProfile | Select-Object Name, Enabled | "
        "ConvertTo-Json -Compress"
    )
    rows = json.loads(r.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {"profiles": rows}


@REGISTRY.register("firewall_rule",
                   "防火墙规则管理: list / add / remove。add/remove 为高危。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="改错防火墙规则可能导致断网或暴露端口")
def firewall_rule(action: str, name: str = "", direction: str = "inbound",
                  port: int = 0, protocol: str = "TCP",
                  allow: bool = True) -> dict:
    """action: list / add / remove
    name: 规则名 (list 时可作过滤)
    direction: inbound / outbound
    port: 端口号 (add 用)
    protocol: TCP / UDP / ICMPv4 / ICMPv6
    allow: true=放行 false=阻止
    confirm: 必须传 true"""
    # P0-1 修复: action/direction/protocol 白名单, name 转义
    if action not in ("list", "add", "remove"):
        raise ValueError("action 必须是 list/add/remove")
    if direction not in ("inbound", "outbound"):
        raise ValueError("direction 必须是 inbound/outbound")
    if protocol not in ("TCP", "UDP", "ICMPv4", "ICMPv6"):
        raise ValueError("protocol 只允许 TCP/UDP/ICMPv4/ICMPv6")
    if action == "list":
        q = ("Get-NetFirewallRule | Select-Object -First 300 "
             "DisplayName, Enabled, Direction, Action")
        if name:
            q += f" | Where-Object DisplayName -like {_psq('*' + name + '*')}"
        r = _ps(q + " | ConvertTo-Json -Compress")
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        return {"count": len(rows), "rules": rows[:200]}
    if action == "add":
        if not name or not port:
            raise ValueError("add 需要 name 和 port")
        d = "Inbound" if direction == "inbound" else "Outbound"
        act = "Allow" if allow else "Block"
        r = _ps(
            f"New-NetFirewallRule -DisplayName {_psq(name)} -Direction {d} "
            f"-Protocol {protocol} -LocalPort {int(port)} -Action {act} | "
            f"Select-Object DisplayName, Enabled | ConvertTo-Json -Compress"
        )
        if r.returncode != 0:
            raise ToolError(f"加规则失败 (要管理员权限): {r.stderr[:200]}")
        return {"added": name, "port": port, "direction": direction}
    # remove
    if not name:
        raise ValueError("remove 需要 name")
    r = _ps(f"Remove-NetFirewallRule -DisplayName {_psq(name)} -ErrorAction Stop; 'OK'")
    if r.returncode != 0:
        raise ToolError(f"删规则失败: {r.stderr[:200]}")
    return {"removed": name}


# ======================================================================
# 注册表组
# ======================================================================
def _reg_path(path: str) -> None:
    """注册表路径安全校验 (P1-3 修复: 之前只拦'根节点+一层', 深层关键路径全放行).

    新策略: 禁止操作这些关键子树 (前缀树边界, 用 normcase+分隔符判断):
    - HKLM:\\SYSTEM\\CurrentControlSet (整个控制集: 服务/驱动/启动项)
    - HKLM:\\SYSTEM\\MountedDevices
    - HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion (Winlogon 等)
    - HKLM:\\SECURITY / HKLM:\\SAM (账户数据库)
    - HKCU:\\...\\Run 是常见持久化位置, 但也是合法自启配置 → 保留可写 (有 confirm)
    """
    if not path or len(path) < 8:
        raise ToolError("注册表路径不合法")
    import os
    norm = os.path.normcase(path.rstrip("\\"))
    critical_subtrees = (
        r"hklm:\system\currentcontrolset",
        r"hklm:\system\mounteddevices",
        r"hklm:\software\microsoft\windows nt\currentversion",
        r"hklm:\security",
        r"hklm:\sam",
    )
    for c in critical_subtrees:
        if norm == c or norm.startswith(c + "\\"):
            raise ToolError(
                f"拒绝操作关键注册表子树: {path} (安全护栏: "
                f"该子树包含系统服务/启动项/账户数据库, 误改可能导致系统无法启动)")
    # 基本合法性: 必须以已知根键开头
    roots = ("hklm:\\", "hkcu:\\", "hkcr:\\", "hku:\\")
    if not norm.startswith(roots):
        raise ToolError("注册表路径必须以 HKLM:\\ / HKCU:\\ / HKCR:\\ / HKU:\\ 开头")


@REGISTRY.register("registry_get", "读注册表值/键 (HKLM:\\... / HKCU:\\... 格式)。",
                   danger=DANGER_LOW)
def registry_get(path: str) -> dict:
    """path: 如 HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"""
    _reg_path(path)
    r = _ps(
        f"if (Test-Path {_psq(path)}) {{ Get-ItemProperty {_psq(path)} | "
        f"Select-Object * -ExcludeProperty PS* | ConvertTo-Json -Compress }} "
        f"else {{ 'NOT_FOUND' }}"
    )
    if "NOT_FOUND" in r.stdout:
        return {"exists": False, "path": path}
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise ToolError(f"读取失败: {r.stderr[:200]}")
    return {"exists": True, "path": path, "values": data}


@REGISTRY.register("registry_set", "写注册表值。危险操作。", danger=DANGER_HIGH,
                   requires_confirm=True, confirm_hint="写错注册表可能让系统/软件异常")
def registry_set(path: str, name: str, value: str, value_type: str = "String") -> dict:
    """path: 注册表键路径
    name: 值名称
    value: 值内容
    value_type: String / DWord / QWord / ExpandString / Binary
    confirm: 必须传 true"""
    _reg_path(path)
    if value_type not in ("String", "DWord", "QWord", "ExpandString", "Binary"):
        raise ValueError("value_type 只允许 String/DWord/QWord/ExpandString/Binary")
    r = _ps(
        f"New-Item -Path {_psq(path)} -Force | Out-Null; "
        f"New-ItemProperty -Path {_psq(path)} -Name {_psq(name)} "
        f"-Value {_psq(value)} "
        f"-PropertyType {value_type} -Force | Out-Null; 'OK'"
    )
    if r.returncode != 0:
        raise ToolError(f"写入失败 (要管理员权限?): {r.stderr[:200]}")
    return {"written": f"{path}\\{name}"}


@REGISTRY.register("registry_delete", "删除注册表值或键。危险操作。", danger=DANGER_HIGH,
                   requires_confirm=True, confirm_hint="删错注册表可能让系统/软件异常")
def registry_delete(path: str, name: str = "") -> dict:
    """path: 注册表键路径
    name: 值名称 (空则删除整个键)
    confirm: 必须传 true"""
    _reg_path(path)
    if name:
        r = _ps(f"Remove-ItemProperty -Path {_psq(path)} -Name {_psq(name)} -ErrorAction Stop; 'OK'")
    else:
        r = _ps(f"Remove-Item -Path {_psq(path)} -Recurse -ErrorAction Stop; 'OK'")
    if r.returncode != 0:
        raise ToolError(f"删除失败: {r.stderr[:200]}")
    return {"deleted": f"{path}\\{name}" if name else path}


# ======================================================================
# 网络组
# ======================================================================
@REGISTRY.register("network_info", "网络信息: 适配器 IP / 网关 / DNS / 连通性。",
                   danger=DANGER_LOW)
def network_info() -> dict:
    r = _ps(
        "Get-NetIPConfiguration | Where-Object IPv4Address | "
        "Select-Object InterfaceAlias, "
        "@{n='ipv4';e={$_.IPv4Address.IPAddress}}, "
        "@{n='gateway';e={$_.IPv4DefaultGateway.NextHop}}, "
        "@{n='dns';e={($_.DNSServer | ForEach-Object Address) -join ','}} | "
        "ConvertTo-Json -Compress"
    )
    rows = json.loads(r.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {"adapters": rows}


def _ssrf_guard(url: str) -> None:
    """SSRF 防护核心: 校验 URL 协议 + 解析出的所有 IP (P1-1 提取为独立函数,
    供每一跳重定向重复调用)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("仅支持 http/https")
    if "@" in parsed.netloc:
        raise ToolError("拒绝 URL 内嵌凭据 (SSRF 防护)")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise ToolError(f"域名解析失败: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            raise ToolError(f"拒绝访问内网/保留地址 {ip} (SSRF 防护)")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """逐跳 SSRF 校验的重定向处理器 (P1-1 修复).

    之前用默认 opener: 30x 自动跟随到新地址但不再过 IP 校验,
    外部 URL 一个 302 即可把请求转进内网. 现在每一跳都重新校验.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ssrf_guard(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener():
    """带 certifi CA + 逐跳 SSRF 校验的 opener."""
    import ssl as _ssl
    try:
        import certifi
        ctx = _ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    handlers = [_SafeRedirectHandler()]
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _http_request_impl(url: str, method: str = "GET", body: str = "",
                       timeout_seconds: int = 30) -> dict:
    """HTTP 请求核心实现 (含 SSRF 防护). 工具间内部调用一律走这里,
    不要调用被 @register 装饰后的公开名 (那是只收 kwargs 的 wrapper)."""
    _ssrf_guard(url)
    req = urllib.request.Request(url, method=method.upper(),
                                 data=body.encode() if body and method.upper() in ("POST", "PUT") else None,
                                 headers={"User-Agent": "OmniWin-MCP/1.0"})
    try:
        with _build_opener().open(req, timeout=timeout_seconds) as resp:
            data = resp.read(20480)
            return {"status": resp.status, "headers": dict(resp.headers),
                    "body": data.decode("utf-8", errors="replace")}
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or \
           "CERTIFICATE_VERIFY_FAILED" in str(e):
            raise ToolError(
                "HTTPS 证书校验失败 (本机 Python 缺少 CA 根证书库)。"
                "修复: pip install certifi (本服务器已自动挂载 certifi, 若仍报错"
                "说明 certifi 未安装到当前环境)。"
                f"原始错误: {e}"
            )
        raise ToolError(f"HTTP 请求失败: {e}")
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"HTTP 请求失败: {e}")


@REGISTRY.register("http_request", "发起 HTTP 请求 (GET/POST, 返回文本/前 20KB)。POST 可外发数据。"
                   "内置私网防护: 拒绝内网/回环/链路本地地址 (防 SSRF, CursorTouch 同款设计)。",
                   danger=DANGER_MEDIUM)  # P1-6: POST 可外传数据
def http_request(url: str, method: str = "GET", body: str = "",
                 timeout_seconds: int = 30) -> dict:
    """url: 完整 URL (http/https)
    method: GET / POST / PUT / DELETE
    body: POST/PUT 的请求体
    timeout_seconds: 超时"""
    return _http_request_impl(url, method, body, timeout_seconds)


@REGISTRY.register("scrape", "抓取网页并转成纯文本 (剥掉 HTML 标签)。含 SSRF 防护。",
                   danger=DANGER_LOW)
def scrape(url: str, max_chars: int = 15000) -> dict:
    """url: 网页 URL
    max_chars: 最多返回字符数"""
    result = _http_request_impl(url)
    import re
    html = result["body"]
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return {
        "title": title.group(1).strip() if title else "",
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "url": url,
    }


@REGISTRY.register("open_browser", "在默认浏览器打开 URL (可拉起任意网页/协议处理器)。", danger=DANGER_MEDIUM)  # P1-6
def open_browser(url: str) -> str:
    """url: 要打开的网址"""
    import webbrowser
    if not url.startswith(("http://", "https://")):
        raise ValueError("url 必须以 http:// 或 https:// 开头")
    webbrowser.open(url)
    return f"已在默认浏览器打开 {url}"


@REGISTRY.register("download_file", "下载文件到指定路径。危险操作 (可执行文件下载需人工把关)。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="下载的文件可能有害, 请确认来源可信")
def download_file(url: str, save_path: str, timeout_seconds: int = 120) -> dict:
    """url: 下载地址
    save_path: 保存绝对路径
    timeout_seconds: 超时
    confirm: 必须传 true"""
    # P1-2 修复: 之前是 _http_request_impl 防护的弱化复制版 (少 reserved/multicast/
    # 凭据检查/解析异常捕获), 且先 open 再下载中断留半截文件。现复用 impl
    # (含逐跳 SSRF 校验) + 先下到临时文件再原子改名。
    import os
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("仅支持 http/https")
    _ssrf_guard(url)

    tmp_path = save_path + ".omniwin-part"
    try:
        with _build_opener().open(
            urllib.request.Request(url, headers={"User-Agent": "OmniWin-MCP/1.0"}),
            timeout=timeout_seconds,
        ) as resp, open(tmp_path, "wb") as f:
            size = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                if size > 500 * 2**20:
                    raise ToolError("超过 500MB 上限, 已中止")
        os.replace(tmp_path, save_path)  # 原子改名, 中断不留半截文件
        return {"saved": save_path, "size_bytes": size}
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        try:
            import os as _os
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)  # 清理半截文件
        except OSError:
            pass
        raise ToolError(f"下载失败: {e}")


# ======================================================================
# 杂项组
# ======================================================================
@REGISTRY.register("clipboard_read", "读取剪贴板文本内容。", danger=DANGER_LOW)
def clipboard_read() -> dict:
    from .. import winapi
    return {"text": winapi.clipboard_get_text()}


@REGISTRY.register("clipboard_write", "写入文本到剪贴板 (覆盖用户剪贴板)。", danger=DANGER_MEDIUM)  # P1-6
def clipboard_write(text: str) -> str:
    """text: 要写入的文本"""
    from .. import winapi
    winapi.clipboard_set_text(text)
    return f"已复制 {len(text)} 个字符到剪贴板"


@REGISTRY.register("notify", "发 Windows 气泡通知 (toast)。", danger=DANGER_LOW)
def notify(title: str, message: str) -> str:
    """title: 标题
    message: 内容"""
    from ..control import _toast
    _toast(title, message)
    return f"通知已发送: {title}"


@REGISTRY.register("get_cursor_pos", "获取当前鼠标光标坐标。", danger=DANGER_LOW)
def get_cursor_pos() -> dict:
    from .. import winapi
    x, y = winapi.get_cursor_pos()
    return {"x": x, "y": y}
