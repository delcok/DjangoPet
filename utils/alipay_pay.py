# -*- coding: utf-8 -*-
import logging
from alipay import AliPay
from django.conf import settings

logger = logging.getLogger(__name__)


class AlipayPayHelper:
    def __init__(self):
        config = settings.ALIPAY_CONFIG
        self.appid = config['APPID']
        self.app_private_key = config['APP_PRIVATE_KEY']
        self.alipay_public_key = config['ALIPAY_PUBLIC_KEY']
        self.sign_type = config['SIGN_TYPE']
        self.debug = config['DEBUG']
        self.notify_url = config['NOTIFY_URL']
        self.return_url = config['RETURN_URL']

        # 初始化支付宝SDK
        self.alipay = AliPay(
            appid=self.appid,
            app_notify_url=self.notify_url,
            app_private_key_string=self.app_private_key,
            alipay_public_key_string=self.alipay_public_key,
            sign_type=self.sign_type,
            debug=self.debug,  # True为沙箱环境，False为生产
        )

    def create_app_pay_order(self, out_trade_no, total_amount, subject, body=None, timeout_express='30m'):
        """
        创建APP支付订单
        :param out_trade_no: 商户订单号
        :param total_amount: 订单金额（单位：元，支持两位小数）
        :param subject: 订单标题
        :param body: 订单描述（可选）
        :param timeout_express: 支付超时时间，默认30分钟
        :return: 订单字符串，直接返回给移动端调起支付宝
        """
        try:
            logger.info(f"创建支付宝APP支付订单: out_trade_no={out_trade_no}, total_amount={total_amount}, subject={subject}")
            # 调用SDK生成APP支付订单信息
            order_string = self.alipay.api_alipay_trade_app_pay(
                out_trade_no=out_trade_no,
                total_amount=total_amount,
                subject=subject,
                body=body,
                timeout_express=timeout_express,
            )
            logger.info(f"支付宝APP订单创建成功: out_trade_no={out_trade_no}")
            return order_string
        except Exception as e:
            logger.error(f"创建支付宝APP订单失败: out_trade_no={out_trade_no}, error={e}")
            raise e

    def verify_notify(self, data):
        """
        验证支付宝异步回调签名
        :param data: 回调的POST参数字典（request.POST.dict()）
        :return: 验证成功返回True，失败返回False
        """
        try:
            signature = data.pop("sign", None)
            signature_type = data.pop("sign_type", None)
            # 验证签名
            success = self.alipay.verify(data, signature)
            if success:
                logger.info(f"支付宝回调签名验证成功: out_trade_no={data.get('out_trade_no')}")
            else:
                logger.error(f"支付宝回调签名验证失败: out_trade_no={data.get('out_trade_no')}")
            return success
        except Exception as e:
            logger.error(f"支付宝回调验证异常: {e}")
            return False

    def query_order(self, out_trade_no=None, trade_no=None):
        """
        查询订单状态
        :param out_trade_no: 商户订单号（和trade_no二选一）
        :param trade_no: 支付宝交易号（和out_trade_no二选一）
        :return: 订单查询结果
        """
        try:
            result = self.alipay.api_alipay_trade_query(
                out_trade_no=out_trade_no,
                trade_no=trade_no,
            )
            logger.info(f"支付宝订单查询结果: {result}")
            return result
        except Exception as e:
            logger.error(f"支付宝订单查询失败: out_trade_no={out_trade_no}, error={e}")
            raise e

    def refund(self, out_trade_no, refund_amount, refund_reason='正常退款', out_request_no=None):
        """
        申请退款
        :param out_trade_no: 商户订单号
        :param refund_amount: 退款金额（单位：元）
        :param refund_reason: 退款原因
        :param out_request_no: 退款请求号（部分退款时必填，同一订单多次退款唯一）
        :return: 退款结果
        """
        try:
            result = self.alipay.api_alipay_trade_refund(
                out_trade_no=out_trade_no,
                refund_amount=refund_amount,
                refund_reason=refund_reason,
                out_request_no=out_request_no,
            )
            logger.info(f"支付宝退款申请成功: out_trade_no={out_trade_no}, refund_amount={refund_amount}")
            return result
        except Exception as e:
            logger.error(f"支付宝退款申请失败: out_trade_no={out_trade_no}, error={e}")
            raise e

    def close_order(self, out_trade_no=None, trade_no=None):
        """
        关闭未支付订单
        :param out_trade_no: 商户订单号
        :param trade_no: 支付宝交易号
        :return: 关闭结果
        """
        try:
            result = self.alipay.api_alipay_trade_close(
                out_trade_no=out_trade_no,
                trade_no=trade_no,
            )
            logger.info(f"支付宝订单关闭成功: out_trade_no={out_trade_no}")
            return result
        except Exception as e:
            logger.error(f"支付宝订单关闭失败: out_trade_no={out_trade_no}, error={e}")
            raise e
