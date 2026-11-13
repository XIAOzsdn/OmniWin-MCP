# OmniWin-MCP 全能视窗 MCP

> **一款融合了三款不同的WindowsMCP，为"自己说了算"设计的 Windows 桌面自动化 MCP 。**
>
> 框架路线致敬 [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP)（Python + stdio）  
> 国内向能力致敬 [shuyu-labs/Windows-MCP.Net](https://github.com/shuyu-labs/Windows-MCP.Net)（OCR / 系统控制 / 中文优先）  
> 安全设计致敬 [danielsimonjr/Windows-MCP](https://github.com/danielsimonjr/Windows-MCP)（confirm 护栏 / 密钥脱敏）  
> 并延伸出独有特性：**全局热键一键冻结** + **编译一次到处扔**。

---

安装直接把本仓库链接丢给你的 Agent 让其部署即可！！！直接部署也行，但需自己配置到 Agent 的MCP中，有些繁琐
## ✨ 独有特性

| 特性                 | 说明                                                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 🥶 **一键冻结**        | 任何时刻按 `Ctrl+Alt+Shift+P`，全部 77 个 AI 工具瞬间冻结，AI 收到明确的 `SERVER_PAUSED` 错误；**解冻只能由人类再次按热键完成——AI 无法自救（含被劫持场景，resume 不在豁免名单）**。冻结/恢复有系统气泡通知反馈。技术实现：15ms GetAsyncKeyState 轮询单通道 + stdin 重定向防协议流抢占 |
| 📦 **编译一次到处扔**     | 9MB 单文件自包含 exe，目标机**零依赖**——不用装 Python、不用装运行时、不用 pip                                                                                                                                        |
| 🛡️ **confirm 护栏** | 18 个危险操作（删除/杀进程/写注册表/防火墙/关机…）必须显式传 `confirm: true` 才执行                                                                                                                                     |
| 🙈 **密钥自动脱敏**      | 环境变量名字含 KEY/TOKEN/SECRET/PASSWORD 等的值自动打码，防 AI 会话泄密                                                                                                                                        |
| 🧩 **增强件可选**       | OCR（RapidOCR 离线中文引擎）和 UIA（uiautomation 库）按需安装，不装也不崩——优雅降级并给出安装指引                                                                                                                           |
| 🚫 **SSRF 防护**     | HTTP/下载工具拒绝内网/回环/链路本地/URL 内嵌凭据，防止 AI 被诱导攻击内网                                                                                                                                               |
| 🇨🇳 **中文优先**      | 全部 77 个工具描述、错误信息、文档均为中文                                                                                                                                                                    |

## 📦 部署教程

### 前置要求

| 项目       | 要求                                                                   |
| -------- | -------------------------------------------------------------------- |
| 操作系统     | Windows 10 / 11                                                      |
| 方式一（exe） | **什么都不用装**——exe 已自包含全部依赖                                             |
| 方式二（源码）  | Python 3.10+（核心零第三方依赖）                                               |
| MCP 客户端  | 任何支持 stdio MCP 的客户端（Claude Desktop / Cursor / VS Code / WorkBuddy 等） |

---

### 方式一：单文件 exe（推荐，零依赖）

**第 1 步 · 拿 exe**：编译好的成品在 `dist/OmniWin-MCP.exe`（约 9.1MB）。把它拷到目标机器任意位置，例如 `C:\Tools\OmniWin-MCP.exe`。目标机**不需要**装 Python / .NET / 任何运行库。

> 没有现成 exe？在源码目录跑 `python build.py` 自己编译一个（需 Python 3.10+ 和 pyinstaller）。

**第 2 步 · 客户端配置**：在 MCP 客户端配置文件里加一段（路径改成实际路径，**用正斜杠 `/` 或双反斜杠 `\\`**）：

```json
{
  "mcpServers": {
    "OmniWin-MCP": {
      "command": "C:/Tools/OmniWin-MCP.exe",
      "args": []
    }
  }
}
```

各客户端配置文件位置：

| 客户端            | 配置文件                                          |
| -------------- | --------------------------------------------- |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor         | `%USERPROFILE%\.cursor\mcp.json`              |
| VS Code        | 命令面板搜 "MCP: Open User Configuration"          |
| 其他             | MCP/连接器设置里类型选 **stdio**，命令指向 exe              |

**第 3 步 · 重启客户端**：看到 74 个 OmniWin 工具出现即部署成功。

---

### 方式二：源码运行（开发模式）

```bash
# 1. 进入源码根目录
cd omniwin-mcp

# 2. 启动（stderr 看到「热键监听已启动 (74 个工具就绪)」即成功）
python -m omniwin
```

客户端配置：

```json
{
  "mcpServers": {
    "OmniWin-MCP": {
      "command": "python",
      "args": ["-m", "omniwin"],
      "cwd": "C:/path/to/omniwin-mcp"
    }
  }
}
```

> `python` 不在 PATH 时，`command` 写 Python 绝对路径。

---

### 部署后验证（30 秒）

```bash
# 工具清单（应列出 77 个工具）
OmniWin-MCP.exe --list-tools

# 冒烟测试（源码目录内执行，25 项自动断言）
python tests/smoke_test.py
```

客户端里问一句"查一下系统信息"，AI 调用 `system_info` 返回 OS/内存/磁盘 → 全链路通。

---

### 可选增强件（不装也能用，装了更强）

**安装环境（先看这张表，再看下面的单个安装）：**

| 要素 | 说明 |
|---|---|
| 装到哪个 Python | 运行 OmniWin-MCP 的那个解释器（终端里 `python -m omniwin` 能启动的那个） |
| 在哪里敲命令 | CMD / PowerShell / Windows Terminal 任选，或直接丢给 AI 执行 |
| 多 Python 机器 | 永远用 `python -m pip install xxx`，不用裸 `pip install xxx`（防装错环境） |
| 装完之后 | 重启 MCP 服务器（重启客户端）才生效 |
| exe 用户 | **两条路任选**：① 直接让 AI 调用 `install_enhancement` 工具一键安装（exe 内置 pip，目标机无需 Python，装到 exe 旁 enhancements/ 目录，重启生效）② 编译机装好后 `python build.py --full` 打进 exe |

**三个增强件，逐个照抄安装命令即可：**

| 增强件 | 解锁的工具 | Python 版本 | 额外依赖 | 体积 | 安装命令 |
|---|---|---|---|---|---|
| 1️⃣ rapidocr-onnxruntime | 4 个 OCR 工具 | 3.8 – 3.13 | 无（自动带上 onnxruntime） | ~60MB（含离线模型，免联网） | `python -m pip install rapidocr-onnxruntime` |
| 2️⃣ uiautomation | 4 个 UIA 元素工具 | 3.5+（纯 Python） | 无 | <1MB | `python -m pip install uiautomation` |
| 3️⃣ certifi | HTTPS 证书校验修复 | 全版本 | 无 | ~1.5MB | `python -m pip install certifi` |

> exe 用户还可让 AI 调用 `enhancement_status` 查看安装状态、`uninstall_enhancement` 卸载——增强件的装/查/卸全程 AI 一句话搞定。

**安装后验证（三条 import 全部 OK 即成功；exe 用户让 AI 调 `enhancement_status` 看状态即可）：**

```bash

```bash
python -c "import rapidocr_onnxruntime; print('OCR OK')"
python -c "import uiautomation; print('UIA OK')"
python -c "import certifi; print('certifi OK')"
```

最后在 MCP 客户端里让 AI 调用一次 `ocr_screen`，能返回屏幕文字 = 增强件全链路通。

> 诚实标注：版本范围按各库官方支持矩阵标注（本机实测环境为 Python 3.13.12，仅 certifi 实装过，另两个未实测）。
> 未安装增强件时，相关工具会优雅降级并提示安装命令，不影响其余 70+ 工具。

---

### 常见问题

| 现象                      | 解决                                                               |
| ----------------------- | ---------------------------------------------------------------- |
| 客户端里看不到工具               | 检查 `command` 路径斜杠方向；重启客户端；先跑 `--list-tools` 确认 exe/源码本身能启动       |
| 危险操作提示 CONFIRM_REQUIRED | 正常护栏：参数里加 `"confirm": true`（必须是布尔 true，字符串 `"false"` 也会被拦）       |
| 工具全部返回 SERVER_PAUSED    | 人类按了 `Ctrl+Alt+Shift+P` 冻结。再按一次热键解冻（AI 无法自救，见下方人类管控）             |
| 防火墙/服务操作报错              | 需要**管理员权限**运行 MCP 客户端（或以管理员身份重启客户端）                              |
| 想禁用危险工具                 | 启动参数 `--exclude-tools "powershell,registry_set,registry_delete"` |
| HTTPS 请求报证书错误           | `pip install certifi`（服务器会自动挂载）                                  |

---

## 🎮 人类管控

```
平时:    AI 正常操作, control_status 返回 running
按热键:  Ctrl+Alt+Shift+P → 屏幕弹气泡「已冻结」→ 所有工具立即返回 SERVER_PAUSED
再按:    恢复, 气泡「已恢复」
AI 侧:   冻结期只有 control_status / pause / resume 三个管控工具可用, 状态完全透明
```

安全分级（每个工具在描述里自带标注）：

- `low`：只读，随便用（截图/列表/查询）
- `medium`：有副作用但可逆（输入/复制/移窗）
- `high`：不可逆或系统级（删除/杀进程/注册表/防火墙/电源）→ **强制 confirm**

启动时可整体禁用危险工具：

```bash
OmniWin-MCP.exe --exclude-tools "powershell,registry_set,registry_delete"
```

## 🔨 工具总览（74 个，13 大类）

| 类别           | 工具                                                                                                                                                    | 来源                           |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| 管控 (3)       | control_status / pause / resume                                                                                                                       | **独有**                       |
| 输入 (8)       | click / move_mouse / drag / scroll / type_text / press_key / shortcut / wait                                                                          | CursorTouch                  |
| 屏幕-截图 (1)    | screenshot（区域/缩放/base64）                                                                                                                              | CursorTouch+                 |
| 屏幕-OCR (4)   | ocr_screen / ocr_region / find_text_on_screen / ocr_image                                                                                             | **shuyu-labs**               |
| 窗口 (6)       | launch_app / list_windows / focus_window / switch_window / resize_window / window_action                                                              | 三家融合                         |
| UIA (4)      | get_state / find_element / wait_for_element / interact_element                                                                                        | CursorTouch                  |
| 进程/Shell (7) | process_list / process_kill🔒 / start_process / powershell / service_list / service_control🔒 / scheduled_tasks / event_log                           | danielsimonjr+               |
| 文件 (13)      | 读写/追加/复制/移动/删除🔒/目录增删🔒/列表/搜索/信息/哈希/归档(zip穿越防护)                                                                                                       | 三家融合                         |
| 系统 (11)      | system_info / brightness / volume / resolution🔒 / disk_info / storage_health / driver_list / wmi_query / power_action🔒 / env_get(脱敏) / env_list(脱敏) | **shuyu-labs**+danielsimonjr |
| 安全 (4)       | verify_signature / defender_status / firewall_status / firewall_rule🔒                                                                                | **danielsimonjr**            |
| 注册表 (3)      | registry_get / registry_set🔒 / registry_delete🔒（关键节点护栏）                                                                                             | danielsimonjr                |
| 网络/Web (5)   | network_info / http_request(SSRF防护) / scrape / open_browser / download_file🔒                                                                         | CursorTouch+                 |
| 杂项 (5)       | clipboard_read / clipboard_write / notify / get_cursor_pos / …                                                                                        | 三家融合                         |

🔒 = 危险操作，强制 confirm=true

## 🧪 测试

```bash
python tests/smoke_test.py    # 25 项冒烟测试: 协议/安全/冻结/脱敏/截图/SSRF...
```

## 📁 项目结构

```
omniwin-mcp/
├── omniwin/
│   ├── server.py      # MCP stdio JSON-RPC 核心 (自实现, 零依赖)
│   ├── registry.py    # 工具注册 + confirm 装饰器 + JSON Schema 自动生成
│   ├── control.py     # 人类管控: 全局热键 + 冻结闸门 + toast 反馈
│   ├── winapi.py      # Windows API ctypes 层 (鼠标键盘/截图/窗口/剪贴板)
│   └── tools/         # 13 大类 74 个工具
├── tests/smoke_test.py
├── OmniWin-MCP.spec   # PyInstaller 配置
├── build.py           # 一键打包
└── entry.py
```

## ⚠️ 诚实边界

- 本项目融合的是三家的**设计思想与功能覆盖**，代码为全新实现（协议核心、安全层、管控层、全部工具均为原创代码，零拷贝）
- OCR / UIA 增强依赖第三方库，核心功能（输入/截图/文件/进程/注册表/网络/管控）零依赖
- 冻结闸门拦截的是**本服务器发起的工具调用**；已执行完毕的操作不会回滚（与 CursorTouch 的接管机制同样的诚实说明）
- 需要管理员权限的工具（防火墙/服务控制/部分 WMI）在非提权客户端下会明确报错
