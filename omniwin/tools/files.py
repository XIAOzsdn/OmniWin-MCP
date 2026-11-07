"""文件系统组 - 读/写/复制/移动/删除/搜索/哈希/归档 (融合三家文件工具之全)."""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import zipfile

from ..registry import REGISTRY, DANGER_LOW, DANGER_MEDIUM, DANGER_HIGH, ToolError


@REGISTRY.register("file_read", "读取文本文件内容 (自动截断, 默认尾部 30000 字符)。",
                   danger=DANGER_LOW)
def file_read(path: str, max_chars: int = 30000, encoding: str = "utf-8") -> dict:
    """path: 文件绝对路径
    max_chars: 最多返回字符数 (1 - 200000)
    encoding: 编码 (utf-8 / gbk)"""
    if not os.path.isfile(path):
        raise ToolError(f"文件不存在: {path}")
    max_chars = max(1, min(int(max_chars), 200000))
    size = os.path.getsize(path)
    if size > 64 * 2**20:
        raise ToolError(f"文件过大 ({size // 2**20}MB > 64MB 上限), 请用 powershell 或分段工具读取")
    try:
        # P2-4 修复: 只读尾部所需字节, 不再全量 f.read() 入内存
        with open(path, "rb") as f:
            need = max_chars * 4  # UTF-8 中文最坏 4 字节/字符
            if size > need:
                f.seek(-need, 2)
            tail = f.read()
        content = tail.decode(encoding, errors="replace")
    except OSError as e:
        raise ToolError(f"读取失败: {e}")
    return {
        "path": path, "size_bytes": size,
        "total_chars_hint": len(content),
        "truncated": len(content) > max_chars or size > len(tail),
        "content": content[-max_chars:],
    }


