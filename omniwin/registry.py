"""工具注册器 + 安全装饰器.

安全设计源自 danielsimonjr/Windows-MCP 的 confirm:true 机制并加以延伸:
- @requires_confirm: 危险工具必须显式传 confirm=true 才执行
- 工具黑名单: 启动参数 --exclude-tools 可整体禁用危险工具
- 危险等级标注: 每个工具声明 LOW / MEDIUM / HIGH, 客户端可按级过滤
"""

from __future__ import annotations

import functools
import inspect
import json
import re
import typing
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 危险等级
# ---------------------------------------------------------------------------
DANGER_LOW = "low"      # 只读操作, 无副作用
DANGER_MEDIUM = "medium"  # 有副作用但可逆 (复制文件, 移动窗口...)
DANGER_HIGH = "high"    # 不可逆 / 破坏性 / 系统级 (删除, 杀进程, 注册表写...)

_SENSITIVE_WORDS = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "AUTH",
    "CREDENTIAL", "PRIVATE", "PAT", "APIKEY", "API_KEY",
)
# 词边界匹配: PATH 不被 KEY/PAT 误伤 (P3-2), KEYBOARD_LAYOUT 不被 KEY 误伤
_SENSITIVE_RE = re.compile(
    "|".join(rf"(?<![A-Z0-9]){w}(?![A-Z0-9])" for w in _SENSITIVE_WORDS)
)


class ToolError(Exception):
    """工具执行错误 (会被序列化为 MCP 错误结果, 而非 crash)."""


class ConfirmRequired(ToolError):
    """危险操作缺少 confirm=true 参数."""


def redact_sensitive(mapping: dict[str, Any]) -> dict[str, Any]:
    """对名字含敏感关键词的环境变量值打码 (danielsimonjr 脱敏机制的延伸).

    >>> redact_sensitive({"OPENAI_API_KEY": "sk-xxx", "PATH": "C:\\\\"})
    {'OPENAI_API_KEY': '******[已脱敏, 传 include_secrets=true 可查看]', 'PATH': 'C:\\\\'}
    >>> redact_sensitive({"AUTHOR": "someone", "KEYBOARD_LAYOUT": "us"})
    {'AUTHOR': 'someone', 'KEYBOARD_LAYOUT': 'us'}
    """
    out = {}
    for k, v in mapping.items():
        if _SENSITIVE_RE.search(k.upper()):
            out[k] = "******[已脱敏, 传 include_secrets=true 可查看]"
        else:
            out[k] = v
    return out


class ToolRegistry:
    """全局工具注册表."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._excluded: set[str] = set()

    # ------------------------------------------------------------------
    def exclude(self, names: list[str]) -> None:
        self._excluded.update(n.strip() for n in names if n.strip())

    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        description: str,
        danger: str = DANGER_LOW,
        requires_confirm: bool = False,
        confirm_hint: str = "",
    ) -> Callable:
        """注册装饰器: 把函数变成 MCP 工具.

        函数签名参数会自动转成 JSON Schema (支持 str / int / float / bool / list / dict).
        """

        def deco(fn: Callable) -> Callable:
            schema = _build_schema(fn, requires_confirm, confirm_hint)
            entry = {
                "name": name,
                "description": (
                    f"[危险级:{danger}] {description}"
                    if danger != DANGER_LOW
                    else description
                ),
                "danger": danger,
                "handler": fn,
                "schema": schema,
            }
            self._tools[name] = entry

            @functools.wraps(fn)
            def wrapper(**kwargs: Any) -> Any:
                if name in self._excluded:
                    raise ToolError(
                        f"工具 {name} 已被 --exclude-tools 禁用"
                    )
                # P0-2 修复: 只认严格布尔 True (LLM 常见传 "false"/"no" 字符串,
                # 真值判断会被 "false" 绕过 —— 外部审查报告实测复现)
                if requires_confirm and kwargs.get("confirm") is not True:
                    raise ConfirmRequired(
                        f"工具 {name} 是危险操作 ({danger} 级)。"
                        f"若确认执行, 请在参数中显式加入布尔值 \"confirm\": true。"
                        f"说明: {confirm_hint or description}"
                    )
                kwargs.pop("confirm", None)
                return fn(**kwargs)

            self._tools[name]["handler"] = wrapper
            return wrapper

        return deco

    # ------------------------------------------------------------------
    def list_tools(self) -> list[dict[str, Any]]:
        tools = []
        for name, e in sorted(self._tools.items()):
            if name in self._excluded:
                continue
            tools.append(
                {
                    "name": e["name"],
                    "description": e["description"],
                    "inputSchema": e["schema"],
                }
            )
        return tools

    # ------------------------------------------------------------------
    def call(self, name: str, arguments: dict[str, Any]) -> str:
        entry = self._tools.get(name)
        if entry is None or name in self._excluded:
            raise ToolError(f"未知或已禁用的工具: {name}")
        result = entry["handler"](**(arguments or {}))
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)

    @property
    def count(self) -> int:
        return len([n for n in self._tools if n not in self._excluded])


# ---------------------------------------------------------------------------
def _build_schema(fn: Callable, requires_confirm: bool, hint: str) -> dict:
    """从函数签名自动生成 JSON Schema.

    P0-4 修复: tools 模块有 `from __future__ import annotations` (PEP 563),
    inspect 拿到的注解是字符串 'int' 而非类型对象 int, 之前全部退化成 string.
    用 typing.get_type_hints 把字符串注解还原为真实类型对象.
    """
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    props: dict[str, Any] = {}
    required: list[str] = []
    _type_map = {
        str: "string", int: "integer", float: "number",
        bool: "boolean", list: "array", dict: "object",
    }
    for pname, param in sig.parameters.items():
        ann = hints.get(pname, param.annotation)
        if ann is inspect.Parameter.empty:
            ann = str
        # 处理 list[str] / dict[str, Any] 等泛型 (typing.X[str] 的 origin 是 X)
        base = typing.get_origin(ann) or ann
        jtype = _type_map.get(base, "string")
        prop: dict[str, Any] = {"type": jtype}
        doc = _param_doc(fn, pname)
        if doc:
            prop["description"] = doc
        props[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    if requires_confirm:
        props["confirm"] = {
            "type": "boolean",
            "description": f"必须显式传 true 才会执行。{hint}".strip(),
        }
        required.append("confirm")
    schema: dict[str, Any] = {
        "type": "object",
        "properties": props,
    }
    if required:
        schema["required"] = required
    return schema


def _param_doc(fn: Callable, pname: str) -> str:
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        s = line.strip()
        if s.startswith(f"{pname}:") or s.startswith(f"{pname} :"):
            return s.split(":", 1)[1].strip()
    return ""


# 全局单例
REGISTRY = ToolRegistry()
