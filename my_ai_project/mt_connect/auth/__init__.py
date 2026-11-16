"""认证鉴权子包：注册 / 登录 / Token 校验依赖。

对外从本包直接导出公共符号，调用方写：

    from my_ai_project.mt_connect.auth import register, login, get_current_user
"""

from my_ai_project.mt_connect.auth.my_auth import (
    get_current_user,
    login,
    register,
)

__all__ = ["get_current_user", "login", "register"]