@REGISTRY.register("file_write", "写文本文件 (overwrite=true 覆盖, 否则新建)。危险操作。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="覆盖已有文件将丢失原内容")
def file_write(path: str, content: str, overwrite: bool = True) -> dict:
    """path: 目标文件绝对路径
    content: 写入内容
    overwrite: 是否覆盖已有文件
    confirm: 必须传 true"""
    if os.path.exists(path) and not overwrite:
        raise ToolError(f"文件已存在且 overwrite=false: {path}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"written": path, "chars": len(content)}


@REGISTRY.register("file_append", "向文件末尾追加内容 (不动原内容)。", danger=DANGER_MEDIUM)
def file_append(path: str, content: str) -> dict:
    """path: 目标文件绝对路径
    content: 追加内容"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
    return {"appended": path, "chars": len(content)}


@REGISTRY.register("file_copy", "复制文件或整个目录。", danger=DANGER_MEDIUM)
def file_copy(src: str, dst: str) -> dict:
    """src: 源路径 (文件或目录)
    dst: 目标路径"""
    if not os.path.exists(src):
        raise ToolError(f"源不存在: {src}")
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)
    return {"copied": src, "to": dst}


@REGISTRY.register("file_move", "移动/重命名文件或目录。", danger=DANGER_MEDIUM)
def file_move(src: str, dst: str) -> dict:
    """src: 源路径
    dst: 目标路径"""
    if not os.path.exists(src):
        raise ToolError(f"源不存在: {src}")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.move(src, dst)
    return {"moved": src, "to": dst}


@REGISTRY.register("file_delete", "删除文件 (移入回收站语义不可用, 直接删除)。危险操作。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="删除后无法从回收站找回")
def file_delete(path: str) -> dict:
    """path: 要删除的文件绝对路径
    confirm: 必须传 true"""
    if not os.path.isfile(path):
        raise ToolError(f"文件不存在: {path}")
    os.remove(path)
    return {"deleted": path}


@REGISTRY.register("directory_create", "创建目录 (含多级父目录)。", danger=DANGER_LOW)
def directory_create(path: str) -> dict:
    """path: 目录绝对路径"""
    os.makedirs(path, exist_ok=True)
    return {"created": path}


@REGISTRY.register("directory_delete",
                   "删除整个目录及其所有内容。高危操作 (不可逆)。",
                   danger=DANGER_HIGH, requires_confirm=True,
                   confirm_hint="整棵目录树连同内容一并删除, 不可恢复")
def directory_delete(path: str) -> dict:
    """path: 目录绝对路径
    confirm: 必须传 true"""
    if not os.path.isdir(path):
        raise ToolError(f"目录不存在: {path}")
    # P1-4 修复: realpath 解析 junction/符号链接 + 盘根拒绝 + 路径边界判断
    import ntpath
    real = os.path.realpath(path)
    norm = ntpath.normcase(ntpath.normpath(real))
    # 1) 盘根与关键根不设防的补漏: 任何盘符根目录直接拒绝
    if ntpath.splitdrive(norm)[1] == "\\":
        raise ToolError(f"拒绝删除盘根目录: {path} (安全护栏)")
    critical = [
        os.environ.get("SystemRoot", r"C:\Windows").lower(),
        r"c:\program files", r"c:\program files (x86)",
        r"c:\programdata",  # P1-4: 之前漏了 ProgramData
        r"c:\users",
        os.path.expanduser("~").lower(),
    ]
    for c in critical:
        c = ntpath.normcase(ntpath.normpath(c))
        # 用分隔符边界判断, 修复 C:\Users\xxx2 被 C:\Users 误拦的前缀匹配问题
        if norm == c or norm.startswith(c + "\\"):
            raise ToolError(f"拒绝删除系统关键目录: {path} (安全护栏)")
    shutil.rmtree(real)
    return {"deleted": path, "resolved": real}


@REGISTRY.register("list_directory", "列出目录内容 (名称/类型/大小/修改时间)。",
                   danger=DANGER_LOW)
def list_directory(path: str, limit: int = 200) -> dict:
    """path: 目录绝对路径
    limit: 最多返回条数"""
    if not os.path.isdir(path):
        raise ToolError(f"目录不存在: {path}")
    items = []
    try:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
                items.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": st.st_size if os.path.isfile(full) else None,
                    "modified": st.st_mtime,
                })
            except OSError:
                items.append({"name": name, "type": "no-access"})
    except OSError as e:
        raise ToolError(f"列目录失败: {e}")
    return {"count": len(items[:limit]), "items": items[:limit]}


@REGISTRY.register("file_search",
                   "按通配符搜索文件 (如 *.py / 报告*.docx), 递归子目录。",
                   danger=DANGER_LOW)
def file_search(directory: str, pattern: str = "*", limit: int = 100) -> dict:
    """directory: 起始目录
    pattern: 通配符模式
    limit: 最多返回条数"""
    if not os.path.isdir(directory):
        raise ToolError(f"目录不存在: {directory}")
    hits = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if glob.fnmatch.fnmatch(f.lower(), pattern.lower()):
                hits.append(os.path.join(root, f))
                if len(hits) >= limit:
                    return {"count": len(hits), "files": hits,
                            "truncated": True}
    return {"count": len(hits), "files": hits}


@REGISTRY.register("file_info", "查看文件/目录详细信息 (大小/时间/属性)。",
                   danger=DANGER_LOW)
def file_info(path: str) -> dict:
    """path: 文件或目录绝对路径"""
    if not os.path.exists(path):
        raise ToolError(f"路径不存在: {path}")
    st = os.stat(path)
    return {
        "path": path,
        "type": "dir" if os.path.isdir(path) else "file",
        "size_bytes": st.st_size,
        "created": st.st_ctime,
        "modified": st.st_mtime,
        "accessed": st.st_atime,
    }


@REGISTRY.register("file_hash",
                   "计算文件哈希 (校验下载完整性 / 对比文件是否相同)。",
                   danger=DANGER_LOW)
def file_hash(path: str, algorithm: str = "sha256") -> dict:
    """path: 文件绝对路径
    algorithm: md5 / sha1 / sha256"""
    algo = algorithm.lower().replace("-", "")
    if algo not in ("md5", "sha1", "sha256"):
        raise ValueError("algorithm 必须是 md5/sha1/sha256")
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"path": path, "algorithm": algo, "hash": h.hexdigest()}


@REGISTRY.register("archive",
                   "zip 压缩/解压。list=看内容, create=打包, extract=解压。"
                   "extract 会向磁盘写任意文件, 与 file_write 同级管控 (P1-7 修复)。",
                   danger=DANGER_HIGH, requires_confirm=False)
def archive(action: str, zip_path: str, source_dir: str = "",
            target_dir: str = "", confirm: bool = False) -> dict:
    """action: list / create / extract
    zip_path: zip 文件路径
    source_dir: create 时的源目录
    target_dir: extract 时的目标目录
    confirm: extract 时必须传 true (写磁盘操作与 file_write 同级)"""
    if action == "list":
        if not os.path.isfile(zip_path):
            raise ToolError(f"zip 不存在: {zip_path}")
        with zipfile.ZipFile(zip_path) as z:
            return {"count": len(z.namelist()), "files": z.namelist()[:200]}
    if action == "create":
        if not os.path.isdir(source_dir):
            raise ToolError(f"源目录不存在: {source_dir}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _d, files in os.walk(source_dir):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, source_dir))
        return {"created": zip_path, "size_bytes": os.path.getsize(zip_path)}
    if action == "extract":
        # P1-7 修复: extract 向磁盘写任意文件, 升级为 confirm 护栏
        if confirm is not True:
            raise ToolError(
                "archive(extract) 会向磁盘写入文件 (与 file_write 同级)。"
                "若确认执行, 请显式传入布尔值 \"confirm\": true。")
        if not os.path.isfile(zip_path):
            raise ToolError(f"zip 不存在: {zip_path}")
        dest = target_dir or os.path.dirname(zip_path)
        # 穿越防护: 成员解析后必须落在目标目录内 (is_relative_to 边界判断)
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                resolved = os.path.realpath(os.path.join(dest, name))
                if not resolved.startswith(os.path.realpath(dest) + os.sep) \
                        and os.path.realpath(os.path.join(dest, name)) != os.path.realpath(dest):
                    raise ToolError(f"拒绝越界成员名: {name} (zip 穿越防护)")
            z.extractall(dest)
        return {"extracted": zip_path, "to": dest}
    raise ValueError("action 必须是 list/create/extract")
