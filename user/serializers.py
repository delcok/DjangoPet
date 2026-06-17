# -*- coding: utf-8 -*-
from rest_framework import serializers
from django.utils import timezone
from .models import User, UserAuthProvider, UserDevice, UserLoginLog, UserProfileAudit
import re


# ═══════════════════════════════════════════════════════
# 用户端序列化器
# ═══════════════════════════════════════════════════════

class UserSerializer(serializers.ModelSerializer):
    """用户信息序列化器（用户端）"""

    display_name = serializers.ReadOnlyField()
    avatar_url = serializers.SerializerMethodField()
    vip_status = serializers.SerializerMethodField()
    pending_profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'avatar', 'avatar_url', 'bio', 'phone', 'email',
            'gender', 'birth_date',
            'is_vip', 'vip_level', 'vip_expired_at', 'vip_status',
            'is_verified', 'level', 'exp',
            # ★ 宠物端社交统计（系统维护，只读）—— 商城没有这几个字段
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'is_public', 'allow_message',
            'is_active', 'display_name',
            'last_login', 'created_at', 'updated_at',
            'pending_profile',
        ]
        read_only_fields = [
            'id', 'phone', 'is_vip', 'vip_level', 'vip_expired_at',
            'is_verified', 'level', 'exp', 'is_active',
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'last_login', 'created_at', 'updated_at',
        ]

    def get_avatar_url(self, obj):
        if obj.avatar and obj.avatar.startswith('http'):
            return obj.avatar
        elif obj.avatar:
            return f"https://cdn.yimengzhiyuan.com/{obj.avatar.lstrip('/')}"   # ★ 换成你的真实 CDN
        return "https://cdn.yimengzhiyuan.com/avatar/av-gen.png"

    def get_vip_status(self, obj):
        if not obj.is_vip:
            return '普通用户'
        if obj.vip_expired_at and obj.vip_expired_at < timezone.now():
            return 'VIP已过期'
        return f'VIP{obj.vip_level}级用户'

    def get_pending_profile(self, obj):
        """
        返回用户自己「未通过」的头像/昵称（pending 或最近一次 rejected）。
        前端用 status 决定显示「审核中」还是「已驳回」。
        仅用于单对象场景（get_user_info / 登录返回），不要用在列表里。
        """
        out = {}
        for f in (UserProfileAudit.Field.USERNAME, UserProfileAudit.Field.AVATAR):
            a = (UserProfileAudit.objects
                 .filter(user=obj, field=f)
                 .order_by('-created_at')
                 .first())
            if a and a.status != UserProfileAudit.Status.APPROVED:
                out[f] = {
                    'value': a.new_value,
                    'status': a.status,
                    'reject_reason': a.reject_reason,
                    'submitted_at': a.created_at,
                }
        return out


class UserUpdateSerializer(serializers.ModelSerializer):
    """用户信息更新序列化器（用户端）—— 社交统计 / VIP / 认证都不可在这里改"""

    class Meta:
        model = User
        fields = ['username', 'avatar', 'bio', 'gender', 'birth_date', 'email']

    def validate_username(self, value):
        if value:
            value = value.strip()
            if len(value) < 2:
                raise serializers.ValidationError("用户名至少需要2个字符")
            if len(value) > 30:
                raise serializers.ValidationError("用户名不能超过30个字符")
        return value


class WechatLoginSerializer(serializers.Serializer):
    """微信登录序列化器"""
    code = serializers.CharField(help_text="微信登录code")
    user_info = serializers.JSONField(required=False, help_text="微信用户信息")
    invite_code = serializers.CharField(required=False, allow_blank=True, default="")

# 中国大陆手机号（与阿里云短信一致，App 登录注册用）
CN_PHONE_RE = re.compile(r'^1[3-9]\d{9}$')


class SendSmsCodeSerializer(serializers.Serializer):
    """发送短信验证码（App 端：登录/注册）"""
    phone = serializers.CharField(max_length=17, help_text="手机号")
    scene = serializers.ChoiceField(
        choices=['login', 'register', 'reset_password'],
        default='login',
        help_text="登录注册统一用 login，留空即可",
    )

    def validate_phone(self, value):
        value = (value or '').strip()
        if not CN_PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value


class SmsLoginSerializer(serializers.Serializer):
    """短信验证码登录/注册（手机号不存在则自动注册）"""
    phone = serializers.CharField(max_length=17, help_text="手机号")
    code = serializers.CharField(min_length=4, max_length=6, help_text="短信验证码")
    scene = serializers.ChoiceField(
        choices=['login', 'register'], default='login',
        help_text="需与发送时一致；统一登录注册流程留空即可",
    )
    platform = serializers.ChoiceField(
        choices=['ios', 'android', 'h5', 'web'],
        default='ios', help_text="客户端平台",
    )
    invite_code = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="邀请码（仅新用户注册时生效）",
    )

    def validate_phone(self, value):
        value = (value or '').strip()
        if not CN_PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value

    def validate_code(self, value):
        value = (value or '').strip()
        if not value.isdigit():
            raise serializers.ValidationError("验证码必须为数字")
        return value

