"""OmniWin-MCP 冒烟测试: 真实启动 server, 走 stdio JSON-RPC 全流程.

验证项:
 1. initialize 握手            2. tools/list 数量与 schema
 3. confirm 拦截 (危险操作)    4. confirm 放行
 5. 冻结闸门 (pause 后拦截)    6. control_status 冻结期豁免
 7. resume 恢复                8. 密钥脱敏
 9. 真实功能: 截图/剪贴板/系统信息
10. SSRF 防护 (拒绝内网地址)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PY = sys.executable
from omniwin import winapi as _w  # 产品级注入器 (40字节结构体)

passed, failed = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else failed).append((name, detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -- {detail}" if detail and not ok else ""))


class McpClient:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [PY, "-m", "omniwin"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def send(self, obj: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict:
        assert self.proc.stdout
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("服务器无响应 (可能崩溃), stderr: " +
                               (self.proc.stderr.read()[:2000] if self.proc.stderr else ""))
        return json.loads(line)

    def call_tool(self, name: str, args: dict | None = None, msg_id: int = 0):
        self.send({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                   "params": {"name": name, "arguments": args or {}}})
        return self.recv()

    def close(self) -> None:
        try:
            self.proc.stdin.close() if self.proc.stdin else None
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main() -> int:
    # 环境变量必须在启动子进程之前设置 (子进程通过 environ 继承)
    os.environ["OMNIWIN_TEST_API_KEY"] = "sk-super-secret-123"
    c = McpClient()
    mid = 0
    try:
        # ---- 1. initialize ----
        print("== 1. initialize 握手 ==")
        mid += 1
        c.send({"jsonrpc": "2.0", "id": mid, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18",
                           "capabilities": {},
                           "clientInfo": {"name": "smoke-test", "version": "0"}}})
        resp = c.recv()
        ok = resp["result"]["serverInfo"]["name"] == "OmniWin-MCP"
        check("initialize 返回 serverInfo", ok, str(resp)[:200])
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # ---- 2. tools/list ----
        print("== 2. tools/list ==")
        mid += 1
        c.send({"jsonrpc": "2.0", "id": mid, "method": "tools/list"})
        resp = c.recv()
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        check(f"工具数量 >= 74 (实际 {len(tools)})", len(tools) >= 74)
        check("含管控工具", {"control_status", "pause", "resume"} <= names)
        check("含输入工具", {"click", "type_text", "shortcut"} <= names)
        check("含OCR工具", {"ocr_screen", "find_text_on_screen"} <= names)
        check("含运维工具", {"service_control", "event_log", "wmi_query",
                            "defender_status", "firewall_rule"} <= names)
        check("schema 是 JSON object", all(
            t["inputSchema"]["type"] == "object" for t in tools))

        # ---- 3. confirm 拦截 (P2-14 新格式: result.isError + 文本标记) ----
        print("== 3. 危险操作 confirm 拦截 ==")
        resp = c.call_tool("file_delete", {"path": "C:/nonexist-xxx.txt",
                                           "confirm": "false"})
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("字符串 confirm='false' 也被拦 (P0-2 修复)",
              r.get("isError") is True and "CONFIRM_REQUIRED -32001" in text,
              text[:150])
        check("错误信息含 confirm 指引", "confirm" in text)

        # ---- 4. confirm 放行 ----
        print("== 4. confirm 放行 ==")
        tmp = os.path.join(tempfile.gettempdir(), "omniwin_smoke_test.txt")
        with open(tmp, "w") as f:
            f.write("hello")
        resp = c.call_tool("file_delete", {"path": tmp, "confirm": True})
        ok = "content" in resp.get("result", {}) and not os.path.exists(tmp)
        check("带 confirm=true 删除成功", ok, str(resp)[:200])

        # ---- 5. 冻结闸门 ----
        print("== 5. 人类管控: 冻结闸门 ==")
        resp = c.call_tool("pause")
        check("pause 工具可用", "content" in resp.get("result", {}), str(resp)[:200])
        resp = c.call_tool("system_info")
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("冻结后普通工具被拦 (-32002 标记)",
              r.get("isError") is True and "SERVER_PAUSED -32002" in text, text[:150])

        # ---- 6. control_status 冻结期豁免 ----
        print("== 6. control_status 冻结期豁免 ==")
        resp = c.call_tool("control_status")
        text = resp["result"]["content"][0]["text"]
        status = json.loads(text)
        check("冻结期 control_status 可用且报 paused",
              status["state"] == "paused", text[:200])

        # ---- 7. resume (N-P0-5 新语义: 冻结期 resume 也被拦, 解冻只认热键) ----
        print("== 7. resume 被闸门拦截 + 人类热键解冻 ==")
        resp = c.call_tool("resume")
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("冻结期 resume 也被拦 (N-P0-5: AI 无法自救)",
              r.get("isError") is True and "SERVER_PAUSED" in text, text[:150])
        # 人类解冻: 产品级 winapi.shortcut 注入 (等效物理按键; 先过 0.6s 防抖窗)
        time.sleep(0.8)
        _w.shortcut('ctrl+alt+shift+p')
        time.sleep(1.2)
        resp = c.call_tool("control_status")
        text = resp["result"]["content"][0]["text"]
        check("人类热键解冻成功", '"running"' in text, text[:200])
        resp = c.call_tool("get_cursor_pos")
        check("恢复后普通工具可用", "content" in resp.get("result", {}), str(resp)[:200])

        # ---- 8. 密钥脱敏 ----
        print("== 8. 密钥脱敏 ==")
        resp = c.call_tool("env_get", {"name": "OMNIWIN_TEST_API_KEY"})
        text = resp["result"]["content"][0]["text"]
        check("敏感变量被脱敏", "sk-super-secret" not in text and "脱敏" in text, text[:200])

        # ---- 9. 真实功能 ----
        print("== 9. 真实功能: 截图 / 剪贴板 / 系统信息 ==")
        resp = c.call_tool("screenshot", {"return_base64": False})
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        png_ok = os.path.isfile(data.get("path", "")) and data["size_bytes"] > 1000
        check("GDI 截图成功且 PNG 有效", png_ok, text[:200])

        resp = c.call_tool("clipboard_write", {"text": "OmniWin冒烟测试中文"})
        resp = c.call_tool("clipboard_read")
        text = resp["result"]["content"][0]["text"]
        check("剪贴板写读回环 (含中文)", "OmniWin冒烟测试中文" in text, text[:200])

        resp = c.call_tool("system_info")
        text = resp["result"]["content"][0]["text"]
        check("system_info 返回", '"os"' in text, text[:200])

        resp = c.call_tool("list_windows")
        text = resp["result"]["content"][0]["text"]
        check("list_windows 返回窗口列表", '"count"' in text, text[:200])

        # ---- 10. SSRF 防护 ----
        print("== 10. SSRF 防护 ==")
        resp = c.call_tool("http_request", {"url": "http://127.0.0.1/x"})
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("拒绝回环地址", r.get("isError") is True and "SSRF" in text, text[:150])
        resp = c.call_tool("http_request", {"url": "http://192.168.1.1/x"})
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("拒绝私网地址", r.get("isError") is True and "SSRF" in text, text[:150])

        # ---- 11. OCR 实测 (已装 rapidocr 时验证真实识别; 未装时验证优雅降级) ----
        print("== 11. OCR 实测 ==")
        resp = c.call_tool("ocr_screen")
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        try:
            ocr = json.loads(text)
            check("OCR 真实识别屏幕文字 (count > 0)",
                  isinstance(ocr, dict) and ocr.get("count", 0) > 0, text[:150])
        except (json.JSONDecodeError, TypeError):
            check("OCR 未安装时优雅降级给安装指引",
                  "pip install" in text, text[:150])

        # ---- 12. 未知工具 ----
        print("== 12. 未知工具 ==")
        resp = c.call_tool("no_such_tool")
        r = resp.get("result", {})
        text = r.get("content", [{}])[0].get("text", "") if r else ""
        check("未知工具返回错误", r.get("isError") is True and "未知" in text, text[:150])

    finally:
        c.close()

    print(f"\n========== 冒烟测试结果: {len(passed)} 通过 / {len(failed)} 失败 ==========")
    if failed:
        for name, d in failed:
            print(f"  失败: {name}: {d[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
