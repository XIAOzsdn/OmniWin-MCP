"""系统组工具 - 系统信息 / 亮度 / 音量 / 分辨率 (shuyu-labs 紧贴国内的三件套)
+ 磁盘 / 驱动 / WMI / 电源 (danielsimonjr 运维深水区) + 环境变量 (脱敏).
音量/亮度/分辨率经 PowerShell 桥 (WMI / IAudioEndpointVolume), 零第三方依赖.
"""

from __future__ import annotations

import json
import os
import platform
import shutil

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError, redact_sensitive
from .window_uia import _ps, _psq


@REGISTRY.register("system_info",
                   "系统信息总览: OS/CPU/内存/磁盘/网络/Python。排障第一步。",
                   danger=DANGER_LOW)
def system_info() -> dict:
    uname = platform.uname()
    total, avail, _pct = shutil.disk_usage(os.path.abspath(os.sep))
    return {
        "os": f"{uname.system} {uname.release} (build {uname.version})",
        "machine": uname.machine,
        "processor": uname.processor or platform.processor(),
        "hostname": uname.node,
        "python": platform.python_version(),
        "memory": {
            # P2-1 修复: WMI 的 TotalVisibleMemorySize/FreePhysicalMemory 单位是 KB
            # (微软 WMI 文档), 之前误当字节除以 1_000_000, 32GB 机器报 33.6GB
            "total_gb": round(_ps_mem("TotalVisibleMemorySize") / 1024 / 1024, 1),
            "free_gb": round(_ps_mem("FreePhysicalMemory") / 1024 / 1024, 1),
        },
        "disk_c": {"total_gb": round(total / 2**30, 1),
                   "free_gb": round(avail / 2**30, 1)},
    }


def _ps_mem(field: str) -> float:
    r = _ps(f"(Get-CimInstance Win32_OperatingSystem).{field}")
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


@REGISTRY.register("brightness", "调节屏幕亮度 (0-100), 支持 增/减/直接设置。",
                   danger=DANGER_MEDIUM)
def brightness(action: str = "get", value: int = 20) -> dict:
    """action: get / set / increase / decrease
    value: set/increase/decrease 时的目标或步长 (0-100)"""
    r = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
    if r.returncode != 0:
        raise ToolError("无法读取亮度 (台式机外接显示器通常不支持软件调亮度)")
    try:
        current = int(float(r.stdout.strip()))
    except ValueError:
        raise ToolError(f"亮度解析失败: {r.stdout[:100]}")

    if action == "get":
        return {"brightness": current}
    if action == "set":
        target = max(0, min(100, int(value)))
    elif action == "increase":
        target = min(100, current + int(value))
    elif action == "decrease":
        target = max(0, current - int(value))
    else:
        raise ValueError("action 必须是 get/set/increase/decrease")
    _ps(
        f"(Get-CimInstance -Namespace root/WMI -ClassName "
        f"WmiMonitorBrightnessMethods).WmiSetBrightness(1,{target})"
    )
    return {"brightness_was": current, "brightness_now": target}


@REGISTRY.register("volume", "调节系统音量 (0-100), 支持 静音/取消静音/增/减/设置。",
                   danger=DANGER_MEDIUM)
