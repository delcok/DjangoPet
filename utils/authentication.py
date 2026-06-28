# -*- coding: utf-8 -*-
"""
JWT 认证模块
"""
import logging

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.translation import gettext_lazy as _

from managers.models import Manager
from merchants.models import Merchant, MerchantSubAccount
from user.models import User
from staffs.models import Staff

logger = logging.getLogger(__name__)


# ============================================================
# Token 类型常量
# ============================================================
class TokenType:
    USER = 'user'
    MANAGER = 'manager'
    MERCHANT = 'merchant'
    MERCHANT_SUB = 'merchant_sub'
    STAFF = 'staff'


# ✅ 修复 #1 + #14:
# 允许通过 JWT 认证的商家状态白名单。
# - active     → 正常营业,完全放行
# - suspended  → 暂停中,允许登录查看通知/申诉,业务接口靠 IsActiveMerchant 拦
# 其他状态(pending/rejected/closed)一律拒绝认证。
MERCHANT_AUTH_ALLOWED_STATUSES = {'active', 'suspended', 'draft', 'pending', 'rejected'}


# ============================================================
# Token 生成函数
# ============================================================
def generate_jwt_tokens(user, user_type: str) -> dict:
    refresh = RefreshToken.for_user(user)

    refresh['type'] = user_type
    refresh['user_id'] = user.id

    if hasattr(user, 'token_version'):
        refresh['token_version'] = user.token_version

    if user_type == TokenType.MERCHANT_SUB:
        refresh['merchant_id'] = user.merchant_id

    if user_type == TokenType.STAFF:
        refresh['merchant_id'] = user.merchant_id
        refresh['staff_name'] = user.name

    if user_type == TokenType.MANAGER:
        refresh['role'] = user.role.code if user.role else None
        refresh['is_superuser'] = user.is_superuser
        refresh['permissions'] = user.get_permissions()

    access = refresh.access_token
    access['type'] = user_type
    access['user_id'] = user.id

    if hasattr(user, 'token_version'):
        access['token_version'] = user.token_version

    if user_type == TokenType.MERCHANT_SUB:
        access['merchant_id'] = user.merchant_id

    if user_type == TokenType.STAFF:
        access['merchant_id'] = user.merchant_id
        access['staff_name'] = user.name

    if user_type == TokenType.MANAGER:
        access['role'] = user.role.code if user.role else None
        access['is_superuser'] = user.is_superuser

    return {
        'access_token': str(access),
        'refresh_token': str(refresh),
        'token_type': 'Bearer',
        'expires_in': int(access.lifetime.total_seconds()),
    }


def generate_user_tokens(user: User) -> dict:
    return generate_jwt_tokens(user, TokenType.USER)


def generate_manager_tokens(manager: Manager) -> dict:
    return generate_jwt_tokens(manager, TokenType.MANAGER)


def generate_merchant_tokens(merchant: Merchant) -> dict:
    return generate_jwt_tokens(merchant, TokenType.MERCHANT)


def generate_merchant_sub_tokens(sub_account: MerchantSubAccount) -> dict:
    return generate_jwt_tokens(sub_account, TokenType.MERCHANT_SUB)


def generate_staff_tokens(staff: Staff) -> dict:
    return generate_jwt_tokens(staff, TokenType.STAFF)


# ============================================================
# 认证基类
# ============================================================
class BaseAuthentication(JWTAuthentication):
    expected_type: str = None

    def get_user(self, validated_token):
        try:
            user_id = validated_token['user_id']
            token_type = validated_token['type']
        except KeyError:
            raise InvalidToken(_('Token 中缺少必要的用户标识'))

        if token_type != self.expected_type:
            raise InvalidToken(_('Token 类型不匹配'))

        return self._get_user_instance(user_id, validated_token)

    def _get_user_instance(self, user_id, validated_token):
        raise NotImplementedError

    def _check_token_version(self, user, validated_token):
        if hasattr(user, 'token_version'):
            token_version = validated_token.get('token_version')
            if token_version is not None and token_version != user.token_version:
                raise InvalidToken(_('Token 已失效,请重新登录'))


# ============================================================
# 普通用户认证
# ============================================================
class UserAuthentication(BaseAuthentication):
    expected_type = TokenType.USER

    def _get_user_instance(self, user_id, validated_token):
        try:
            user = User.objects.get(id=user_id, is_active=True)
            if user.is_banned:
                raise InvalidToken(_('用户已被封禁'))
            self._check_token_version(user, validated_token)
            return user
        except User.DoesNotExist:
            raise InvalidToken(_('用户不存在或已注销'))


