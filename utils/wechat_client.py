# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 21:31
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
微信小程序客户端
- 单例模式
- access_token 通过 Redis 自动缓存（wechatpy 自带 RedisStorage）
- 所有需要 access_token 的接口（生成小程序码、获取手机号等）共享同一份 token
"""
import logging
from django.conf import settings
from django.utils import timezone
from wechatpy import WeChatClient
from wechatpy.session.redisstorage import RedisStorage
from wechatpy.exceptions import WeChatClientException

from utils.cache import get_redis_connection

_user_mini_client = None

logger = logging.getLogger(__name__)

# 常用快递公司中文名称 -> 微信官方编码映射
# 完整列表可调用微信接口获取：https://developers.weixin.qq.com/miniprogram/dev/api-backend/open-api/order-management/order.get-delivery-list.html
EXPRESS_COMPANY_MAP = {
    "顺丰速运": "SF",
    "圆通速递": "YTO",
    "中通快递": "ZTO",
    "申通快递": "STO",
    "韵达速递": "YD",
    "邮政快递包裹": "YZPY",
    "EMS": "EMS",
    "京东物流": "JD",
    "极兔速递": "JTSD",
    "百世快递": "HTKY",
    "德邦快递": "DBL",
    "宅急送": "ZJS",
    "天天快递": "HHTT",
    "优速快递": "UC",
    "速尔快递": "SURE",
    "国通快递": "GTO",
    "全峰快递": "QFKD",
    "快捷快递": "FAST",
    "丹鸟物流": "DANNIAO",
    "中铁快运": "CRE",
}


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


def upload_wechat_shipping_info(
    out_trade_no: str,
    openid: str,
    logistics_type: int,
    item_desc: str,
    tracking_no: str = None,
    express_company_name: str = None,
    delivery_mode: int = 1,
    is_all_delivered: bool = None,
) -> bool:
    """
    上传发货/自提信息到微信订单中心
    :param out_trade_no: 商户支付单号（PaymentOrder.out_trade_no）
    :param openid: 用户微信openid
    :param logistics_type: 物流类型：1=实体物流 2=同城配送 3=虚拟商品 4=用户自提
    :param item_desc: 商品描述，如"翡翠吊坠x1，和田玉手链x2"，限120字
    :param tracking_no: 物流单号（实体物流必填）
    :param express_company_name: 快递公司中文名称（实体物流必填，自动转换为编码）
    :param delivery_mode: 发货模式：1=统一发货 2=分拆发货
    :param is_all_delivered: 分拆发货时是否全部发货完成
    :return: 上传成功返回True，失败返回False
    """
    try:
        client = get_user_mini_client()
        mch_id = settings.WECHAT_PAY_CONFIG['MCH_ID']

        # 构造订单标识：使用商户侧单号
        order_key = {
            "order_number_type": 1,
            "mchid": mch_id,
            "out_trade_no": out_trade_no,
        }

        # 构造物流列表
        shipping_item = {
            "item_desc": item_desc[:120],  # 限120字
        }
        # 实体物流需要补充物流信息
        if logistics_type == 1:
            if not tracking_no or not express_company_name:
                logger.error(f"上传微信发货信息失败：实体物流必须提供物流单号和快递公司，out_trade_no={out_trade_no}")
                return False
            # 转换快递公司编码
            express_code = EXPRESS_COMPANY_MAP.get(express_company_name)
            if not express_code:
                logger.warning(f"未找到快递公司[{express_company_name}]的编码，将使用名称作为编码，请补充映射")
                express_code = express_company_name
            shipping_item["tracking_no"] = tracking_no
            shipping_item["express_company"] = express_code

        shipping_list = [shipping_item]

        # 构造请求体
        payload = {
            "order_key": order_key,
            "logistics_type": logistics_type,
            "delivery_mode": delivery_mode,
            "shipping_list": shipping_list,
            "upload_time": timezone.now().isoformat(timespec='milliseconds'),
            "payer": {"openid": openid},
        }
        # 分拆发货需要传is_all_delivered
        if delivery_mode == 2 and is_all_delivered is not None:
            payload["is_all_delivered"] = is_all_delivered

        # 调用微信接口
        result = client.post("/wxa/sec/order/upload_shipping_info", data=payload)
        if result.get('errcode') == 0:
            logger.info(f"上传微信发货信息成功：out_trade_no={out_trade_no}, logistics_type={logistics_type}")
            return True
        else:
            logger.error(f"上传微信发货信息失败：out_trade_no={out_trade_no}, errcode={result.get('errcode')}, errmsg={result.get('errmsg')}")
            return False
    except WeChatClientException as e:
        logger.error(f"上传微信发货信息接口调用异常：out_trade_no={out_trade_no}, error={str(e)}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"上传微信发货信息未知异常：out_trade_no={out_trade_no}, error={str(e)}", exc_info=True)
        return False