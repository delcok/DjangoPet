# -*- coding: utf-8 -*-
# @Time    : 2025/8/20 17:22
# @Author  : Delock
import logging
import requests

from utils.wechat_client import get_user_mini_client

logger = logging.getLogger(__name__)


def fetch_phone_number(phone_code: str) -> str | None:
    """
    获取微信用户手机号
    参考: https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/user-info/phone-number/getPhoneNumber.html

    Args:
        phone_code: 前端 wx.getPhoneNumber 拿到的 code

    Returns:
        手机号字符串，失败返回 None

    说明：
        access_token 由 wechatpy 单例客户端管理，自动从 Redis 读取/刷新，
        无需外部传入。
    """
    if not phone_code:
        return None

    try:
        client = get_user_mini_client()
        access_token = client.access_token
        if not access_token:
            logger.error('获取手机号失败：access_token 为空')
            return None
    except Exception as e:
        logger.error(f'获取 access_token 异常: {e}')
        return None

    url = f'https://api.weixin.qq.com/wxa/business/getuserphonenumber?access_token={access_token}'
    try:
        response = requests.post(url, json={'code': phone_code}, timeout=10)
        result = response.json()

        if result.get('errcode') == 0:
            phone_info = result.get('phone_info', {})
            return phone_info.get('phoneNumber')
        else:
            logger.error(f'获取手机号失败: {result}')
            return None
    except Exception as e:
        logger.error(f'获取手机号异常: {e}')
        return None