# -*- coding: utf-8 -*-
import secrets
from datetime import datetime

from django.db import transaction, IntegrityError
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from wechatpy.crypto import WeChatWxaCrypto

from user.models import User, UserAuthProvider, UserLoginLog, InviteReward, UserProfileAudit
from user.serializers import (
    UserSerializer,
    AdminUserListSerializer,
    AdminUserDetailSerializer,
    AdminUserUpdateSerializer,
    AdminBanUserSerializer,
    AdminToggleActiveSerializer,
    AdminSetVipSerializer,
    AdminCancelVipSerializer,
    AdminVerifyUserSerializer,
    AdminChangeLevelSerializer,
    AdminResetPasswordSerializer, SendSmsCodeSerializer, SmsLoginSerializer,
)
from user.filters import UserFilter, UserLoginLogFilter
from user.paginations import AdminUserPagination, LoginLogPagination, StandardPagination

from utils.authentication import generate_jwt_tokens, UserAuthentication, ManagerAuthentication
from utils.permission import IsManager, IsSuperAdmin
from utils.fetch_number import fetch_phone_number
from utils.account_factory import register_user
from utils.send_sms import verify_sms_code, send_sms_code
from utils.wechat_client import get_user_mini_client
from wallet.models import WalletTransaction, UserWallet


# ═══════════════════════════════════════════════════════════════
# 用户端接口
# ═══════════════════════════════════════════════════════════════

def _parse_wx_gender(v):
    """
    微信返回: 0=未知 / 1=男 / 2=女
    注: 2021-04 后 getUserProfile 的 gender 基本都是 0（隐私政策收紧）
    """
    return {1: 'M', 2: 'F'}.get(v, 'U')

def _submit_profile_audit(user, field, new_value):
    """
    提交一条资料审核（头像/昵称）。
    已存在该字段的 pending 记录则覆盖 new_value，保证每字段仅一条待审核。
    返回 (audit, changed)；changed=False 表示值跟线上一致、无需审核。
    """
    new_value = (new_value or '').strip()
    current = getattr(user, field) or ''
    if new_value == current:
        return None, False

    with transaction.atomic():
        # 锁住该用户行，串行化「同一用户」的并发提交
        # MySQL 不支持条件唯一索引，靠这把行锁防止双击产生两条 pending
        User.objects.select_for_update().get(pk=user.pk)
        audit, _ = UserProfileAudit.objects.update_or_create(
            user=user, field=field, status=UserProfileAudit.Status.PENDING,
            defaults={'old_value': current, 'new_value': new_value},
        )
    return audit, True


def _build_login_response(user, openid=None):
    """统一的登录返回（generate_jwt_tokens 返回的是 dict，不是 tuple）"""
    tokens = generate_jwt_tokens(user, 'user')
    data = {
        'access': tokens['access_token'],
        'refresh': tokens['refresh_token'],
        'token_type': tokens.get('token_type', 'Bearer'),
        'expires_in': tokens.get('expires_in'),
        'user_info': UserSerializer(user).data,
    }
    if openid:
        data['openid'] = openid
    return data


def _get_client_ip(request):
    """优先取反代透传的真实 IP"""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _platform_to_channel(platform):
    """登录平台 → 注册渠道 register_channel"""
    return {'ios': 'ios', 'android': 'android', 'h5': 'h5', 'web': 'h5'}.get(platform, 'ios')


def _record_login_log(request, user, *, login_method, platform,
                      is_success=True, fail_reason='', device_id=''):
    """写登录日志（埋点 + 风控），失败不影响主流程"""
    try:
        UserLoginLog.objects.create(
            user=user,
            login_method=login_method,
            platform=platform,
            device_id=device_id or '',
            ip_address=_get_client_ip(request),
            location='',  # 如需 IP 归属地可在此补充
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
            is_success=is_success,
            fail_reason=fail_reason or '',
        )
    except Exception:
        import traceback
        traceback.print_exc()

