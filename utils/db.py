# -*- coding: utf-8 -*-
"""
通用 DB 工具
"""


def escape_like(s: str) -> str:
    """
    转义 LIKE 通配符,防止用户输入 %%%/___ 触发慢查询/全表扫描。
    用法:
        queryset.filter(name__icontains=escape_like(keyword))
    """
    if not s:
        return s
    return (
        s.replace('\\', '\\\\')
         .replace('%', '\\%')
         .replace('_', '\\_')
    )