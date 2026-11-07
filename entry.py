"""PyInstaller 单文件入口 (极薄包装, 避免打包 __main__ 的相对导入问题)."""

from omniwin.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
