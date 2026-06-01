# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 21:05
# @Author  : Delock

"""券码生成工具"""
import secrets
import string

# 排除易混淆字符：0/O、1/I/L、2/Z、5/S、8/B
SAFE_ALPHABET = '34679ACDEFGHJKMNPQRTUVWXY'


def generate_redemption_code(length: int = 12) -> str:
    """
    生成人工可输入的核销码
    - 12 位
    - 大写字母 + 数字
    - 排除易混淆字符
    存储时不带连字符，展示时按 4-4-4 分组
    """
    return ''.join(secrets.choice(SAFE_ALPHABET) for _ in range(length))


def normalize_code(code: str) -> str:
    """规范化用户输入的核销码：去空格/连字符，转大写"""
    if not code:
        return ''
    return code.replace('-', '').replace(' ', '').strip().upper()