# utils/send_sms.py
import logging
from django.conf import settings
from alibabacloud_dysmsapi20170525.client import Client
from alibabacloud_dysmsapi20170525 import models as sms_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from .cache import SMSCodeManager

logger = logging.getLogger('sms')


# ══════════════════════════════════════════════════════════════
# 短信模板配置
# ══════════════════════════════════════════════════════════════

class SMSTemplate:
    """短信模板配置"""

    # 场景 -> 模板ID 映射（需要在阿里云控制台配置）
    TEMPLATES = {
        'login': 'SMS_505135275',  # 登录验证码
        'register': 'SMS_123456790',  # 注册验证码
        'reset_password': 'SMS_123456791',  # 重置密码
        'bind_phone': 'SMS_123456792',  # 绑定手机
        'change_phone': 'SMS_123456793',  # 更换手机
        'order_notify': 'SMS_123456794',  # 订单通知
        'merchant_verify': 'SMS_123456795',  # 商家入驻验证
        'change_bank': 'SMS_506450089',
        'order_dispatch': 'SMS_506430128',
        'order_transfer': 'SMS_506380133',
        'order_no_staff': 'SMS_506380134',
    }

    # 场景描述（用于日志）
    SCENE_DESC = {
        'login': '登录',
        'register': '注册',
        'reset_password': '重置密码',
        'bind_phone': '绑定手机',
        'change_phone': '更换手机',
        'order_notify': '订单通知',
        'merchant_verify': '商家入驻',
        'change_bank': '修改提现银行卡',
        'order_dispatch': '派单通知员工',
        'order_transfer': '转单通知',
        'order_no_staff': '需要人工派单',
    }

    @classmethod
    def get_template_id(cls, scene: str) -> str:
        """获取模板ID"""
        return cls.TEMPLATES.get(scene, cls.TEMPLATES['login'])

    @classmethod
    def get_scene_desc(cls, scene: str) -> str:
        """获取场景描述"""
        return cls.SCENE_DESC.get(scene, '验证')


# ══════════════════════════════════════════════════════════════
# 阿里云短信客户端
# ══════════════════════════════════════════════════════════════

class AliyunSMSClient:
    """阿里云短信客户端（单例）"""

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> Client:
        if self._client is None:
            config = open_api_models.Config(
                access_key_id=settings.ALIYUN_ACCESS_KEY_ID,
                access_key_secret=settings.ALIYUN_ACCESS_KEY_SECRET,
                endpoint='dysmsapi.aliyuncs.com'
            )
            self._client = Client(config)
        return self._client


# ══════════════════════════════════════════════════════════════
# 短信服务
# ══════════════════════════════════════════════════════════════

class SMSService:
    """短信服务"""

    def __init__(self):
        self.code_manager = SMSCodeManager()
        self.client = AliyunSMSClient().client
        self.sign_name = getattr(settings, 'ALIYUN_SMS_SIGN_NAME', '')
        self.debug_mode = getattr(settings, 'SMS_DEBUG_MODE', False)

    def send_verification_code(
            self,
            phone: str,
            scene: str = 'login'
    ) -> tuple[bool, str, str | None]:
        """
        发送验证码

        Args:
            phone: 手机号
            scene: 场景（login/register/reset_password等）

        Returns:
            (是否成功, 消息, 验证码-仅调试模式返回)
        """
        # 检查是否可以发送
        can_send, reason = self.code_manager.can_send(phone)
        if not can_send:
            return False, reason, None

        # 生成验证码
        code = self.code_manager.generate_code()

        # 调试模式：不真正发送
        if self.debug_mode:
            self.code_manager.save_code(phone, code, scene)
            logger.info(f"[DEBUG] 短信验证码 - 手机: {phone}, 场景: {scene}, 验证码: {code}")
            return True, "验证码已发送（调试模式）", code

        # 真正发送短信
        try:
            template_id = SMSTemplate.get_template_id(scene)

            request = sms_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=self.sign_name,
                template_code=template_id,
                template_param=f'{{"code":"{code}"}}'
            )

            runtime = util_models.RuntimeOptions()
            response = self.client.send_sms_with_options(request, runtime)

            if response.body.code == 'OK':
                # 发送成功，保存验证码
                self.code_manager.save_code(phone, code, scene)
                logger.info(f"短信发送成功 - 手机: {phone}, 场景: {scene}")
                return True, "验证码已发送", None
            else:
                error_msg = response.body.message or '发送失败'
                logger.error(f"短信发送失败 - 手机: {phone}, 错误: {error_msg}")
                return False, f"发送失败: {error_msg}", None

        except Exception as e:
            logger.exception(f"短信发送异常 - 手机: {phone}, 错误: {str(e)}")
            return False, "短信服务异常，请稍后重试", None

    def verify_code(self, phone: str, code: str, scene: str = 'login') -> tuple[bool, str]:
        """
        验证验证码

        Returns:
            (是否正确, 错误信息)
        """
        return self.code_manager.verify_code(phone, code, scene)

    def send_notification(
            self,
            phone: str,
            template_code: str,
            template_param: dict
    ) -> tuple[bool, str]:
        """
        发送通知短信（非验证码类）

        Args:
            phone: 手机号
            template_code: 模板ID
            template_param: 模板参数

        Returns:
            (是否成功, 消息)
        """
        import json

        if self.debug_mode:
            logger.info(f"[DEBUG] 通知短信 - 手机: {phone}, 模板: {template_code}, 参数: {template_param}")
            return True, "发送成功（调试模式）"

        try:
            request = sms_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=self.sign_name,
                template_code=template_code,
                template_param=json.dumps(template_param, ensure_ascii=False)
            )

            runtime = util_models.RuntimeOptions()
            response = self.client.send_sms_with_options(request, runtime)

            if response.body.code == 'OK':
                logger.info(f"通知短信发送成功 - 手机: {phone}")
                return True, "发送成功"
            else:
                error_msg = response.body.message or '发送失败'
                logger.error(f"通知短信发送失败 - 手机: {phone}, 错误: {error_msg}")
                return False, error_msg

        except Exception as e:
            logger.exception(f"通知短信发送异常 - 手机: {phone}")
            return False, "发送异常"


# ══════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════

_sms_service = None


def get_sms_service() -> SMSService:
    """获取短信服务单例"""
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service


def send_sms_code(phone: str, scene: str = 'login') -> tuple[bool, str, str | None]:
    """发送验证码的快捷方法"""
    return get_sms_service().send_verification_code(phone, scene)


def verify_sms_code(phone: str, code: str, scene: str = 'login') -> tuple[bool, str]:
    """验证验证码的快捷方法"""
    return get_sms_service().verify_code(phone, code, scene)