# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置: OmniWin-MCP 单文件自包含 exe.

编译一次到处扔:
  目标机零依赖 (不用装 Python / pip / 任何运行时), 双击即用.
核心仅用 Python 标准库 + Windows API, 打包体积极小 (~12MB).
"""

# --full 模式: rapidocr 已安装时自动收集其数据文件 (config.yaml + 3 个模型目录)。
# 修复: build.py 曾用命令行 --collect-all, 但 spec 模式下被 PyInstaller 忽略
# (第一轮报告 P3-12), 导致 exe 内 config.yaml does not exist。
datas = []
binaries = []
hiddenimports = ['pip', 'pip._internal.cli.main']
try:
    import rapidocr_onnxruntime  # noqa: F401
    from PyInstaller.utils.hooks import collect_all
    d, b, h = collect_all('rapidocr_onnxruntime')
    datas += d
    binaries += b
    hiddenimports += h
    print(f'[spec] rapidocr 数据文件已收集: {len(d)} 项')
except ImportError:
    print('[spec] 核心版: 未安装 rapidocr, 跳过收集')

a = Analysis(
    ["entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 只砍确定安全的大模块 (email/html 是 urllib.request 的依赖, 不能砍)
        "tkinter", "unittest", "pydoc", "doctest",
        "http.server", "pdb", "profile", "pstats",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OmniWin-MCP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,      # 单文件模式: 解压到临时目录
    console=True,             # stdio MCP 服务器必须保留控制台句柄
    disable_windowed_traceback=False,
    argv_emulation=False,
)