class OptionalUserAuthentication(UserAuthentication):
    """
    可选用户认证:有 token 就认证,没有就跳过。
    ✅ 修复 #5: 只吞 token / 认证相关异常,
    DB/配置错误等保持上抛,避免静默降级成"匿名访问"
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_param = request.query_params.get('token', '')

        if not auth_header and not token_param:
            return None

        try:
            return super().authenticate(request)
        except (InvalidToken, TokenError, AuthenticationFailed) as e:
            logger.debug(f"Optional auth failed: {e}")
            return None


# ============================================================
# 管理后台认证
# ============================================================
class ManagerAuthentication(BaseAuthentication):
    expected_type = TokenType.MANAGER

    def _get_user_instance(self, user_id, validated_token):
        try:
            manager = Manager.objects.select_related('role').get(id=user_id, status='active')
            self._check_token_version(manager, validated_token)
            return manager
        except Manager.DoesNotExist:
            raise InvalidToken(_('管理员不存在或已禁用'))


# ============================================================
# 商家端认证(B端)
# ============================================================
def _check_merchant_status(merchant_status: str):
    """
    ✅ 修复 #1: 商家状态白名单校验
    把 status 检查统一封装,所有认证类共用。
    旧代码只拦 'closed',pending/rejected 商家也能通过认证 → 越权风险。
    """
    if merchant_status not in MERCHANT_AUTH_ALLOWED_STATUSES:
        msg = {
            'pending': '账户待审核',
            'rejected': '账户审核被拒绝',
            'closed': '账户已关闭',
        }.get(merchant_status, '账户状态异常')
        raise InvalidToken(_(msg))


class MerchantAuthentication(BaseAuthentication):
    """商家主账号认证"""

    expected_type = TokenType.MERCHANT

    def _get_user_instance(self, user_id, validated_token):
        try:
            merchant = Merchant.objects.get(id=user_id)
            _check_merchant_status(merchant.status)  # ✅
            self._check_token_version(merchant, validated_token)
            return merchant
        except Merchant.DoesNotExist:
            raise InvalidToken(_('商家不存在'))


class MerchantSubAccountAuthentication(BaseAuthentication):
    """商家子账号认证"""

    expected_type = TokenType.MERCHANT_SUB

    def _get_user_instance(self, user_id, validated_token):
        try:
            sub_account = MerchantSubAccount.objects.select_related('merchant').get(
                id=user_id,
                is_active=True
            )
            # ✅ 修复 #14: 子账号同步走商家状态白名单
            _check_merchant_status(sub_account.merchant.status)
            self._check_token_version(sub_account, validated_token)
            return sub_account
        except MerchantSubAccount.DoesNotExist:
            raise InvalidToken(_('子账号不存在或已禁用'))


class MerchantOrSubAuthentication(JWTAuthentication):
    """商家主账号或子账号都能通过"""

    def get_user(self, validated_token):
        try:
            user_id = validated_token['user_id']
            token_type = validated_token['type']
        except KeyError:
            raise InvalidToken(_('Token 中缺少必要的用户标识'))

        if token_type == TokenType.MERCHANT:
            try:
                merchant = Merchant.objects.get(id=user_id)
                _check_merchant_status(merchant.status)  # ✅
                token_version = validated_token.get('token_version')
                if token_version is not None and hasattr(merchant, 'token_version'):
                    if token_version != merchant.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                merchant._is_main_account = True
                return merchant
            except Merchant.DoesNotExist:
                raise InvalidToken(_('商家不存在'))

        elif token_type == TokenType.MERCHANT_SUB:
            try:
                sub = MerchantSubAccount.objects.select_related('merchant').get(
                    id=user_id,
                    is_active=True
                )
                _check_merchant_status(sub.merchant.status)  # ✅
                token_version = validated_token.get('token_version')
                if token_version is not None and hasattr(sub, 'token_version'):
                    if token_version != sub.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                sub._is_main_account = False
                sub._merchant = sub.merchant
                return sub
            except MerchantSubAccount.DoesNotExist:
                raise InvalidToken(_('子账号不存在或已禁用'))

        raise InvalidToken(_('无效的商家 Token'))


# ============================================================
# 员工端认证
# ============================================================
class StaffAuthentication(BaseAuthentication):
    expected_type = TokenType.STAFF

    def _get_user_instance(self, user_id, validated_token):
        try:
            staff = Staff.objects.select_related('merchant').get(
                id=user_id,
                status='active'
            )
            _check_merchant_status(staff.merchant.status)  # ✅
            self._check_token_version(staff, validated_token)
            staff._merchant = staff.merchant
            return staff
        except Staff.DoesNotExist:
            raise InvalidToken(_('员工账号不存在或已禁用'))


class StaffOrMerchantAuthentication(JWTAuthentication):
    """员工 / 商家主账号 / 子账号都能通过"""

    def get_user(self, validated_token):
        try:
            user_id = validated_token['user_id']
            token_type = validated_token['type']
        except KeyError:
            raise InvalidToken(_('Token 中缺少必要的用户标识'))

        if token_type == TokenType.STAFF:
            try:
                staff = Staff.objects.select_related('merchant').get(
                    id=user_id, status='active'
                )
                _check_merchant_status(staff.merchant.status)  # ✅
                token_version = validated_token.get('token_version')
                if token_version is not None and hasattr(staff, 'token_version'):
                    if token_version != staff.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                staff._is_staff = True
                staff._is_main_account = False
                staff._merchant = staff.merchant
                return staff
            except Staff.DoesNotExist:
                raise InvalidToken(_('员工账号不存在或已禁用'))

        elif token_type == TokenType.MERCHANT:
            try:
                merchant = Merchant.objects.get(id=user_id)
                _check_merchant_status(merchant.status)  # ✅
                token_version = validated_token.get('token_version')
                if token_version is not None and hasattr(merchant, 'token_version'):
                    if token_version != merchant.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                merchant._is_staff = False
                merchant._is_main_account = True
                return merchant
            except Merchant.DoesNotExist:
                raise InvalidToken(_('商家不存在'))

        elif token_type == TokenType.MERCHANT_SUB:
            try:
                sub = MerchantSubAccount.objects.select_related('merchant').get(
                    id=user_id, is_active=True
                )
                _check_merchant_status(sub.merchant.status)  # ✅
                token_version = validated_token.get('token_version')
                if token_version is not None and hasattr(sub, 'token_version'):
                    if token_version != sub.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                sub._is_staff = False
                sub._is_main_account = False
                sub._merchant = sub.merchant
                return sub
            except MerchantSubAccount.DoesNotExist:
                raise InvalidToken(_('子账号不存在或已禁用'))

        raise InvalidToken(_('无效的 Token 类型'))


class OptionalStaffAuthentication(StaffAuthentication):
    """✅ 修复 #5"""

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_param = request.query_params.get('token', '')

        if not auth_header and not token_param:
            return None

        try:
            return super().authenticate(request)
        except (InvalidToken, TokenError, AuthenticationFailed) as e:
            logger.debug(f"Optional staff auth failed: {e}")
            return None