# ═══════════════════════════════════════════════════════
# 管理员端 - 用户列表/详情序列化器
# ═══════════════════════════════════════════════════════

class AdminUserListSerializer(serializers.ModelSerializer):
    """管理员 - 用户列表（精简，含钱包概要 + 社交概要）"""

    display_name = serializers.ReadOnlyField()
    vip_status = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    register_channel_display = serializers.CharField(source='get_register_channel_display', read_only=True)
    wallet = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'display_name', 'avatar', 'phone', 'email',
            'gender', 'gender_display',
            'is_vip', 'vip_level', 'vip_expired_at', 'vip_status',
            'is_verified', 'level', 'exp',
            # ★ 宠物端社交概要
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'register_channel', 'register_channel_display',
            'is_active', 'is_banned',
            'last_login', 'last_active_at', 'created_at',
            'wallet',
        ]

    def get_vip_status(self, obj):
        if not obj.is_vip:
            return '普通用户'
        if obj.vip_expired_at and obj.vip_expired_at < timezone.now():
            return 'VIP已过期'
        return f'VIP{obj.vip_level}级'

    def get_wallet(self, obj):
        """钱包概要 —— 通过 select_related('wallet') 拿到，避免 N+1"""
        wallet = getattr(obj, 'wallet', None)
        if not wallet:
            return {'points_balance': 0, 'gold_balance': 0}
        return {
            'points_balance': wallet.points_balance,
            'points_available': getattr(wallet, 'points_available', wallet.points_balance),
            'gold_balance': wallet.gold_balance,
            'gold_available': getattr(wallet, 'gold_available', wallet.gold_balance),
        }


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """管理员 - 用户详情（完整字段 + 关联数据）"""

    display_name = serializers.ReadOnlyField()
    has_password = serializers.ReadOnlyField()
    is_complete_profile = serializers.ReadOnlyField()
    vip_status = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    register_channel_display = serializers.CharField(source='get_register_channel_display', read_only=True)

    invited_by_info = serializers.SerializerMethodField()
    invited_count = serializers.SerializerMethodField()

    auth_providers = serializers.SerializerMethodField()
    devices = serializers.SerializerMethodField()
    wallet = serializers.SerializerMethodField()
    recent_logins = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'display_name', 'avatar', 'bio',
            'phone', 'email',
            'gender', 'gender_display', 'birth_date',
            'has_password', 'is_complete_profile',
            'is_vip', 'vip_level', 'vip_expired_at', 'vip_status',
            'is_verified', 'verification_type', 'verified_at',
            'level', 'exp',
            # ★ 宠物端社交统计
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'is_public', 'allow_message',
            'register_channel', 'register_channel_display',
            'invite_code', 'invited_by', 'invited_by_info', 'invited_count',
            'is_active', 'is_banned', 'ban_reason',
            'last_login', 'last_active_at',
            'created_at', 'updated_at',
            'auth_providers', 'devices', 'wallet', 'recent_logins',
        ]
        read_only_fields = [
            'followers_count', 'following_count', 'posts_count', 'likes_received',
        ]

    def get_vip_status(self, obj):
        if not obj.is_vip:
            return '普通用户'
        if obj.vip_expired_at and obj.vip_expired_at < timezone.now():
            return 'VIP已过期'
        return f'VIP{obj.vip_level}级'

    def get_invited_by_info(self, obj):
        if not obj.invited_by:
            return None
        return {
            'id': obj.invited_by.id,
            'username': obj.invited_by.display_name,
            'phone': obj.invited_by.phone,
        }

    def get_invited_count(self, obj):
        return obj.invited_users.count()

    def get_auth_providers(self, obj):
        return [
            {
                'id': p.id,
                'provider': p.provider,
                'provider_display': p.get_provider_display(),
                'union_id': p.union_id,
                'created_at': p.created_at,
            }
            for p in obj.auth_providers.all()
        ]

    def get_devices(self, obj):
        return [
            {
                'id': d.id,
                'platform': d.platform,
                'platform_display': d.get_platform_display(),
                'device_brand': d.device_brand,
                'device_model': d.device_model,
                'os_version': d.os_version,
                'app_version': d.app_version,
                'channel': d.channel,
                'is_active': d.is_active,
                'last_active_at': d.last_active_at,
            }
            for d in obj.devices.all()[:10]
        ]

    def get_wallet(self, obj):
        wallet = getattr(obj, 'wallet', None)
        if not wallet:
            return None
        return {
            'points_balance': wallet.points_balance,
            'points_available': getattr(wallet, 'points_available', wallet.points_balance),
            'points_total_earned': wallet.points_total_earned,
            'points_frozen': wallet.points_frozen,
            'gold_balance': wallet.gold_balance,
            'gold_available': getattr(wallet, 'gold_available', wallet.gold_balance),
            'gold_total_earned': wallet.gold_total_earned,
            'gold_frozen': wallet.gold_frozen,
        }

    def get_recent_logins(self, obj):
        logs = obj.login_logs.order_by('-created_at')[:5]
        return [
            {
                'login_method': l.get_login_method_display(),
                'platform': l.platform,
                'ip_address': l.ip_address,
                'location': l.location,
                'is_success': l.is_success,
                'created_at': l.created_at,
            }
            for l in logs
        ]


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """
    管理员 - 编辑用户基本资料（比用户端权限更大）
    注意：实名认证字段不在这里改，要走 admin_verify_user 接口；
         社交统计也不允许后台手改。
    """

    class Meta:
        model = User
        fields = [
            'username', 'avatar', 'bio', 'email',
            'gender', 'birth_date',
            'is_public', 'allow_message',
        ]

    def validate_username(self, value):
        if value:
            value = value.strip()
            if len(value) < 2 or len(value) > 30:
                raise serializers.ValidationError("用户名长度必须在 2-30 个字符之间")
        return value


