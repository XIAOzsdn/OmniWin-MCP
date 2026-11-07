"""增强件管理工具组 - exe 用户的一键增强通道 (AI 可直接调用).

解决的产品痛点: PyInstaller --onefile 的依赖编译期冻结, 用户 pip install
对 exe 不可见, AI 也无法给 exe 加依赖 (除非反编译重打包).
方案: pip 打包进 exe + install_enhancement 工具用内置 pip 把增强件
--target 安装到 exe 旁的持久 enhancements/ 目录, 重启即生效.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError
from .. import enhancer


@REGISTRY.register(
    "enhancement_status",
    "查看增强件安装状态: 每个增强件已装/未装、作用、装到哪个目录。"
    "增强件 = 给 OmniWin 解锁 OCR / UIA 等高级能力的外挂包。",
    danger=DANGER_LOW,
)
def enhancement_status() -> dict:
    items = []
    for key, meta in enhancer._ENHANCEMENTS.items():
        items.append({
            "package": key,
            "installed": enhancer.is_installed(key),
            "description": meta["desc"],
            "unlocks": meta["unlock"],
        })
    return {
        "enhancement_dir": enhancer._enhancement_dir(),
        "in_sys_path": enhancer._enhancement_dir() in sys.path,
        "note": "installed=true 则对应工具立即可用; false 则先 install_enhancement 安装, 装完重启 MCP 服务器",
        "enhancements": items,
    }


@REGISTRY.register(
    "install_enhancement",
    "一键安装增强件 (OCR / UIA / certifi), 全程无需用户机器有 Python 环境。"
    "使用内置 pip 把增强件下载安装到持久目录, 装完提示重启。危险级: 会联网下载。",
    danger=DANGER_MEDIUM, requires_confirm=True,
    confirm_hint="会联网下载安装第三方包",
)
def install_enhancement(package: str, confirm: bool = False) -> dict:
    """package: 增强件名, 只允许: rapidocr-onnxruntime / uiautomation / certifi
    confirm: 必须传 true (会联网下载)"""
    if package not in enhancer._ENHANCEMENTS:
        raise ToolError(
            f"未知增强件: {package}。只允许: "
            f"{', '.join(enhancer._ENHANCEMENTS)} (白名单, 防止被诱导安装任意包)")
    if enhancer.is_installed(package):
        return {"installed": True, "already_installed": True,
                "package": package,
                "hint": "已安装, 直接可用 (若刚装完请先重启 MCP 服务器)"}

    target = enhancer._enhancement_dir()
    os.makedirs(target, exist_ok=True)

    # 内置 pip (PyInstaller hiddenimports 打包进来; 源码运行则用当前解释器的 pip)
    try:
        from pip._internal.cli.main import main as pip_main
    except ImportError:
        raise ToolError(
            "内置 pip 不可用 (该部署缺少 pip 模块)。"
            "源码用户请直接 python -m pip install; exe 用户请使用 --full 打包版。")

    # 冷门依赖显式带上 (审查实测: rapidocr 的 pyclipper/shapely 若只写包名,
    # 部分 pip 解析场景会漏装, 补齐后 config.yaml/模型才能完整工作)
    extra = {
        "rapidocr-onnxruntime": ["pyclipper", "shapely"],
    }
    pkgs = [package] + extra.get(package, [])
    args = ["install", "--target", target,
            "--no-warn-script-location", "--upgrade"] + pkgs
    print(f"[enhancer] pip {' '.join(args)}", file=sys.stderr, flush=True)

    # 执行方式按部署形态分流:
    # - exe (frozen): 必须**进程内**调 pip —— sys.executable 是 exe 自己,
    #   用它起 `-c` 子进程会被 PyInstaller bootloader 无视, pip 根本不执行
    #   (外部审查实测证伪的根因)。pip 已通过 spec hiddenimports 冻结进 exe。
    # - 源码: 子进程执行, 避免 pip 污染当前进程 sys.modules。
    frozen = getattr(sys, "frozen", False)
    if frozen:
        import io
        import contextlib
        from pip._internal.cli.main import main as pip_main
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = pip_main(args)
        except SystemExit as e:  # pip 内部可能 sys.exit
            rc = e.code if isinstance(e.code, int) else (0 if not e.code else 1)
        pip_out = buf.getvalue()
        ok = rc == 0
        result = {
            "package": package,
            "installed": ok,
            "target_dir": target,
            "next_step": "重启 MCP 服务器 (重启客户端) 后增强件生效" if ok else "",
            "pip_tail": pip_out[-1500:],
        }
        if not ok:
            raise ToolError(
                f"增强件 {package} 安装失败 (exit={rc})。"
                f"pip 输出尾部: {pip_out[-500:]}")
        # 装后自检 (审查实测: 数据文件/依赖缺失会导致运行时报错)
        if package == "rapidocr-onnxruntime":
            missing = []
            pkg_dir = os.path.join(target, "rapidocr_onnxruntime")
            for rel in ("config.yaml", "ch_ppocr_v3_det", "ch_ppocr_v3_rec", "ch_ppocr_v2_cls"):
                if not os.path.exists(os.path.join(pkg_dir, rel)):
                    missing.append(rel)
            if missing:
                raise ToolError(
                    f"rapidocr 安装后自检失败: 数据文件缺失 {missing}。"
                    f"请把此报错反馈给开发者。")
            result["self_check"] = "数据文件完整 (config.yaml + 3 个模型目录)"
        return result

    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; from pip._internal.cli.main import main; "
         f"sys.exit(main({args!r}))"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=600,
        creationflags=0x08000000,
    )
    ok = r.returncode == 0
    result = {
        "package": package,
        "installed": ok,
        "target_dir": target,
        "next_step": "重启 MCP 服务器 (重启客户端) 后增强件生效" if ok else "",
        "pip_tail": (r.stdout + r.stderr)[-1500:],
    }
    if not ok:
        raise ToolError(
            f"增强件 {package} 安装失败 (exit={r.returncode})。"
            f"pip 输出尾部: {(r.stdout + r.stderr)[-500:]}")
    if package == "rapidocr-onnxruntime":
        pkg_dir = os.path.join(target, "rapidocr_onnxruntime")
        missing = [rel for rel in ("config.yaml", "ch_ppocr_v3_det", "ch_ppocr_v3_rec", "ch_ppocr_v2_cls")
                   if not os.path.exists(os.path.join(pkg_dir, rel))]
        if missing:
            raise ToolError(f"rapidocr 安装后自检失败: 数据文件缺失 {missing}")
        result["self_check"] = "数据文件完整 (config.yaml + 3 个模型目录)"
    return result


@REGISTRY.register(
    "uninstall_enhancement",
    "卸载增强件 (删除 enhancements 目录下对应包)。危险操作。",
    danger=DANGER_HIGH, requires_confirm=True,
    confirm_hint="删除后对应工具回到优雅降级状态",
)
def uninstall_enhancement(package: str, confirm: bool = False) -> dict:
    """package: 增强件名
    confirm: 必须传 true"""
    import shutil
    # confirm 检查由装饰器统一处理 (wrapper pop 后函数体收不到)
    # confirm 检查由装饰器统一处理
    if package not in enhancer._ENHANCEMENTS:
        raise ValueError(f"未知增强件: {package}")
    target = enhancer._enhancement_dir()
    removed = []
    if os.path.isdir(target):
        base = package.replace("-", "_").lower()
        for name in os.listdir(target):
            low = name.lower()
            if low == base or low.startswith(base + "-"):  # dist-info 目录
                shutil.rmtree(os.path.join(target, name), ignore_errors=True)
                removed.append(name)
    if not removed:
        return {"removed": [], "note": "目录里没有该增强件的文件 (可能本来就未安装)"}
    return {"removed": removed, "next_step": "重启 MCP 服务器后生效"}