# ============================================================
# 多角色通用认证
# ============================================================
class MultiRoleAuthentication(JWTAuthentication):
    """支持所有角色,根据 type 字段自动分流"""

    def get_user(self, validated_token):
        try:
            user_id = validated_token['user_id']
            token_type = validated_token['type']
        except KeyError:
            raise InvalidToken(_('Token 中缺少必要的用户标识'))

        token_version = validated_token.get('token_version')

        if token_type == TokenType.USER:
            try:
                user = User.objects.get(id=user_id, is_active=True)
                if user.is_banned:
                    raise InvalidToken(_('用户已被封禁'))
                if token_version is not None and hasattr(user, 'token_version'):
                    if token_version != user.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                user._user_type = 'user'
                return user
            except User.DoesNotExist:
                raise InvalidToken(_('用户不存在或已注销'))

        elif token_type == TokenType.MANAGER:
            try:
                manager = Manager.objects.select_related('role').get(id=user_id, status='active')
                if token_version is not None and hasattr(manager, 'token_version'):
                    if token_version != manager.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                manager._user_type = 'manager'
                return manager
            except Manager.DoesNotExist:
                raise InvalidToken(_('管理员不存在或已禁用'))

        elif token_type == TokenType.MERCHANT:
            try:
                merchant = Merchant.objects.get(id=user_id)
                _check_merchant_status(merchant.status)  # ✅
                if token_version is not None and hasattr(merchant, 'token_version'):
                    if token_version != merchant.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                merchant._user_type = 'merchant'
                merchant._is_main_account = True
                return merchant
            except Merchant.DoesNotExist:
                raise InvalidToken(_('商家不存在'))

        elif token_type == TokenType.MERCHANT_SUB:
            try:
                sub = MerchantSubAccount.objects.select_related('merchant').get(
                    id=user_id, is_active=True
                )
                _check_merchant_status(sub.merchant.status)  # ✅
                if token_version is not None and hasattr(sub, 'token_version'):
                    if token_version != sub.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                sub._user_type = 'merchant_sub'
                sub._is_main_account = False
                sub._merchant = sub.merchant
                return sub
            except MerchantSubAccount.DoesNotExist:
                raise InvalidToken(_('子账号不存在或已禁用'))

        elif token_type == TokenType.STAFF:
            try:
                staff = Staff.objects.select_related('merchant').get(
                    id=user_id, status='active'
                )
                _check_merchant_status(staff.merchant.status)  # ✅
                if token_version is not None and hasattr(staff, 'token_version'):
                    if token_version != staff.token_version:
                        raise InvalidToken(_('Token 已失效,请重新登录'))
                staff._user_type = 'staff'
                staff._merchant = staff.merchant
                return staff
            except Staff.DoesNotExist:
                raise InvalidToken(_('员工账号不存在或已禁用'))

        raise InvalidToken(_('无效的 Token 类型'))