def volume(action: str = "get", value: int = 20) -> dict:
    """action: get / set / increase / decrease / mute / unmute
    value: set/increase/decrease 的目标或步长 (0-100)"""
    r = _ps(r"""
$code = @'
using System;
using System.Runtime.InteropServices;
public class MasterVol {
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr n); int UnregisterControlChangeNotify(IntPtr n);
    int GetChannelCount(out uint c);
    int SetMasterVolumeLevel(float l, Guid g); int SetMasterVolumeLevelScalar(float s, Guid g);
    int GetMasterVolumeLevel(out float l); int GetMasterVolumeLevelScalar(out float s);
    int SetChannelVolumeLevel(uint c, float l, Guid g); int SetChannelVolumeLevelScalar(uint c, float s, Guid g);
    int GetChannelVolumeLevel(uint c, out float l); int GetChannelVolumeLevelScalar(uint c, out float s);
    int SetMute(bool m, Guid g); int GetMute(out bool m);
  }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice { int Activate(ref Guid iid, uint ctx, out IAudioEndpointVolume vol); }
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator { int GetDefaultAudioEndpoint(int f, int m, out IMMDevice dev); }
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}
  public class VolumeCtl {
    public static IAudioEndpointVolume Get() {
      var en = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
      IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
      IAudioEndpointVolume vol; Guid iid = typeof(IAudioEndpointVolume).GUID;
      dev.Activate(ref iid, 1, out vol); return vol;
    }
  }
'@
Add-Type -TypeDefinition $code
$v = [MasterVol+VolumeCtl]::Get()
$s = 0.0; [void]$v.GetMasterVolumeLevelScalar([ref]$s); [math]::Round($s*100)
""")
    if r.returncode != 0:
        raise ToolError(f"音量控制失败: {r.stderr.strip()[:200]}")
    try:
        current = int(float(r.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        raise ToolError(f"音量解析失败: {r.stdout[:100]}")

    if action == "get":
        return {"volume": current}
    script = _VOL_SETTER
    if action == "set":
        target = max(0, min(100, int(value)))
        script = script.replace("__LEVEL__", f"{target / 100:.2f}").replace(
            "__MUTE__", "")
    elif action == "increase":
        target = min(100, current + int(value))
        script = script.replace("__LEVEL__", f"{target / 100:.2f}").replace(
            "__MUTE__", "")
    elif action == "decrease":
        target = max(0, current - int(value))
        script = script.replace("__LEVEL__", f"{target / 100:.2f}").replace(
            "__MUTE__", "")
    elif action == "mute":
        script = script.replace("__LEVEL__", f"{current / 100:.2f}").replace(
            "__MUTE__", "[void]$v.SetMute($true, [guid]::Empty);")
    elif action == "unmute":
        script = script.replace("__LEVEL__", f"{current / 100:.2f}").replace(
            "__MUTE__", "[void]$v.SetMute($false, [guid]::Empty);")
    else:
        raise ValueError("action 必须是 get/set/increase/decrease/mute/unmute")
    r2 = _ps(script)
    if r2.returncode != 0:
        raise ToolError(f"音量调节失败: {r2.stderr.strip()[:200]}")
    return {"volume_was": current,
            "action": action,
            "value": value if action in ("set", "increase", "decrease") else None}


_VOL_SETTER = r"""
$code = @'
using System;
using System.Runtime.InteropServices;
public class MasterVol {
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr n); int UnregisterControlChangeNotify(IntPtr n);
    int GetChannelCount(out uint c);
    int SetMasterVolumeLevel(float l, Guid g); int SetMasterVolumeLevelScalar(float s, Guid g);
    int GetMasterVolumeLevel(out float l); int GetMasterVolumeLevelScalar(out float s);
    int SetChannelVolumeLevel(uint c, float l, Guid g); int SetChannelVolumeLevelScalar(uint c, float s, Guid g);
    int GetChannelVolumeLevel(uint c, out float l); int GetChannelVolumeLevelScalar(uint c, out float s);
    int SetMute(bool m, Guid g); int GetMute(out bool m);
  }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice { int Activate(ref Guid iid, uint ctx, out IAudioEndpointVolume vol); }
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator { int GetDefaultAudioEndpoint(int f, int m, out IMMDevice dev); }
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}
  public class VolumeCtl2 {
    public static IAudioEndpointVolume Get() {
      var en = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
      IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
      IAudioEndpointVolume vol; Guid iid = typeof(IAudioEndpointVolume).GUID;
      dev.Activate(ref iid, 1, out vol); return vol;
    }
  }
'@
Add-Type -TypeDefinition $code
$v = [MasterVol+VolumeCtl2]::Get()
[void]$v.SetMasterVolumeLevelScalar(__LEVEL__, [guid]::Empty)
__MUTE__
'OK'
"""


@REGISTRY.register("resolution", "设置屏幕分辨率 (高/中/低 三档, shuyu-labs 同款设计)。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="切换分辨率会闪屏, 游戏全屏可能崩溃")
def resolution(level: str = "high") -> dict:
    """level: high (1920x1080) / medium (1366x768) / low (1280x720)
    confirm: 必须传 true"""
    table = {
        "high": (1920, 1080), "medium": (1366, 768), "low": (1280, 720),
    }
    if level not in table:
        raise ValueError("level 必须是 high/medium/low")
    w, h = table[level]
    r = _ps(
        "Get-CimInstance -ClassName Win32_VideoController | "
        "Select-Object CurrentHorizontalResolution, CurrentVerticalResolution | "
        "ConvertTo-Json -Compress"
    )
    before = r.stdout.strip() or "{}"
    # ChangeDisplaySettings 修改分辨率 (模板替换, 避免 f-string 转义地狱)
    script = _RES_SETTER.replace("__W__", str(w)).replace("__H__", str(h))
    _ps(script)
    return {"requested": level, "resolution": f"{w}x{h}",
            "before_raw": before[:200]}


_RES_SETTER = r"""
$sig = @'
using System;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
public struct DEVMODE {
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
  public short dmSpecVersion; public short dmDriverVersion; public short dmSize;
  public short dmDriverExtra; public int dmFields;
  public int dmPositionX; public int dmPositionY;
  public int dmDisplayOrientation; public int dmDisplayFixedOutput;
  public short dmColor; public short dmDuplex; public short dmYResolution;
  public short dmTTOption; public short dmCollate;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
  public short dmLogPixels; public int dmBitsPerPel;
  public int dmPelsWidth; public int dmPelsHeight;
  public int dmDisplayFlags; public int dmDisplayFrequency;
  public int dmICMMethod; public int dmICMIntent; public int dmMediaType;
  public int dmDitherType; public int dmReserved1; public int dmReserved2;
  public int dmPanningWidth; public int dmPanningHeight;
}
public class NativeRes {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int ChangeDisplaySettingsW(ref DEVMode d, int f);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int EnumDisplaySettingsW(string dev, int mode, ref DEVMode d);
}
'@
Add-Type -TypeDefinition $sig
$dm = New-Object DEVMODE
$dm.dmSize = [int16][System.Runtime.InteropServices.Marshal]::SizeOf($dm)
[void][NativeRes]::EnumDisplaySettingsW($null, -1, [ref]$dm)
$dm.dmPelsWidth = __W__
$dm.dmPelsHeight = __H__
$dm.dmBitsPerPel = 32
$dm.dmFields = 0x80000 -bor 0x100000 -bor 0x40000
[void][NativeRes]::ChangeDisplaySettingsW([ref]$dm, 0)
'OK'
"""


# ----------------------------------------------------------------------
@REGISTRY.register("disk_info", "列出所有磁盘分区 (总容量/剩余/文件系统/卷标)。",
                   danger=DANGER_LOW)
def disk_info() -> dict:
    r = _ps(
        "Get-CimInstance Win32_LogicalDisk | "
        "Select-Object DeviceID, VolumeName, FileSystem, "
        "@{n='sizeGB';e={[math]::Round($_.Size/1GB,1)}}, "
        "@{n='freeGB';e={[math]::Round($_.FreeSpace/1GB,1)}} | "
        "ConvertTo-Json -Compress"
    )
    rows = json.loads(r.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {"disks": rows}


@REGISTRY.register("storage_health", "磁盘健康度 (SMART 状态 / 温度 / 磨损, 需管理员权限最佳)。",
                   danger=DANGER_LOW)
def storage_health() -> dict:
    r = _ps(
        "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, "
        "@{n='sizeGB';e={[math]::Round($_.Size/1GB,1)}}, OperationalStatus | "
        "ConvertTo-Json -Compress"
    )
    rows = json.loads(r.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {"physical_disks": rows}


@REGISTRY.register("driver_list", "列出驱动程序 (名称/版本/日期), 可按名称过滤。",
                   danger=DANGER_LOW)
def driver_list(name_filter: str = "", limit: int = 100) -> dict:
    """name_filter: 驱动名过滤词
    limit: 最多返回条数"""
    r = _ps(
        "Get-CimInstance Win32_PnPSignedDriver | "
        "Where-Object DeviceName | "
        "Select-Object DeviceName, DriverVersion, DriverDate, Manufacturer | "
        "Select-Object -First 1000 | ConvertTo-Json -Compress"
    )
    try:
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
    except json.JSONDecodeError:
        rows = []
    if name_filter:
        rows = [d for d in rows
                if name_filter.lower() in (d.get("DeviceName") or "").lower()]
    return {"count": len(rows[:limit]), "drivers": rows[:limit]}


@REGISTRY.register("wmi_query", "执行 WMI/CIM 查询 (如 Win32_Process / Win32_BIOS)。danielsimonjr 同款深水区工具。",
                   danger=DANGER_LOW)
def wmi_query(wql: str = "SELECT * FROM Win32_BIOS", limit: int = 20) -> dict:
    """wql: WQL 查询语句
    limit: 最多返回条数"""
    # P0-1 修复: WQL 拼进 PS 双引号字符串, 之前只挡 ; 和 | 没挡 ` 和 $ 和 "
    if ";" in wql.lower() or "|" in wql:
        raise ToolError("wmi_query 只接受单条 WQL 查询, 不允许管道或分号 (防注入)")
    for ch in ('"', '`', "$"):
        if ch in wql:
            raise ToolError(f"wql 不允许包含 {ch!r} 字符 (防注入)")
    r = _ps(
        f"Get-CimInstance -Query {_psq(wql)} | Select-Object -First {min(int(limit), 200)} | "
        f"ConvertTo-Json -Depth 3 -Compress"
    )
    if r.returncode != 0:
        raise ToolError(f"WQL 查询失败: {r.stderr.strip()[:300]}")
    rows = json.loads(r.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    return {"count": len(rows), "results": rows}


@REGISTRY.register("power_action", "电源操作: shutdown / restart / logoff / lock / sleep。高危!",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="重启/关机会中断所有未保存工作")
def power_action(action: str, force: bool = True) -> dict:
    """action: shutdown / restart / logoff / lock / sleep
    force: 强制 (不询问应用)
    confirm: 必须传 true"""
    import ctypes
    if action == "lock":
        ctypes.windll.user32.LockWorkStation()
        return {"done": "lock"}
    cmds = {
        "shutdown": "Stop-Computer" + (" -Force" if force else ""),
        "restart": "Restart-Computer" + (" -Force" if force else ""),
        "logoff": "shutdown /l",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    }
    if action not in cmds:
        raise ValueError("action 必须是 shutdown/restart/logoff/lock/sleep")
    _ps(cmds[action], timeout=10)
    return {"done": action, "note": "命令已发出"}


@REGISTRY.register("env_get",
                   "读取环境变量 (名字含 KEY/TOKEN/SECRET/PASSWORD 等的值自动打码)。"
                   "敏感值一律脱敏, 无查看原文的开关 —— 护栏不能由被监管方自己关闭 (P1-8 修复)。",
                   danger=DANGER_LOW)
def env_get(name: str) -> dict:
    """name: 环境变量名"""
    val = os.environ.get(name)
    if val is None:
        return {"name": name, "exists": False}
    val = redact_sensitive({name: val})[name]
    return {"name": name, "exists": True, "value": val}


@REGISTRY.register("env_list", "列出所有环境变量 (敏感值已脱敏, 无豁免开关)。", danger=DANGER_LOW)
def env_list() -> dict:
    env = redact_sensitive(dict(os.environ))
    return {"count": len(env), "env": env}
