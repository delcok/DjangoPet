# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 21:31
# @Author  : Delock

from django.conf import settings
from wechatpy import WeChatClient
from wechatpy.session.redisstorage import RedisStorage

from utils.cache import get_redis_connection

_user_mini_client = None


def get_user_mini_client() -> WeChatClient:
    """获取用户端小程序的 WeChatClient（单例 + Redis 缓存 token）"""
    global _user_mini_client
    if _user_mini_client is None:
        cfg = settings.MINI_PROGRAM_SETTINGS['USER']
        session = RedisStorage(
            get_redis_connection(),
            prefix='wechatpy:user_mini',
        )
        _user_mini_client = WeChatClient(
            cfg['APPID'],
            cfg['APPSECRET'],
            session=session,
        )
    return _user_mini_client