# -*- coding: utf-8 -*-
# @Time    : 2025/7/16 18:27
# @Author  : Delock
import hashlib
import logging
import xml.etree.ElementTree as ET
from wechatpy import WeChatPayException
from wechatpy.pay import WeChatPay
from django.conf import settings
import uuid
from datetime import datetime

import time
import random
import string
import json
from base64 import b64encode, b64decode
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

class WeChatPayHelper:
    def __init__(self):
        config = settings.WECHAT_PAY_CONFIG
        self.pay = WeChatPay(
            appid=config['APPID'],
            mch_id=config['MCH_ID'],
            api_key=config['API_KEY'],
            mch_cert=config['CERT_PATH'],
            mch_key=config['KEY_PATH'],
        )

        self.trade_type = config['TRADE_TYPE']

    def generate_out_trade_no(self):
        return f"{settings.WECHAT_PAY_CONFIG['MCH_ID']}{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8]}"

    def create_payment_order(self, openid, total_fee, body, out_trade_no=None):
        if not out_trade_no:
            out_trade_no = self.generate_out_trade_no()
        try:
            logger.info(f"delock开始创建支付订单: openid={openid}, total_fee={total_fee}, body={body}, out_trade_no={out_trade_no}")
            order = self.pay.order.create(
                body=body,
                trade_type=self.trade_type,
                notify_url="https://pet.yimengzhiyuan.com:8080/api/v1/wechat_callback/payment/",
                total_fee=total_fee,
                client_ip='121.196.245.220',  # 替换为您的服务器IP
                user_id=openid,
                out_trade_no=out_trade_no,
            )
            logger.info(f"创建支付订单成功: {order}")
            pay_params = self.pay.jsapi.get_jsapi_params(order.get('prepay_id'))
            pay_params["prepay_id"] = order.get('prepay_id')
            pay_params["mch_id"] = self.pay.mch_id
            return pay_params
        except WeChatPayException as e:
            logger.error(f"创建支付订单失败: {e}")
            raise e

    def parse_callback(self, xml_data, callback_type):
        """
        解析并验证回调数据
        :param xml_data: 微信回调的XML数据
        :param callback_type: 回调类型，'payment' 或 'refund'
        :return: 解析后的数据字典
        """

        try:
            if callback_type == 'payment':
                data = self.pay.parse_payment_result(xml_data)
            else:
                raise ValueError("Invalid callback_type")
            return data
        except WeChatPayException as e:
            logger.error(f"{callback_type.capitalize()}回调解析失败: {e}")
            raise e

    def verify_signature(self, xml_data, signature):
        """
        验证微信支付回调的签名
        :param xml_data: 回调的XML数据
        :param signature: 微信支付回调提供的签名
        :return: 如果签名正确返回True，否则返回False
        """
        # 解析xml_data，获取微信支付回调的所有参数
        root = ET.fromstring(xml_data)
        data = {elem.tag: elem.text for elem in root if elem.tag != 'sign'}

        # 按照字段名字典排序
        sorted_fields = sorted(data.items())

        # 拼接参数字符串
        sign_string = '&'.join([f"{k}={v}" for k, v in sorted_fields])
        sign_string = f"{sign_string}&key={self.pay.api_key}"  # 加上API密钥

        # 计算MD5签名并转换为大写
        calculated_signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()

        # 比较计算出来的签名和回调中的签名是否一致
        if calculated_signature == signature.upper():
            return True
        else:
            logger.error(f"签名验证失败: 计算签名={calculated_signature}, 回调签名={signature}")
            return False

    def cancel_payment_order(self, out_trade_no):
        try:
            # 调用微信支付的接口来关闭订单
            result = self.pay.order.close(out_trade_no=out_trade_no)
            return result
        except WeChatPayException as e:
            logger.error(f"取消支付订单失败: {e}")
            raise e
