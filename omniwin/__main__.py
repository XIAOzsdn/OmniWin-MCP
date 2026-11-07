"""python -m omniwin 入口 & CLI.

用法:
  python -m omniwin                          # 启动 MCP 服务器 (stdio)
  python -m omniwin --no-hotkey              # 不注册全局热键
  python -m omniwin --exclude-tools "powershell,registry_set"   # 禁用危险工具
  python -m omniwin --list-tools             # 打印全部工具名
"""

from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    from . import tools  # noqa: F401  (触发全部工具注册)
    from .registry import REGISTRY
    from .server import serve

    excluded: list[str] = []
    if "--exclude-tools" in args:
        i = args.index("--exclude-tools")
        if i + 1 < len(args):
            excluded = args[i + 1].split(",")
    if excluded:
        REGISTRY.exclude(excluded)

    if "--list-tools" in args:
        for t in REGISTRY.list_tools():
            print(f"{t['name']:24s} {t['description'][:70]}")
        print(f"\n共 {REGISTRY.count} 个工具")
        return 0

    hotkey = "--no-hotkey" not in args
    serve(hotkey=hotkey)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
