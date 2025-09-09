# -*- coding: utf-8 -*-
# @Time    : 2025/8/20 17:22
# @Author  : Delock
import requests

def fetch_phone_number(access_token, phone_code):
    """
    获取微信用户手机号
    参考: https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/user-info/phone-number/getPhoneNumber.html
    """
    url = f"https://api.weixin.qq.com/wxa/business/getuserphonenumber?access_token={access_token}"
    data = {"code": phone_code}

    try:
        response = requests.post(url, json=data, timeout=10)
        result = response.json()

        if result.get('errcode') == 0:
            phone_info = result.get('phone_info', {})
            return phone_info.get('phoneNumber')
        else:
            print(f"获取手机号失败: {result}")
            return None
    except Exception as e:
        print(f"获取手机号异常: {str(e)}")
        return None