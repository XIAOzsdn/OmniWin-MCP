"""第三轮修复回归 - 最终稳定版 (独立进程分组 + 防抖缓冲)."""
import sys, json, subprocess, time

def run_group(tests, setup_sleep=1.0):
    """每组独立起一个 server 进程, 按顺序执行测试元组列表."""
    p = subprocess.Popen(['python', '-m', 'omniwin'], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding='utf-8')
    mid = [0]
    def call(name, args=None):
        mid[0] += 1
        p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': mid[0], 'method': 'tools/call',
                                  'params': {'name': name, 'arguments': args or {}}}) + '\n')
        p.stdin.flush()
        r = json.loads(p.stdout.readline())
        if 'error' in r:
            return ('ERR', r['error'].get('code'))
        t = r['result']['content'][0]['text']
        try:
            return json.loads(t)
        except (json.JSONDecodeError, TypeError):
            return t
    time.sleep(setup_sleep)
    for name, args, label, judge in tests:
        r = call(name, args)
        yield label, judge(r)
    p.stdin.close()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()

ok = 0
total = 0
def check(label, passed):
    global ok, total
    total += 1
    ok += 1 if passed else 0
    print(('  [通过] ' if passed else '  [失败] ') + label)

sys.path.insert(0, '.')
from omniwin import winapi

# ============ 组1: N-P0-5 冻结不可自救 ============
for label, passed in run_group([
    ('pause', {}, 'pause 冻结', lambda r: isinstance(r, dict) and r['state'] == 'paused'),
    ('resume', {}, '冻结期 resume 被拦 (N-P0-5)', lambda r: isinstance(r, str) and 'SERVER_PAUSED' in r),
    ('system_info', {}, '冻结依然生效', lambda r: isinstance(r, str) and 'SERVER_PAUSED' in r),
    ('control_status', {}, 'control_status 豁免', lambda r: isinstance(r, dict) and r['state'] == 'paused'),
]):
    check(label, passed)

# ============ 组2: 完整冻结/解冻生命周期 (热键) ============
p = subprocess.Popen(['python', '-m', 'omniwin'], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     text=True, encoding='utf-8')
mid = [0]
def call2(name, args=None):
    mid[0] += 1
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': mid[0], 'method': 'tools/call',
                              'params': {'name': name, 'arguments': args or {}}}) + '\n')
    p.stdin.flush()
    r = json.loads(p.stdout.readline())
    if 'error' in r:
        return ('ERR',)
    t = r['result']['content'][0]['text']
    try:
        return json.loads(t)
    except (json.JSONDecodeError, TypeError):
        return t

time.sleep(1.2)
r = call2('pause')
check('组2: AI pause', isinstance(r, dict) and r['state'] == 'paused')
time.sleep(0.9)
winapi.shortcut('ctrl+alt+shift+p')
time.sleep(1.2)
r = call2('control_status')
check('组2: 人类热键解冻 (AI pause 后)', isinstance(r, dict) and r['state'] == 'running')
time.sleep(0.9)
winapi.shortcut('ctrl+alt+shift+p')
time.sleep(1.2)
r = call2('control_status')
check('组2: 热键冻结', isinstance(r, dict) and r['state'] == 'paused')
r = call2('resume')
check('组2: 人类冻结后 resume 被拦', isinstance(r, str) and 'SERVER_PAUSED' in r)
time.sleep(0.9)
winapi.shortcut('ctrl+alt+shift+p')
time.sleep(1.2)
r = call2('control_status')
check('组2: 人类热键再解冻', isinstance(r, dict) and r['state'] == 'running')
p.stdin.close()
try:
    p.wait(timeout=5)
except Exception:
    p.kill()

# ============ 组3: notify 注入 ============
for label, passed in run_group([
    ('notify', {'title': "a'); Write-Output PWNED7; ('", 'message': 'x'},
     'notify 注入串不崩溃 (N-P0-7 转义)', lambda r: isinstance(r, str) and '通知已发送' in r),
], setup_sleep=1.0):
    check(label, passed)

# ============ 组4: launch_app 注入 ============
for label, passed in run_group([
    ('launch_app', {'name': "notepad', Write-Output PWNED10, '"},
     'launch_app 注入串不崩溃 (N-P1-10 转义)', lambda r: isinstance(r, (str, dict))),
], setup_sleep=1.0):
    check(label, passed)

# ============ 组5: powershell stdin ============
for label, passed in run_group([
    ('powershell', {'command': '[Console]::In.ReadLine()', 'timeout_seconds': 3, 'confirm': True},
     'powershell stdin 重定向 (N-P1-9): ReadLine 阻塞超时而非吃协议流',
     lambda r: isinstance(r, str) and '超时' in r),
    ('control_status', {}, '超时后 server 仍存活 (协议流安全旁证)',
     lambda r: isinstance(r, dict) and 'state' in r),
], setup_sleep=1.0):
    check(label, passed)

print(f'===== 第三轮修复回归 (稳定版): {ok}/{total} =====')
