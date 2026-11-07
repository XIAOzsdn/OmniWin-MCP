"""验证 _psq 转义: 攻击串经转义后应被 PS 当作纯字符串回显."""
import sys
sys.path.insert(0, '.')
from omniwin.tools.window_uia import _psq

attack = "x'; Write-Output PWNED; '"
q = _psq(attack)
print('转义后:', q)
r = _psq  # 占位
from omniwin.tools.window_uia import _ps
res = _ps(f'Write-Output {q}')
print('PS 回显:', repr(res.stdout.strip()))
print('回显==原攻击串:', res.stdout.strip() == attack)
print('注入被中和:', 'PWNED' not in res.stdout)
