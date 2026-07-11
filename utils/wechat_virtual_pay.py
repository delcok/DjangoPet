# -*- coding: utf-8 -*-
"""
微信小程序虚拟支付工具类
文档: https://developers.weixin.qq.com/miniprogram/dev/platform-capabilities/business-capabilities/virtual-payment.html
"""
import hmac
import hashlib
import json
import logging
import time
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WeChatVirtualPayHelper:
    """微信小程序虚拟支付（米大师）辅助类"""

    # API基础地址
    API_BASE_URL = "https://api.weixin.qq.com"
    SANDBOX_API_BASE_URL = "https://api.weixin.qq.com"

    def __init__(self, env=0):
        """
        初始化
        :param env: 环境 0=正式环境 1=沙箱环境
        """
        self.env = env
        config = settings.WECHAT_VIRTUAL_PAY_CONFIG
        
        self.app_id = config['APP_ID']
        self.offer_id = config['OFFER_ID']
        
        # 根据环境选择app_key
        if env == 1:
            self.app_key = config['SANDBOX_APP_KEY']
        else:
            self.app_key = config['PROD_APP_KEY']
        
        self.access_token = None
        self.access_token_expire_at = 0

    def calc_pay_sig(self, uri, post_body):
        """
        计算支付签名 paySig
        算法: HMAC-SHA256(appKey, uri + '&' + post_body)
        :param uri: API路径，如 /xpay/query_user_balance，客户端固定为 'requestVirtualPayment'
        :param post_body: POST请求体JSON字符串
        :return: 十六进制签名
        """
        need_sign_msg = uri + '&' + post_body
        pay_sig = hmac.new(
            key=self.app_key.encode('utf-8'),
            msg=need_sign_msg.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        return pay_sig

    def calc_user_signature(self, post_body, session_key):
        """
        计算用户态签名 signature
        算法: HMAC-SHA256(sessionKey, post_body)
        :param post_body: POST请求体JSON字符串
        :param session_key: 用户登录session_key
        :return: 十六进制签名
        """
        signature = hmac.new(
            key=session_key.encode('utf-8'),
            msg=post_body.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        return signature

    def get_access_token(self):
        """获取接口调用凭据access_token"""
        now = time.time()
        if self.access_token and now < self.access_token_expire_at - 60:
            return self.access_token

        url = f"{self.API_BASE_URL}/cgi-bin/token"
        params = {
            'grant_type': 'client_credential',
            'appid': self.app_id,
            'secret': settings.MINI_PROGRAM_SETTINGS['USER']['APPSECRET'],
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            result = resp.json()
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.access_token_expire_at = now + result.get('expires_in', 7200)
                logger.info("获取虚拟支付access_token成功")
                return self.access_token
            else:
                logger.error(f"获取access_token失败: {result}")
                raise Exception(f"获取access_token失败: {result.get('errmsg', '未知错误')}")
        except Exception as e:
            logger.error(f"获取access_token异常: {e}")
            raise

    def _request(self, uri, data):
        """
        发送带签名的POST请求到米大师API
        :param uri: API路径，如 /xpay/query_user_balance
        :param data: 请求数据字典
        :return: 响应结果
        """
        url = f"{self.API_BASE_URL}{uri}"
        access_token = self.get_access_token()
        
        # 添加环境参数
        data['env'] = self.env
        
        # 序列化为JSON字符串（用于签名）
        post_body = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        
        # 计算支付签名
        pay_sig = self.calc_pay_sig(uri, post_body)
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        params = {
            'access_token': access_token,
            'pay_sig': pay_sig,
        }
        
        try:
            logger.info(f"虚拟支付API请求: {uri}, data={post_body}")
            resp = requests.post(url, params=params, data=post_body.encode('utf-8'), 
                               headers=headers, timeout=30)
            result = resp.json()
            logger.info(f"虚拟支付API响应: {uri}, result={result}")
            
            if result.get('errcode', 0) != 0:
                logger.error(f"虚拟支付API错误: {result}")
            return result
        except Exception as e:
            logger.error(f"虚拟支付API请求异常: {uri}, error={e}")
            raise

    def query_user_balance(self, openid, user_ip='127.0.0.1'):
        """
        查询用户代币（金币）余额
        :param openid: 用户openid
        :param user_ip: 用户IP
        :return: 余额信息
        """
        uri = '/xpay/query_user_balance'
        data = {
            'openid': openid,
            'user_ip': user_ip,
        }
        return self._request(uri, data)

    def query_order(self, openid, order_id=None, out_trade_no=None):
        """查询订单信息。openid 必填（米大师按用户维度查单）。"""
        uri = '/xpay/query_order'
        data = {'openid': openid}          # ★ openid 必填
        if order_id:
            data['order_id'] = order_id
        if out_trade_no:
            data['out_trade_no'] = out_trade_no
        data['user_ip'] = '127.0.0.1'
        result = self._request(uri, data)
        logger.info('query_order 返回 out_trade_no=%s result=%s', out_trade_no, result)
        return result

    def refund_order(self, out_trade_no, out_refund_no, refund_fee, reason=''):
        """
        申请退款
        :param out_trade_no: 原支付商户订单号
        :param out_refund_no: 商户退款单号
        :param refund_fee: 退款金额（分）
        :param reason: 退款原因
        :return: 退款结果
        """
        uri = '/xpay/refund_order'
        data = {
            'out_trade_no': out_trade_no,
            'out_refund_no': out_refund_no,
            'refund_fee': refund_fee,
            'reason': reason,
            'user_ip': '127.0.0.1',
        }
        return self._request(uri, data)

    def notify_provide_goods(self, out_trade_no):
        """
        通知已发货（发放金币）
        :param out_trade_no: 商户订单号
        :return: 结果
        """
        uri = '/xpay/notify_provide_goods'
        data = {
            'out_trade_no': out_trade_no,
            'user_ip': '127.0.0.1',
        }
        return self._request(uri, data)

    def present_currency(self, openid, quantity, bill_no, user_ip='127.0.0.1'):
        """
        赠送代币（金币）
        :param openid: 用户openid
        :param quantity: 赠送数量
        :param bill_no: 赠送单号
        :param user_ip: 用户IP
        :return: 结果
        """
        uri = '/xpay/present_currency'
        data = {
            'openid': openid,
            'quantity': quantity,
            'bill_no': bill_no,
            'user_ip': user_ip,
        }
        return self._request(uri, data)

    def generate_client_pay_params(self, openid, session_key, buy_quantity, out_trade_no, 
                                   attach='', platform='android'):
        """
        生成前端调起支付所需的参数
        :param openid: 用户openid
        :param session_key: 用户session_key
        :param buy_quantity: 购买代币数量（注意：这里是在MP后台配置的兑换档位对应的数量，不是金额）
        :param out_trade_no: 商户订单号
        :param attach: 透传数据
        :param platform: 平台 android/ios/windows
        :return: 前端支付参数
        """
        # 构造signData
        sign_data_dict = {
            'offerId': self.offer_id,
            'buyQuantity': buy_quantity,
            'env': self.env,
            'currencyType': 'CNY',
            'outTradeNo': out_trade_no,
            'attach': attach,
            'mode': 'short_series_coin',  # 代币充值模式
        }
        logger.info('虚拟支付 signData=%s', sign_data_dict)

        # 序列化为JSON字符串（注意：要和实际传给前端的完全一致）
        sign_data = json.dumps(sign_data_dict, separators=(',', ':'), ensure_ascii=False)
        
        # 计算支付签名
        pay_sig = self.calc_pay_sig('requestVirtualPayment', sign_data)
        
        # 计算用户态签名
        signature = self.calc_user_signature(sign_data, session_key)
        
        return {
            'signData': sign_data,
            'paySig': pay_sig,
            'signature': signature,
            'mode': 'short_series_coin',
            'env': self.env,
        }

    @staticmethod
    def parse_xml_callback(xml_data):
        """
        解析微信回调XML数据
        :param xml_data: XML字符串
        :return: 字典格式数据
        """
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_data)
        result = {}
        for child in root:
            tag = child.tag
            text = child.text
            # 处理嵌套对象（如WeChatPayInfo、CoinInfo等）
            if len(child) > 0:
                nested = {}
                for subchild in child:
                    nested[subchild.tag] = subchild.text
                result[tag] = nested
            else:
                result[tag] = text
        return result
