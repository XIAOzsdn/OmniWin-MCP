"""一键打包脚本: 编译一次到处扔.

用法 (在项目根目录):
  python build.py              # 核心版 (零依赖, ~12MB)
  python build.py --full       # 全能版 (内置 OCR + UIA 增强, 体积较大)

产物: dist/OmniWin-MCP.exe
目标机不需要安装任何东西: 无 Python / 无运行时 / 无依赖包.
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    full = "--full" in sys.argv
    if full:
        print("== 全能版: 先确认增强依赖 ==")
        for pkg in ("rapidocr_onnxruntime", "uiautomation", "PIL", "pyclipper", "shapely"):
            r = subprocess.run(
                [sys.executable, "-c", f"import {pkg}"],
                capture_output=True,
            )
            if r.returncode != 0:
                print(f"  缺 {pkg}, 请先: pip install {pkg}")
                return 1
        print("  增强依赖齐备")

    print("== PyInstaller 打包中 (单文件, console) ==")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "OmniWin-MCP.spec",
    ]
    # 数据文件收集已移入 spec (try/except 自动检测), spec 模式下
    # 命令行 --collect-all 会被 PyInstaller 忽略 (P3-12), 故不再传递。

    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("打包失败")
        return 1

    print(
        "\n完成! 产物: dist/OmniWin-MCP.exe\n"
        "部署: 把这个 exe 拷到任何 Windows 10/11 机器, MCP 客户端配置指向它即可:\n"
        '{\n  "mcpServers": {\n    "OmniWin-MCP": {\n'
        '      "command": "C:/path/to/OmniWin-MCP.exe",\n      "args": []\n    }\n  }\n}\n'
        "热键: Ctrl+Alt+Shift+P 随时冻结/恢复 AI 操作"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
