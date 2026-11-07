"""进程 / 服务 / 计划任务 / 事件日志 / PowerShell 组.

系统管理深水区工具源自 danielsimonjr/Windows-MCP 的运维工具设计
(service / scheduled_task / event_log / wmi_query), 全部经 PowerShell 桥实现
(System PowerShell Windows 7+ 必装, 零额外依赖 —— danielsimonjr 同款思路).
"""

from __future__ import annotations

import json
import subprocess

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError
from .window_uia import _ps, _psq

# 白名单枚举 (P0-1 修复: 命令动词/过滤词绝不允许自由字符串拼接)
_SERVICE_ACTIONS = {"start": "Start-Service", "stop": "Stop-Service",
                    "restart": "Restart-Service"}
_EVENT_LOGS = {"System", "Application", "Security", "Setup"}
_EVENT_LEVELS = {"Critical", "Error", "Warning", "Information", "Verbose"}


# ----------------------------------------------------------------------
@REGISTRY.register("process_list",
                   "列出运行中的进程 (名称/PID/内存), 可按名称过滤。",
                   danger=DANGER_LOW)
def process_list(name_filter: str = "", limit: int = 100) -> dict:
    """name_filter: 进程名过滤词 (可空)
    limit: 最多返回条数"""
    # P2-6 修复: 名字过滤下推到 PowerShell 侧, 避免"目标进程不在内存前500"漏检
    q = "Get-Process | Sort-Object WorkingSet64 -Descending"
    if name_filter:
        q += f" | Where-Object ProcessName -like {_psq('*' + name_filter + '*')}"
    q += (" | Select-Object -First 500 ProcessName, Id, "
          "@{n='memMB';e={[math]::Round($_.WorkingSet64/1MB,1)}} | "
          "ConvertTo-Json -Compress")
    r = _ps(q)
    try:
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
    except json.JSONDecodeError:
        rows = []
    return {"count": len(rows[:limit]), "processes": rows[:limit]}


