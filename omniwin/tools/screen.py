"""屏幕组工具 - 截图 (GDI 零依赖) + OCR (RapidOCR 可选, 国内离线引擎).

OCR 路线紧贴国内: 默认对接 RapidOCR (国产离线 OCR, onnxruntime 推理,
中文识别强, 无需联网/云 API/翻墙). 未安装时给出明确安装指引而非报错崩溃.
OCR 能力源自 shuyu-labs/Windows-MCP.Net 的 5 工具设计 (全屏/区域/找文字/
坐标定位/图片文件), 并扩展了点击联动.
"""

from __future__ import annotations

import base64
import os
import tempfile
import time

from ..registry import REGISTRY, DANGER_LOW, ToolError
from .. import winapi


def _save_png_bytes(png: bytes, name_hint: str = "omniwin") -> str:
    """把 PNG 字节落盘到临时目录, 返回绝对路径."""
    import uuid  # P2-3: uuid 后缀防同秒覆盖
    path = os.path.join(
        tempfile.gettempdir(),
        f"omniwin_{name_hint}_{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}.png",
    )
    with open(path, "wb") as f:
        f.write(png)
    return path


def _get_ocr_engine():
    """惰性加载 RapidOCR; 未安装时抛出带指引的错误."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError:
        try:
            from rapidocr import RapidOCR  # type: ignore  # 新版包名
        except ImportError:
            raise ToolError(
                "OCR 引擎未安装。请运行: pip install rapidocr-onnxruntime "
                "(约 60MB, 离线中文 OCR, 无需联网)。安装后重启本 MCP 服务器。"
            )
    return RapidOCR()


_OCR_CACHE: dict = {}


def _ocr_engine():
    if "engine" not in _OCR_CACHE:
        _OCR_CACHE["engine"] = _get_ocr_engine()
    return _OCR_CACHE["engine"]


def _run_ocr_on_png(png_path: str) -> list[dict]:
    """RapidOCR 识别, 返回 [{text, box, confidence}]."""
    result, _ = _ocr_engine()(png_path)
    items = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            items.append({
                "text": text,
                "center": [int(sum(xs) / 4), int(sum(ys) / 4)],
                "box": [[int(p[0]), int(p[1])] for p in box],
                "confidence": round(float(score), 3),
            })
    return items


# ----------------------------------------------------------------------
@REGISTRY.register("screenshot",
                   "屏幕截图 (GDI 直捕, 零依赖)。返回 PNG 的 base64 (可直接给多模态模型看) "
                   "及落盘路径; 支持区域截图与缩放。",
                   danger=DANGER_LOW)
def screenshot(region: list[int] | None = None,
               scale: float = 1.0,
               return_base64: bool = True) -> dict:
    """region: [left, top, right, bottom] 像素区域, 省略则全屏
    scale: 缩放 (0.1-1.0), 高分屏省 token 用 0.5
    return_base64: false 则不返回 base64 只给路径"""
    import io

    png = winapi.capture_screen_png(tuple(region) if region else None)
    if scale < 0.99:
        try:
            from PIL import Image  # 可选缩放
            img = Image.open(io.BytesIO(png))
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(new_size)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
        except ImportError:
            pass  # 无 Pillow 则返回原图
    path = _save_png_bytes(png, "screen")
    out: dict = {"path": path, "size_bytes": len(png)}
    if return_base64:
        out["base64_png"] = base64.b64encode(png).decode("ascii")
    return out


@REGISTRY.register("ocr_screen",
                   "OCR 识别整个屏幕的文字 (RapidOCR 离线中文引擎)。"
                   "纯文本模型也能靠它'读'屏幕, 不依赖多模态视觉。",
                   danger=DANGER_LOW)
def ocr_screen() -> dict:
    png = winapi.capture_screen_png(None)
    path = _save_png_bytes(png, "ocr_full")
    items = _run_ocr_on_png(path)
    return {
        "count": len(items),
        "texts": [i["text"] for i in items],
        "items": items,
        "screenshot": path,
    }


@REGISTRY.register("ocr_region",
                   "OCR 识别屏幕指定矩形区域的文字, 比 ocr_screen 更快更省。",
                   danger=DANGER_LOW)
def ocr_region(left: int, top: int, right: int, bottom: int) -> dict:
    """left: 区域左边界像素
    top: 区域上边界像素
    right: 区域右边界像素
    bottom: 区域下边界像素"""
    png = winapi.capture_screen_png((left, top, right, bottom))
    path = _save_png_bytes(png, "ocr_region")
    items = _run_ocr_on_png(path)
    for i in items:  # 坐标换回全屏绝对坐标
        i["center"] = [i["center"][0] + left, i["center"][1] + top]
        i["box"] = [[p[0] + left, p[1] + top] for p in i["box"]]
    return {"count": len(items), "items": items, "screenshot": path}


@REGISTRY.register("find_text_on_screen",
                   "在屏幕上查找指定文字并返回其中心坐标 (OCR 定位)。"
                   "找到后可直接把坐标喂给 click 实现纯文本模型点按钮。",
                   danger=DANGER_LOW)
def find_text_on_screen(text: str, click_it: bool = False,
                        best_match: bool = True) -> dict:
    """text: 要找的文字
    click_it: true 则自动点击第一个命中位置
    best_match: true 只返回最像的一条, false 返回全部命中"""
    png = winapi.capture_screen_png(None)
    path = _save_png_bytes(png, "find")
    items = _run_ocr_on_png(path)
    # P2-16 修复: 去掉反向子串匹配 (找"确定"时 OCR 的单字"定"也命中)
    hits = [i for i in items if text in i["text"]]
    if not hits:
        return {"found": False, "text": text, "message": "屏幕上未找到该文字"}
    hits.sort(key=lambda i: i["confidence"], reverse=True)
    result = hits[0] if best_match else None
    out = {
        "found": True,
        "count": len(hits),
        "best": result or hits[0],
        "all": hits if not best_match else [h for h in hits[:10]],
    }
    if click_it:
        target = hits[0]["center"]
        winapi.click(target[0], target[1])
        out["clicked"] = target
    return out


@REGISTRY.register("ocr_image",
                   "OCR 识别本地图片文件中的文字 (支持中文)。", danger=DANGER_LOW)
def ocr_image(image_path: str) -> dict:
    """image_path: 图片文件绝对路径 (png/jpg/bmp)"""
    if not os.path.isfile(image_path):
        raise ToolError(f"文件不存在: {image_path}")
    items = _run_ocr_on_png(image_path)
    return {"count": len(items), "texts": [i["text"] for i in items], "items": items}
