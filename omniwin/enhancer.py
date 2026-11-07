"""增强件自举模块 - exe 模式的插件安装能力 (解决"编译期冻结依赖"死穴).

背景: PyInstaller --onefile 的依赖在编译期冻结进 exe, 运行时解压到临时目录,
用户 pip install 装进系统 Python 对 exe 不可见, AI 也无法给 exe 加依赖.

方案: 打包时把 pip 一起冻结进 exe (spec 的 hiddenimports), 运行时:
1. 启动时把 <exe目录>/enhancements/ 注入 sys.path (持久目录, 不随运行重建)
2. 工具 install_enhancement: 进程内调用内置 pip, --target 安装到该目录
3. 重启 MCP 服务器后增强件生效

源码运行方式同样可用 (装进当前解释器的默认 site-packages 或指定 target).
"""

from __future__ import annotations

import os
import sys


def _enhancement_dir() -> str:
    """增强件持久目录: exe 旁边 / 源码包旁边, 重启后仍在、重新打包不丢."""
    if getattr(sys, "frozen", False):  # PyInstaller exe
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "enhancements")


def bootstrap_enhancement_path() -> str:
    """把增强件目录注入 sys.path (存在才注入). 返回注入的目录或空串."""
    d = _enhancement_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
        return d
    return d if os.path.isdir(d) else ""


_ENHANCEMENTS = {
    "rapidocr-onnxruntime": {
        "desc": "离线中文 OCR (~60MB, 含模型, 免联网)",
        "unlock": "ocr_screen / ocr_region / find_text_on_screen / ocr_image",
        "verify_import": "rapidocr_onnxruntime",
    },
    "uiautomation": {
        "desc": "UIA 元素树 (国产库, 纯 Python)",
        "unlock": "get_state / find_element / wait_for_element / interact_element",
        "verify_import": "uiautomation",
    },
    "certifi": {
        "desc": "HTTPS CA 证书库 (缺系统根证书的机器需要)",
        "unlock": "http_request / scrape / download_file 的 HTTPS 校验",
        "verify_import": "certifi",
    },
}


def is_installed(package_key: str) -> bool:
    import importlib
    mod = _ENHANCEMENTS[package_key]["verify_import"]
    try:
        importlib.import_module(mod)
        return True
    except ImportError:
        return False
