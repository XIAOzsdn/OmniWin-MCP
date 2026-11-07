"""OmniWin MCP - 全能视窗 MCP 服务器.

融合三家之长的 Windows 桌面自动化 MCP 服务器:
- 框架路线: CursorTouch/Windows-MCP (Python + stdio + UIA 思路)
- 国内向能力: shuyu-labs/Windows-MCP.Net (OCR / 系统控制 / 中文)
- 安全设计: danielsimonjr/Windows-MCP (confirm 护栏 / 密钥脱敏)

独有特性:
- 全局热键 Ctrl+Alt+Shift+P 一键冻结/恢复所有 AI 操作
- 零第三方依赖核心 (纯标准库 + Windows API ctypes)
- PyInstaller 单文件打包, 编译一次到处扔
"""

__version__ = "1.0.0"
SERVER_NAME = "OmniWin-MCP"