@REGISTRY.register("process_kill",
                   "结束进程 (按 PID 或名称)。危险操作。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="杀进程可能丢失未保存数据")
def process_kill(pid: int = 0, name: str = "") -> dict:
    """pid: 进程 ID (与 name 二选一)
    name: 进程名 (如 notepad)
    confirm: 必须传 true"""
    if pid:
        r = _ps(f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop; 'OK'")
    elif name:
        r = _ps(f"Stop-Process -Name {_psq(name)} -Force -ErrorAction Stop; 'OK'")
    else:
        raise ValueError("pid 和 name 必须给一个")
    if r.returncode != 0:
        raise ToolError(f"杀进程失败: {r.stderr.strip()[:300]}")
    return {"killed": pid or name}


@REGISTRY.register("start_process",
                   "启动进程/程序 (带参数和工作目录)。任意程序启动 = 高危, 需确认。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="启动任意可执行文件可能运行恶意程序")
def start_process(command: str, args: str = "", cwd: str = "",
                  wait: bool = False) -> dict:
    """command: 可执行文件路径或命令
    args: 参数
    cwd: 工作目录
    wait: true 则等进程退出并返回退出码
    confirm: 必须传 true"""
    cmd = f'$p = Start-Process -FilePath {_psq(command)} -PassThru'
    if args:
        cmd += f" -ArgumentList {_psq(args)}"
    if cwd:
        cmd += f" -WorkingDirectory {_psq(cwd)}"
    if wait:
        cmd += "; $p.WaitForExit(); $p.ExitCode"
    else:
        cmd += "; $p.Id"
    r = _ps(cmd, timeout=120 if wait else 30)
    if r.returncode != 0:
        raise ToolError(f"启动失败: {r.stderr.strip()[:300]}")
    out = r.stdout.strip()
    if wait:
        return {"started": True, "exit_code": out}
    return {"started": True, "pid": out}


@REGISTRY.register("powershell",
                   "执行 PowerShell 命令并返回 stdout/stderr (System PowerShell 5.1)。"
                   "可执行任意命令 = 最高危, 强制确认; 可用 --exclude-tools powershell 整体禁用。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="等价于给 AI 一个任意命令执行通道")
def powershell(command: str, timeout_seconds: int = 60) -> dict:
    """command: PowerShell 命令文本
    timeout_seconds: 超时秒数
    confirm: 必须传 true"""
    try:
        r = _ps(command, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        raise ToolError(f"PowerShell 执行超时 ({timeout_seconds}s)")
    return {
        "exit_code": r.returncode,
        "stdout": r.stdout[-8000:],
        "stderr": r.stderr[-2000:],
    }


# ----------------------------------------------------------------------
@REGISTRY.register("service_list", "列出 Windows 服务 (名称/状态/启动类型), 可过滤。",
                   danger=DANGER_LOW)
def service_list(state_filter: str = "", limit: int = 100) -> dict:
    """state_filter: Running / Stopped (可空=全部)
    limit: 最多返回条数"""
    q = "Get-Service | Select-Object Status, Name, DisplayName"
    if state_filter:
        if state_filter not in ("Running", "Stopped"):
            raise ValueError("state_filter 只允许 Running / Stopped")
        q = f"Get-Service | Where-Object Status -eq {_psq(state_filter)} | Select-Object Status, Name, DisplayName"
    r = _ps(q + " | Select-Object -First 500 | ConvertTo-Json -Compress")
    try:
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
    except json.JSONDecodeError:
        rows = []
    return {"count": len(rows[:limit]), "services": rows[:limit]}


@REGISTRY.register("service_control",
                   "控制 Windows 服务: start / stop / restart。危险操作。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="停掉关键服务 (如 DHCP/DNS) 可能断网或蓝屏")
def service_control(name: str, action: str) -> dict:
    """name: 服务名
    action: start / stop / restart
    confirm: 必须传 true"""
    # P0-1 修复: action 是命令动词, 必须白名单 (之前直接拼 f"{action}-Service" 可注入)
    if action not in _SERVICE_ACTIONS:
        raise ValueError("action 必须是 start / stop / restart")
    r = _ps(f"{_SERVICE_ACTIONS[action]} -Name {_psq(name)} -ErrorAction Stop; 'OK'")
    if r.returncode != 0:
        raise ToolError(f"服务操作失败: {r.stderr.strip()[:300]}")
    return {"done": action, "service": name}


@REGISTRY.register("scheduled_tasks", "列出计划任务 (名称/状态/下次运行时间), 可过滤。",
                   danger=DANGER_LOW)
def scheduled_tasks(name_filter: str = "", limit: int = 60) -> dict:
    """name_filter: 任务名过滤词
    limit: 最多返回条数"""
    q = ("Get-ScheduledTask | Select-Object TaskName, State, TaskPath | "
         "Select-Object -First 800")
    if name_filter:
        q += f" | Where-Object TaskName -like {_psq('*' + name_filter + '*')}"
    r = _ps(q + " | ConvertTo-Json -Compress")
    try:
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
    except json.JSONDecodeError:
        rows = []
    return {"count": len(rows[:limit]), "tasks": rows[:limit]}


@REGISTRY.register("event_log",
                   "查询 Windows 事件日志 (Application/System, 可按级别/来源/条数)。",
                   danger=DANGER_LOW)
def event_log(log_name: str = "System", level: str = "",
              newest: int = 20, source: str = "") -> dict:
    """log_name: System / Application / Security / Setup
    level: Critical / Error / Warning / Information / Verbose (可空=全部)
    newest: 最新条数
    source: 来源过滤 (可空)"""
    # P0-1 修复: log_name/level 白名单, source 转义
    if log_name not in _EVENT_LOGS:
        raise ValueError(f"log_name 只允许: {'/'.join(_EVENT_LOGS)}")
    if level and level not in _EVENT_LEVELS:
        raise ValueError(f"level 只允许: {'/'.join(_EVENT_LEVELS)}")
    q = f"Get-WinEvent -LogName {_psq(log_name)} -MaxEvents {min(int(newest), 200)}"
    if level:
        q += f" | Where-Object LevelDisplayName -eq {_psq(level)}"
    if source:
        q += f" | Where-Object ProviderName -like {_psq('*' + source + '*')}"
    # P2-5 修复: Message 可能为 null, 空值安全截断
    q += (" | Select-Object TimeCreated, LevelDisplayName, ProviderName, "
          "Id, @{n='msg';e={if ($_.Message) { $_.Message.Substring(0,"
          "[math]::Min(300,$_.Message.Length)) } else { '' } }} "
          "| ConvertTo-Json -Compress")
    r = _ps(q)
    try:
        rows = json.loads(r.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
    except json.JSONDecodeError:
        rows = []
    return {"count": len(rows), "events": rows}
