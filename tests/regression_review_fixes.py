"""审查报告修复后的全量回归验证."""
import sys, json, subprocess, time
sys.path.insert(0, '.')
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
        return ('ERR', r['error'].get('code'), r['error'].get('message', '')[:80])
    t = r['result']['content'][0]['text']
    try:
        return json.loads(t)
    except (json.JSONDecodeError, TypeError):
        return t

from omniwin import winapi
time.sleep(1.0)
ok = 0
total = 0

def check(n, c):
    global ok, total
    total += 1
    ok += 1 if c else 0
    print(('  [通过] ' if c else '  [失败] ') + n)

# 热键 6 连
seq = []
for i in range(1, 7):
    winapi.shortcut('ctrl+alt+shift+p')
    time.sleep(0.9)
    s = call('control_status')
    expect = 'paused' if i % 2 else 'running'
    seq.append(s['state'] == expect)
check('热键 6 连翻转', all(seq))
call('resume')
time.sleep(0.5)

r = call('service_list', {'state_filter': 'Running', 'limit': 3})
check('service_list 转义后正常', isinstance(r, dict) and r['count'] >= 3)

r = call('service_control', {'name': 'x', 'action': 'Remove-Item', 'confirm': True})
check('service_control action 白名单', isinstance(r, str) and 'start / stop / restart' in r)

r = call('event_log', {'log_name': 'Evil`log'})
check('event_log log_name 白名单', isinstance(r, str) and '只允许' in r)

r = call('wmi_query', {'wql': 'SELECT * FROM Win32_BIOS'})
check('wmi_query 正常查询', isinstance(r, dict) and 'results' in r)

r = call('wmi_query', {'wql': 'SELECT * FROM Win32_BIOS"; echo pwned'})
check('wmi_query 注入拒绝', isinstance(r, str) and '不允许' in r)

r = call('env_get', {'name': 'PATH'})
check('PATH 不脱敏 (P3-2)', isinstance(r, dict) and '脱敏' not in str(r.get('value', '')))

r = call('registry_get', {'path': 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip'})
check('注册表深层护栏 (P1-3)', isinstance(r, str) and '关键注册表子树' in r)

r = call('system_info')
check('内存单位修复 (P2-1)', isinstance(r, dict) and abs(r['memory']['total_gb'] - 16.1) < 1.0)

r = call('volume', {'action': 'get'})
check('音量 get 仍可用', isinstance(r, dict) and 'volume' in r)

r = call('file_read', {'path': r'C:\Windows\win.ini', 'max_chars': 500})
check('file_read 大文件受限读取 (P2-4)', isinstance(r, dict) and 'content' in r)

p.stdin.close()
p.wait(timeout=10)
print(f'===== 修复回归验证: {ok}/{total} =====')
