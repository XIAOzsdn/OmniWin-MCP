"""工具包汇总: 导入即注册."""

from .. import registry  # noqa: F401  (先建立注册表)
from .. import control  # noqa: F401  (管控工具)

# 13 大类工具组
from . import input  # noqa: F401
from . import screen  # noqa: F401
from . import window_uia  # noqa: F401
from . import process_shell  # noqa: F401
from . import files  # noqa: F401
from . import system  # noqa: F401
from . import security_net_misc  # noqa: F401
from . import enhancer_tools  # noqa: F401