@api_view(['POST'])
def wechat_login(request):
    """微信小程序登录"""
    code = request.data.get('code')
    phone_code = request.data.get('phone_code')
    iv = request.data.get('iv')
    encrypted_data = request.data.get('encryptedData')
    openid = request.data.get('openid')
    invite_code = (request.data.get('invite_code') or '').strip()

    # 已有 openid → 尝试快速登录
    if openid:
        auth_provider = UserAuthProvider.objects.filter(
            provider='wx_mini', provider_uid=openid
        ).select_related('user').first()

        if auth_provider:
            user = auth_provider.user
            if user.is_active and not user.is_banned:
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                return Response(_build_login_response(user, openid), status=status.HTTP_200_OK)
            elif user.is_banned:
                return Response({'error': f'您已被封禁: {user.ban_reason}'},
                                status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': '您已被禁用，请联系客服!'},
                                status=status.HTTP_400_BAD_REQUEST)

    if not code:
        return Response({'error': 'Missing code'}, status=status.HTTP_400_BAD_REQUEST)

    wechat_client = get_user_mini_client()
    app_id = wechat_client.appid

    try:
        result = wechat_client.wxa.code_to_session(code)
        session_key = result.get('session_key')
        openid = result.get('openid')
        unionid = result.get('unionid', '')
        if not openid:
            return Response({'error': 'Failed to get openid from WeChat'},
                            status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'error': f'Failed to get session from WeChat: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST)

    auth_provider = UserAuthProvider.objects.filter(
        provider='wx_mini', provider_uid=openid
    ).select_related('user').first()

    if auth_provider:
        user = auth_provider.user
        if user.is_active and not user.is_banned:
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
            if unionid and not auth_provider.union_id:
                auth_provider.union_id = unionid
                auth_provider.save(update_fields=['union_id', 'updated_at'])
            return Response(_build_login_response(user, openid), status=status.HTTP_200_OK)
        elif user.is_banned:
            return Response({'error': f'您已被封禁: {user.ban_reason}'},
                            status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': '您已被禁用，请联系客服!'},
                            status=status.HTTP_400_BAD_REQUEST)

    if not phone_code:
        return Response({'error': 'User does not exist and phone_code is required to register'},
                        status=status.HTTP_400_BAD_REQUEST)

    phone_number = fetch_phone_number(phone_code)
    if not phone_number:
        return Response({'error': 'Failed to fetch phone number'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        user_info = {}
        if encrypted_data and iv:
            try:
                crypto = WeChatWxaCrypto(session_key, iv, app_id)
                user_info = crypto.decrypt_message(encrypted_data)
            except Exception:
                user_info = {}
    except Exception as e:
        return Response({'error': f'Failed to decrypt user information: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST)

    existing_user = None
    if unionid:
        existing_provider = UserAuthProvider.objects.filter(union_id=unionid).select_related('user').first()
        if existing_provider:
            existing_user = existing_provider.user
    if not existing_user:
        existing_user = User.objects.filter(phone=phone_number).first()

    is_new_register = False

    if existing_user:
        # 老用户绑新渠道，不发邀请奖励
        user = existing_user
        UserAuthProvider.objects.create(
            user=user, provider='wx_mini', provider_uid=openid,
            union_id=unionid, extra_data=user_info,
        )
    else:
        username = f"用户{phone_number[-4:]}"
        with transaction.atomic():
            user = register_user(
                phone=phone_number,
                username=username,
                avatar='https://cdn.yimengzhiyuan.com/avatar/av-gen.png',
                gender=_parse_wx_gender(user_info.get('gender')),
                register_channel='wx_mini',
            )
            UserAuthProvider.objects.create(
                user=user, provider='wx_mini', provider_uid=openid,
                union_id=unionid, extra_data=user_info,
            )
        is_new_register = True

    # 邀请奖励放在主事务【之外】发，失败不影响注册
    if is_new_register and invite_code:
        _process_invite_reward(user, invite_code)

    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])
    return Response(_build_login_response(user, openid), status=status.HTTP_200_OK)


@api_view(['PATCH'])
@authentication_classes([UserAuthentication])
def update_user_info(request):
    """
    更新用户信息（用户端）

    ★ 头像(avatar) / 昵称(username) 改为「先提交审核，通过后才生效」：
      这两个字段不直接写库，而是写入 UserProfileAudit 等待人工审核；
      其余字段(bio/gender/birth_date/email/隐私)维持即时生效。
    """
    try:
        user = request.user

        username      = request.data.get('username')
        avatar        = request.data.get('avatar') or request.data.get('avatar_url')
        bio           = request.data.get('bio')
        gender        = request.data.get('gender')
        birth_date    = request.data.get('birth_date')
        email         = request.data.get('email')
        is_public     = request.data.get('is_public')
        allow_message = request.data.get('allow_message')

        updated_fields = []   # 即时生效
        pending_fields = []   # ★ 进审核队列

        # ── 昵称（★ 进审核，不直接写库）──
        if username is not None:
            username = username.strip()
            if len(username) < 2 or len(username) > 30:
                return Response({'error': '用户名长度为 2-30 个字符'},
                                status=status.HTTP_400_BAD_REQUEST)
            _, changed = _submit_profile_audit(user, 'username', username)
            if changed:
                pending_fields.append('username')

        # ── 头像（★ 进审核，不直接写库）──
        if avatar:
            avatar = avatar.strip()
            _, changed = _submit_profile_audit(user, 'avatar', avatar)
            if changed:
                pending_fields.append('avatar')

        # ── 简介（即时生效；如也要审核，照昵称的写法走 _submit_profile_audit）──
        if bio is not None:
            bio = bio.strip()
            if len(bio) > 200:
                return Response({'error': '简介不能超过 200 个字符'},
                                status=status.HTTP_400_BAD_REQUEST)
            user.bio = bio
            updated_fields.append('bio')

        # ── 性别 ──
        if gender is not None:
            GENDER_MAP = {
                'M': 'M', 'F': 'F', 'O': 'O', 'U': 'U',
                'male': 'M', 'female': 'F', 'other': 'O', '': 'U',
            }
            key = gender.strip() if isinstance(gender, str) else ''
            db_gender = GENDER_MAP.get(key) or GENDER_MAP.get(key.lower())
            if db_gender is None:
                return Response({'error': f'性别值不合法: {gender}'},
                                status=status.HTTP_400_BAD_REQUEST)
            user.gender = db_gender
            updated_fields.append('gender')

        # ── 生日 ──
        if birth_date is not None:
            if birth_date:
                try:
                    datetime.strptime(birth_date, '%Y-%m-%d')
                    user.birth_date = birth_date
                except ValueError:
                    return Response({'error': '生日格式不正确,应为 YYYY-MM-DD'},
                                    status=status.HTTP_400_BAD_REQUEST)
            else:
                user.birth_date = None
            updated_fields.append('birth_date')

        # ── 邮箱 ──
        if email is not None:
            email = (email or '').strip() if isinstance(email, str) else ''
            if email:
                from django.core.validators import EmailValidator
                from django.core.exceptions import ValidationError as DjangoValidationError
                try:
                    EmailValidator()(email)
                except DjangoValidationError:
                    return Response({'error': '邮箱格式不正确'},
                                    status=status.HTTP_400_BAD_REQUEST)
                user.email = email
            else:
                user.email = None
            updated_fields.append('email')

        # ── 隐私 ──
        if is_public is not None:
            user.is_public = bool(is_public)
            updated_fields.append('is_public')
        if allow_message is not None:
            user.allow_message = bool(allow_message)
            updated_fields.append('allow_message')

        if not updated_fields and not pending_fields:
            return Response({'error': '没有提供需要更新的字段'},
                            status=status.HTTP_400_BAD_REQUEST)

        if updated_fields:
            user.save(update_fields=updated_fields + ['updated_at'])

        return Response({
            'message': '已提交，等待审核' if pending_fields else '更新成功',
            'user': UserSerializer(user).data,   # 含 pending_profile
            'updated_fields': updated_fields,     # 即时生效的
            'pending_fields': pending_fields,     # ★ 待审核的
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': f'更新失败: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([UserAuthentication])
def get_user_info(request):
    """获取当前用户信息"""
    user = request.user
    user.update_last_active()
    return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

@api_view(['POST'])
def send_sms_code_api(request):
    """
    POST /user/sms/send/   发送短信验证码（App 登录/注册）
    body: { phone, scene? }   scene 默认 login
    """
    serializer = SendSmsCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    phone = serializer.validated_data['phone']
    scene = serializer.validated_data['scene']

    ok, msg, debug_code = send_sms_code(phone, scene)
    if not ok:
        # can_send 限流 / 发送失败都会走这里
        return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

    resp = {'message': msg}
    if debug_code:           # 仅 SMS_DEBUG_MODE=True 返回，线上为 None
        resp['debug_code'] = debug_code
    return Response(resp, status=status.HTTP_200_OK)


@api_view(['POST'])
def sms_login(request):
    """
    POST /user/sms-login/   短信验证码登录/注册（手机号不存在则自动注册）
    body: { phone, code, platform?, invite_code? }
    """
    serializer = SmsLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    phone = data['phone']
    code = data['code']
    scene = data['scene']
    platform = data['platform']
    invite_code = (data.get('invite_code') or '').strip()

    # 1. 校验验证码
    ok, msg = verify_sms_code(phone, code, scene=scene)
    if not ok:
        return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

    # 2. 查找用户
    user = User.objects.filter(phone=phone).first()
    is_new_register = False

    if user:
        # ---- 老用户：状态校验 ----
        if user.is_banned:
            _record_login_log(request, user, login_method='sms', platform=platform,
                              is_success=False, fail_reason='账号已封禁')
            return Response({'error': f'您已被封禁: {user.ban_reason}'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            _record_login_log(request, user, login_method='sms', platform=platform,
                              is_success=False, fail_reason='账号已禁用')
            return Response({'error': '您已被禁用，请联系客服!'},
                            status=status.HTTP_400_BAD_REQUEST)
    else:
        # ---- 新用户：自动注册（register_user 内部会发 100 金币注册奖励）----
        try:
            with transaction.atomic():
                user = register_user(
                    phone=phone,
                    username=f"用户{phone[-4:]}",
                    avatar='https://cdn.yimengzhiyuan.com/avatar/av-gen.png',
                    register_channel=_platform_to_channel(platform),
                )
            is_new_register = True
        except IntegrityError:
            # 并发下同一手机号已被注册，回查复用
            user = User.objects.filter(phone=phone).first()
            if not user:
                raise

    # 3. 邀请奖励（仅新用户，主事务之外，失败不阻断登录）
    if is_new_register and invite_code:
        _process_invite_reward(user, invite_code)

    # 4. 更新最后登录时间
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])

    # 5. 登录日志
    _record_login_log(request, user, login_method='sms', platform=platform, is_success=True)

    # 6. 统一登录返回
    resp = _build_login_response(user)
    resp['is_new_user'] = is_new_register
    return Response(resp, status=status.HTTP_200_OK)

# ═══════════════════════════════════════════════════════════════
# 管理员端 - 用户列表 / 详情
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_user_list(request):
    """管理员 - 用户列表（筛选+分页+排序，含钱包概要）"""
    queryset = (
        User.objects.all()
        .select_related('invited_by', 'wallet')
    )

    filtered = UserFilter(request.GET, queryset=queryset).qs
    paginator = AdminUserPagination()
    page = paginator.paginate_queryset(filtered, request)
    serializer = AdminUserListSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_user_detail(request, user_id):
    """管理员 - 用户详情（含钱包、设备、绑定渠道、最近登录）"""
    user = (
        User.objects
        .select_related('invited_by')
        .prefetch_related('auth_providers', 'devices', 'login_logs')
        .filter(id=user_id)
        .first()
    )
    if not user:
        return Response({'error': '用户不存在'}, status=status.HTTP_404_NOT_FOUND)
    return Response(AdminUserDetailSerializer(user).data)


@api_view(['PATCH'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_update_user(request, user_id):
    """管理员 - 编辑用户基本资料"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    return Response({
        'message': '更新成功',
        'user': AdminUserDetailSerializer(user).data
    })


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 状态管理（高危 → 仅超管）
# ═══════════════════════════════════════════════════════════════

@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsSuperAdmin])
def admin_ban_user(request, user_id):
    """管理员 - 封禁/解封用户（仅超管）"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminBanUserSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    user.is_banned = data['is_banned']
    user.ban_reason = data.get('ban_reason', '') if data['is_banned'] else ''
    user.save(update_fields=['is_banned', 'ban_reason', 'updated_at'])

    return Response({
        'message': '封禁成功' if data['is_banned'] else '解封成功',
        'user_id': user.id,
        'is_banned': user.is_banned,
        'ban_reason': user.ban_reason,
        'operator_id': request.user.id,
    })


@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsSuperAdmin])
def admin_toggle_active(request, user_id):
    """管理员 - 启用/禁用用户（仅超管）"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminToggleActiveSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user.is_active = serializer.validated_data['is_active']
    user.save(update_fields=['is_active', 'updated_at'])

    return Response({
        'message': '启用成功' if user.is_active else '禁用成功',
        'user_id': user.id,
        'is_active': user.is_active,
        'operator_id': request.user.id,
    })


# ═══════════════════════════════════════════════════════════════
# 管理员端 - VIP 管理
# ═══════════════════════════════════════════════════════════════

@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_set_vip(request, user_id):
    """管理员 - 开通/续费/升级 VIP"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminSetVipSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    now = timezone.now()

    if data.get('vip_expired_at'):
        new_expired_at = data['vip_expired_at']
    else:
        days = data['duration_days']
        if data.get('extend') and user.is_vip and user.vip_expired_at and user.vip_expired_at > now:
            base = user.vip_expired_at
        else:
            base = now
        new_expired_at = base + timezone.timedelta(days=days)

    user.is_vip = True
    user.vip_level = data['vip_level']
    user.vip_expired_at = new_expired_at
    user.save(update_fields=['is_vip', 'vip_level', 'vip_expired_at', 'updated_at'])

    return Response({
        'message': 'VIP 设置成功',
        'user_id': user.id,
        'is_vip': user.is_vip,
        'vip_level': user.vip_level,
        'vip_expired_at': user.vip_expired_at,
    })


@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_cancel_vip(request, user_id):
    """管理员 - 取消 VIP"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminCancelVipSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user.is_vip = False
    user.vip_level = 0
    user.vip_expired_at = None
    user.save(update_fields=['is_vip', 'vip_level', 'vip_expired_at', 'updated_at'])

    return Response({'message': 'VIP 已取消', 'user_id': user.id})


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 实名认证
# ═══════════════════════════════════════════════════════════════

@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_verify_user(request, user_id):
    """管理员 - 实名认证 / 取消认证"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminVerifyUserSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    if data['is_verified']:
        user.is_verified = True
        user.verification_type = data['verification_type']
        user.verified_at = timezone.now()
    else:
        user.is_verified = False
        user.verification_type = ''
        user.verified_at = None

    user.save(update_fields=['is_verified', 'verification_type', 'verified_at', 'updated_at'])

    return Response({
        'message': '认证成功' if user.is_verified else '已取消认证',
        'user_id': user.id,
        'is_verified': user.is_verified,
        'verification_type': user.verification_type,
        'verified_at': user.verified_at,
    })


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 等级 / 经验值
# ═══════════════════════════════════════════════════════════════

@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_change_level(request, user_id):
    """管理员 - 调整用户等级 / 经验值"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminChangeLevelSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    updated_fields = []

    if 'level' in data:
        user.level = data['level']
        updated_fields.append('level')

    if 'exp' in data:
        user.exp = data['exp']
        updated_fields.append('exp')
    elif 'exp_delta' in data:
        user.exp = max(0, user.exp + data['exp_delta'])
        updated_fields.append('exp')

    if not updated_fields:
        return Response({'error': '无字段变更'}, status=status.HTTP_400_BAD_REQUEST)

    user.save(update_fields=updated_fields + ['updated_at'])
    return Response({
        'message': '调整成功',
        'user_id': user.id,
        'level': user.level,
        'exp': user.exp,
    })


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 重置密码（高危 → 仅超管）
# ═══════════════════════════════════════════════════════════════

@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsSuperAdmin])
def admin_reset_password(request, user_id):
    """管理员 - 重置用户密码（仅超管）"""
    user = get_object_or_404(User, id=user_id)
    serializer = AdminResetPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(serializer.validated_data['new_password'])
    # 如果 User 有 token_version，重置密码后 +1 强制下线所有端
    if hasattr(user, 'token_version'):
        user.token_version = (user.token_version or 0) + 1
        user.save(update_fields=['_password', 'token_version', 'updated_at'])
    else:
        user.save(update_fields=['_password', 'updated_at'])

    return Response({
        'message': '密码重置成功',
        'user_id': user.id,
        'operator_id': request.user.id,
    })


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 登录日志
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_user_login_logs(request, user_id):
    """管理员 - 查看指定用户登录日志"""
    user = get_object_or_404(User, id=user_id)
    queryset = user.login_logs.all().order_by('-created_at')

    paginator = LoginLogPagination()
    page = paginator.paginate_queryset(queryset, request)
    data = [
        {
            'id': l.id,
            'login_method': l.login_method,
            'login_method_display': l.get_login_method_display(),
            'platform': l.platform,
            'device_id': l.device_id,
            'ip_address': l.ip_address,
            'location': l.location,
            'user_agent': l.user_agent,
            'is_success': l.is_success,
            'fail_reason': l.fail_reason,
            'created_at': l.created_at,
        }
        for l in page
    ]
    return paginator.get_paginated_response(data)


@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_login_logs(request):
    """管理员 - 全站登录日志（含筛选）"""
    queryset = UserLoginLog.objects.all().select_related('user').order_by('-created_at')
    filtered = UserLoginLogFilter(request.GET, queryset=queryset).qs

    paginator = LoginLogPagination()
    page = paginator.paginate_queryset(filtered, request)
    data = [
        {
            'id': l.id,
            'user_id': l.user_id,
            'username': l.user.display_name,
            'phone': l.user.phone,
            'login_method': l.get_login_method_display(),
            'platform': l.platform,
            'ip_address': l.ip_address,
            'location': l.location,
            'is_success': l.is_success,
            'fail_reason': l.fail_reason,
            'created_at': l.created_at,
        }
        for l in page
    ]
    return paginator.get_paginated_response(data)


# ═══════════════════════════════════════════════════════════════
# 管理员端 - 统计概览
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_user_stats(request):
    """管理员 - 用户数据概览"""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timezone.timedelta(days=7)
    month_start = today_start.replace(day=1)

    base = User.objects.all()

    return Response({
        'total': base.count(),
        'new_users': {
            'today': base.filter(created_at__gte=today_start).count(),
            'week': base.filter(created_at__gte=week_start).count(),
            'month': base.filter(created_at__gte=month_start).count(),
        },
        'active_users': {
            'today': base.filter(last_active_at__gte=today_start).count(),
            'week': base.filter(last_active_at__gte=week_start).count(),
        },
        'status': {
            'vip': base.filter(is_vip=True, vip_expired_at__gte=now).count(),
            'verified': base.filter(is_verified=True).count(),
            'banned': base.filter(is_banned=True).count(),
            'inactive': base.filter(is_active=False).count(),
        },
        'channel_distribution': list(
            base.values('register_channel').annotate(count=Count('id')).order_by('-count')
        ),
        'gender_distribution': list(
            base.values('gender').annotate(count=Count('id')).order_by('-count')
        ),
    })

# ═══════════════════════════════════════════════════════════════
# 管理员端 - 资料审核（头像 / 昵称）
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_profile_audit_list(request):
    """
    管理员 - 资料审核列表（默认只看待审核）
    query: status=pending(默认)/approved/rejected/all, field=username|avatar
    分页返回里的 count 即为待审核总数，可用于菜单红点。
    """
    status_param = request.GET.get('status', 'pending')
    field_param  = request.GET.get('field')

    qs = UserProfileAudit.objects.select_related('user').order_by('-created_at')
    if status_param and status_param != 'all':
        qs = qs.filter(status=status_param)
    if field_param:
        qs = qs.filter(field=field_param)

    paginator = StandardPagination()
    page = paginator.paginate_queryset(qs, request)
    data = [
        {
            'id': a.id,
            'user_id': a.user_id,
            'current_username': a.user.display_name,  # 当前线上昵称
            'phone': a.user.phone,
            'field': a.field,
            'field_display': a.get_field_display(),
            'old_value': a.old_value,
            'new_value': a.new_value,                 # 头像就是 URL，前端直接 <img>
            'status': a.status,
            'status_display': a.get_status_display(),
            'reject_reason': a.reject_reason,
            'reviewer_id': a.reviewer_id,
            'reviewed_at': a.reviewed_at,
            'created_at': a.created_at,
        }
        for a in page
    ]
    return paginator.get_paginated_response(data)


@api_view(['POST'])
@authentication_classes([ManagerAuthentication])
@permission_classes([IsManager])
def admin_review_profile_audit(request, audit_id):
    """
    管理员 - 审核资料修改
    body: { action: 'approve' | 'reject', reject_reason?: str }
      approve → 把 new_value 写回 User 对应字段
      reject  → 仅标记并记录原因，不改用户资料
    """
    action = request.data.get('action')
    if action not in ('approve', 'reject'):
        return Response({'error': "action 必须是 approve 或 reject"},
                        status=status.HTTP_400_BAD_REQUEST)

    audit = get_object_or_404(UserProfileAudit, id=audit_id)
    if audit.status != UserProfileAudit.Status.PENDING:
        return Response({'error': '该记录已审核，请勿重复操作'},
                        status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        # 行锁，防并发重复审核
        audit = (UserProfileAudit.objects
                 .select_for_update().select_related('user').get(id=audit_id))
        if audit.status != UserProfileAudit.Status.PENDING:
            return Response({'error': '该记录已审核，请勿重复操作'},
                            status=status.HTTP_400_BAD_REQUEST)

        user = audit.user
        if action == 'approve':
            setattr(user, audit.field, audit.new_value)        # 写回真实字段
            user.save(update_fields=[audit.field, 'updated_at'])
            audit.status = UserProfileAudit.Status.APPROVED
        else:
            audit.reject_reason = (request.data.get('reject_reason') or '').strip()[:200]
            audit.status = UserProfileAudit.Status.REJECTED

        audit.reviewer_id = request.user.id
        audit.reviewed_at = timezone.now()
        audit.save(update_fields=['status', 'reject_reason', 'reviewer_id', 'reviewed_at', 'updated_at'])

    return Response({
        'message': '已通过' if action == 'approve' else '已驳回',
        'audit_id': audit.id, 'user_id': audit.user_id,
        'field': audit.field, 'status': audit.status,
    })


# ═══════════════════════════════════════════════════════════════
# 邀请功能 - 常量 & 工具
# ═══════════════════════════════════════════════════════════════
INVITE_REWARD_GOLD = 100  # 每邀请 1 人奖励 100 金币(后续可改)
INVITEE_REWARD_GOLD = 100  # ★ 被邀请人(新用户)注册奖励，可独立调整

INVITE_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'  # 去掉容易混淆的 I/O/0/1
INVITE_CODE_LEN = 8


def _generate_invite_code():
    """生成全局唯一邀请码"""
    for _ in range(10):
        code = ''.join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LEN))
        if not User.objects.filter(invite_code=code).exists():
            return code
    raise RuntimeError('邀请码生成失败,请重试')


def _ensure_invite_code(user):
    """确保用户有邀请码,无则生成"""
    if user.invite_code:
        return user.invite_code
    code = _generate_invite_code()
    User.objects.filter(pk=user.pk, invite_code='').update(invite_code=code)
    user.refresh_from_db(fields=['invite_code'])
    return user.invite_code


def _mask_phone(phone):
    """脱敏手机号:138****1234"""
    if not phone or len(phone) < 7:
        return phone or ''
    return phone[:3] + '****' + phone[-4:]


def _process_invite_reward(new_user, invite_code):
    """
    处理邀请奖励:
      1. 找到邀请人 → 绑定 invited_by
      2. 给【邀请人】加 INVITE_REWARD_GOLD 金币
      3. 写 InviteReward 记录

    注:被邀请人(新用户)的注册奖励已由 register_user 统一发放(100 金币)，
       这里不再额外给被邀请人发钱，避免叠加成 200。

    ⚠️ 必须在主注册事务【之外】调用，失败不阻断注册主流程
    """
    code = (invite_code or '').strip()
    if not code:
        return

    try:
        # 1. 查邀请人
        inviter = (
            User.objects
            .filter(invite_code__iexact=code)
            .exclude(pk=new_user.pk)
            .first()
        )
        if not inviter:
            return
        if not inviter.is_active or inviter.is_banned:
            return

        # 2. 绑定 invited_by(只允许绑一次)
        if new_user.invited_by_id is None:
            new_user.invited_by = inviter
            new_user.save(update_fields=['invited_by'])

        # 3. 防重复发奖(快路径)
        if InviteReward.objects.filter(inviter=inviter, invitee=new_user).exists():
            return

        # 4. 邀请人钱包 + 加金币
        inviter_wallet, _ = UserWallet.objects.get_or_create(user=inviter)
        inviter_tx = inviter_wallet.change_gold(
            amount=INVITE_REWARD_GOLD,
            action=WalletTransaction.Action.GOLD_GRANT,
            operator_id=new_user.id,
            operator_role='system',
            related_type='invite',
            related_id=new_user.id,
            remark=f'邀请好友 {new_user.display_name} 注册',
            idempotent_key=f'invite_reward_{inviter.id}_{new_user.id}',
        )

        # 5. 写邀请奖励记录(unique_together 兜底防重复)
        InviteReward.objects.create(
            inviter=inviter,
            invitee=new_user,
            reward_gold=INVITE_REWARD_GOLD,
            status='issued',
            business_no=str(inviter_tx.id),
            issued_at=timezone.now(),
            remark=f'邀请注册奖励 +{INVITE_REWARD_GOLD}',
        )

    except IntegrityError:
        # 并发场景下 InviteReward 已存在，正常忽略
        pass
    except Exception:
        # 任何其它异常都吞掉，打日志即可，不影响注册
        import traceback
        traceback.print_exc()
# ═══════════════════════════════════════════════════════════════
# 用户端 - 邀请好友
# ═══════════════════════════════════════════════════════════════

@api_view(['GET'])
@authentication_classes([UserAuthentication])
def get_invite_summary_api(request):
    """
    GET /user/invite/summary/  —— 邀请页汇总
    返回: {invite_code, invited_count, total_gold, reward_per_invite}
    """
    user = request.user
    invite_code = _ensure_invite_code(user)
    invited_count = User.objects.filter(invited_by=user).count()
    total_gold = (
        InviteReward.objects
        .filter(inviter=user, status='issued')
        .aggregate(s=Sum('reward_gold'))['s']
    ) or 0

    return Response({
        'invite_code': invite_code,
        'invited_count': invited_count,
        'total_gold': total_gold,
        'reward_per_invite': INVITE_REWARD_GOLD,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([UserAuthentication])
def get_invite_records(request):
    """
    GET /user/invite/records/  —— 邀请记录(分页)
    返回被邀请人简略信息 + 获得金币数
    """
    queryset = (
        InviteReward.objects
        .filter(inviter=request.user)
        .select_related('invitee')
        .order_by('-created_at')
    )

    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)

    data = [
        {
            'id': r.id,
            'invitee_id': r.invitee_id,
            'invitee_name': r.invitee.display_name,
            'invitee_avatar': r.invitee.avatar or '',
            'invitee_phone_masked': _mask_phone(r.invitee.phone),
            'reward_gold': r.reward_gold,
            'status': r.status,
            'status_display': r.get_status_display(),
            'issued_at': r.issued_at,
            'created_at': r.created_at,
        }
        for r in page
    ]
    return paginator.get_paginated_response(data)


# ═══════════════════════════════════════════════════════════════
# 用户端 - 转赠金币
# ═══════════════════════════════════════════════════════════════
MIN_TRANSFER_GOLD = 1
MAX_TRANSFER_GOLD = 10000


@api_view(['POST'])
@authentication_classes([UserAuthentication])
def transfer_lookup(request):
    """
    POST /user/transfer/lookup/
    body: { phone: "138..." }
    根据手机号查找收款人,返回脱敏信息
    """
    phone = (request.data.get('phone') or '').strip()
    if not phone:
        return Response({'error': '请输入手机号'}, status=status.HTTP_400_BAD_REQUEST)

    target = User.objects.filter(phone=phone).first()
    if not target:
        return Response({'error': '未找到该用户'}, status=status.HTTP_400_BAD_REQUEST)
    if target.pk == request.user.pk:
        return Response({'error': '不能转赠给自己'}, status=status.HTTP_400_BAD_REQUEST)
    if not target.is_active or target.is_banned:
        return Response({'error': '该用户当前不可接收转赠'}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'user_id': target.id,
        'avatar': target.avatar or '',
        'display_name': target.display_name,
        'phone_masked': _mask_phone(target.phone),
    })


@api_view(['POST'])
@authentication_classes([UserAuthentication])
def transfer_gold(request):
    """
    POST /user/transfer/
    body: { recipient_id, amount, remark }
    """
    sender = request.user
    recipient_id = request.data.get('recipient_id')
    amount = request.data.get('amount')
    remark = (request.data.get('remark') or '').strip()[:100]

    # 1. 参数校验
    if not recipient_id or amount is None:
        return Response({'error': '参数不完整'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        recipient_id = int(recipient_id)
        amount = int(amount)
    except (TypeError, ValueError):
        return Response({'error': '参数格式错误'}, status=status.HTTP_400_BAD_REQUEST)

    if amount < MIN_TRANSFER_GOLD:
        return Response({'error': f'单笔最少 {MIN_TRANSFER_GOLD} 金币'},
                        status=status.HTTP_400_BAD_REQUEST)
    if amount > MAX_TRANSFER_GOLD:
        return Response({'error': f'单笔最多 {MAX_TRANSFER_GOLD} 金币'},
                        status=status.HTTP_400_BAD_REQUEST)
    if sender.id == recipient_id:
        return Response({'error': '不能转赠给自己'}, status=status.HTTP_400_BAD_REQUEST)

    # 2. 校验收款人
    recipient = User.objects.filter(pk=recipient_id).first()
    if not recipient:
        return Response({'error': '收款人不存在'}, status=status.HTTP_400_BAD_REQUEST)
    if not recipient.is_active or recipient.is_banned:
        return Response({'error': '收款人状态异常'}, status=status.HTTP_400_BAD_REQUEST)

    # 3. 双方钱包(自动创建)
    sender_wallet, _ = UserWallet.objects.get_or_create(user=sender)
    recipient_wallet, _ = UserWallet.objects.get_or_create(user=recipient)

    # 4. 幂等键(粒度到毫秒,粗略防止双击)
    import time
    idem = f'transfer_{sender.id}_{recipient.id}_{int(time.time() * 1000)}'

    # 5. 转出 + 转入,外层 atomic 保证原子性(失败全回滚)
    try:
        with transaction.atomic():
            out_tx = sender_wallet.change_gold(
                amount=-amount,
                action=WalletTransaction.Action.GOLD_DEDUCT,
                operator_id=sender.id,
                operator_role='user',
                related_type='transfer',
                related_id=recipient.id,
                remark=remark or f'转赠给 {recipient.display_name}',
                idempotent_key=f'{idem}_out',
            )
            recipient_wallet.change_gold(
                amount=amount,
                action=WalletTransaction.Action.GOLD_GRANT,
                operator_id=sender.id,
                operator_role='user',
                related_type='transfer',
                related_id=sender.id,
                remark=remark or f'来自 {sender.display_name} 的转赠',
                idempotent_key=f'{idem}_in',
            )
    except ValueError as e:
        # change_gold 内部抛的:余额不足 / 钱包冻结 / 校验失败
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'transaction_id': out_tx.id,
        'amount': amount,
        'recipient': {
            'user_id': recipient.id,
            'display_name': recipient.display_name,
            'avatar': recipient.avatar or '',
        },
        'sender_gold_available': sender_wallet.gold_available,
    }, status=status.HTTP_201_CREATED)