# ═══════════════════════════════════════════════════════
# 管理员端 - 各类操作序列化器（与商城一致）
# ═══════════════════════════════════════════════════════

class AdminBanUserSerializer(serializers.Serializer):
    """封禁/解封用户"""
    is_banned = serializers.BooleanField(help_text="True=封禁, False=解封")
    ban_reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="",
        help_text="封禁原因（封禁时建议必填）"
    )

    def validate(self, attrs):
        if attrs.get('is_banned') and not attrs.get('ban_reason'):
            raise serializers.ValidationError({'ban_reason': '封禁时必须填写原因'})
        return attrs


class AdminToggleActiveSerializer(serializers.Serializer):
    """启用/禁用用户"""
    is_active = serializers.BooleanField(help_text="True=启用, False=禁用")
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="",
        help_text="操作备注"
    )


class AdminSetVipSerializer(serializers.Serializer):
    """设置 VIP（开通 / 续费 / 升级）"""
    vip_level = serializers.IntegerField(min_value=1, max_value=10, help_text="VIP 等级 1-10")
    duration_days = serializers.IntegerField(
        required=False, min_value=1,
        help_text="续费天数（与 vip_expired_at 二选一）"
    )
    vip_expired_at = serializers.DateTimeField(
        required=False,
        help_text="到期时间（与 duration_days 二选一）"
    )
    extend = serializers.BooleanField(
        default=False,
        help_text="是否在原到期时间基础上续费（True=累加，False=覆盖）"
    )
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get('duration_days') and not attrs.get('vip_expired_at'):
            raise serializers.ValidationError("必须提供 duration_days 或 vip_expired_at 之一")
        return attrs


class AdminCancelVipSerializer(serializers.Serializer):
    """取消 VIP"""
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AdminVerifyUserSerializer(serializers.Serializer):
    """实名认证 / 取消认证"""
    is_verified = serializers.BooleanField(help_text="True=认证, False=取消认证")
    verification_type = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default="",
        help_text="认证类型，例如 id_card / business / artist"
    )

    def validate(self, attrs):
        if attrs.get('is_verified') and not attrs.get('verification_type'):
            raise serializers.ValidationError({'verification_type': '认证时必须指定认证类型'})
        return attrs


class AdminChangeLevelSerializer(serializers.Serializer):
    """调整用户等级 / 经验值"""
    level = serializers.IntegerField(min_value=1, required=False, help_text="设置等级")
    exp = serializers.IntegerField(min_value=0, required=False, help_text="设置经验值（绝对值）")
    exp_delta = serializers.IntegerField(required=False, help_text="经验值增量（正负皆可）")
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if 'level' not in attrs and 'exp' not in attrs and 'exp_delta' not in attrs:
            raise serializers.ValidationError("至少提供 level / exp / exp_delta 中的一项")
        return attrs


class AdminResetPasswordSerializer(serializers.Serializer):
    """管理员重置用户密码"""
    new_password = serializers.CharField(
        min_length=6, max_length=128, write_only=True,
        help_text="新密码（6-128 位）"
    )