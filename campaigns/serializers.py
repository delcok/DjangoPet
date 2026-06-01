# -*- coding: utf-8 -*-
from rest_framework import serializers

from .models import Campaign, CouponTemplate, UserCoupon, RedemptionLog
from utils.coupon_code import normalize_code


# ============================================================
# 券模板
# ============================================================
class CouponTemplateSerializer(serializers.ModelSerializer):
    """券模板序列化器（管理端）"""

    coupon_type_display = serializers.CharField(source='get_coupon_type_display', read_only=True)
    validity_type_display = serializers.CharField(source='get_validity_type_display', read_only=True)

    class Meta:
        model = CouponTemplate
        fields = [
            'id', 'name', 'description',
            'coupon_type', 'coupon_type_display',
            'face_value', 'min_consumption', 'discount_rate',
            'validity_type', 'validity_type_display',
            'valid_days', 'valid_start', 'valid_end',
            'image_url', 'use_instructions', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        validity_type = attrs.get('validity_type', getattr(self.instance, 'validity_type', None))
        if validity_type == 'fixed':
            if not attrs.get('valid_start') or not attrs.get('valid_end'):
                raise serializers.ValidationError('固定时间段类型必须填写有效起止时间')
        elif validity_type == 'relative':
            if not attrs.get('valid_days'):
                raise serializers.ValidationError('相对有效期类型必须填写有效天数')
        return attrs


# ============================================================
# 活动
# ============================================================
class CampaignListSerializer(serializers.ModelSerializer):
    """活动列表序列化器（精简）"""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    coupon_name = serializers.CharField(source='coupon_template.name', read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'cover_image_url',
            'status', 'status_display',
            'start_time', 'end_time',
            'coupon_name', 'quantity_per_claim',
            'total_quota', 'claimed_count', 'remaining_quota',
            'per_user_limit', 'is_running',
            'created_at',
        ]


class CampaignDetailSerializer(serializers.ModelSerializer):
    """活动详情序列化器（含完整信息）"""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    coupon_template_detail = CouponTemplateSerializer(source='coupon_template', read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'description', 'rules',
            'cover_image_url',
            'coupon_template', 'coupon_template_detail',
            'quantity_per_claim',
            'start_time', 'end_time',
            'status', 'status_display',
            'total_quota', 'claimed_count', 'remaining_quota',
            'per_user_limit',
            'wx_scene', 'wx_code_image_url', 'wx_code_page',
            'is_running',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'wx_scene', 'wx_code_image_url',
            'claimed_count', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        start = attrs.get('start_time') or getattr(self.instance, 'start_time', None)
        end = attrs.get('end_time') or getattr(self.instance, 'end_time', None)
        if start and end and start >= end:
            raise serializers.ValidationError('结束时间必须晚于开始时间')
        return attrs


class CampaignPublicSerializer(serializers.ModelSerializer):
    """小程序端展示活动信息（用户扫码后看到的）"""

    coupon_name = serializers.CharField(source='coupon_template.name', read_only=True)
    coupon_description = serializers.CharField(source='coupon_template.description', read_only=True)
    coupon_image_url = serializers.URLField(source='coupon_template.image_url', read_only=True)
    coupon_face_value = serializers.DecimalField(
        source='coupon_template.face_value', max_digits=10, decimal_places=2, read_only=True,
    )
    use_instructions = serializers.CharField(source='coupon_template.use_instructions',
                                             read_only=True)
    is_running = serializers.BooleanField(read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'description', 'rules', 'cover_image_url',
            'start_time', 'end_time',
            'coupon_name', 'coupon_description', 'coupon_image_url',
            'coupon_face_value', 'use_instructions',
            'quantity_per_claim', 'per_user_limit',
            'remaining_quota', 'is_running',
        ]


# ============================================================
# 用户券（关键改动：动态计算 status / status_display）
# ============================================================
class UserCouponSerializer(serializers.ModelSerializer):
    """
    用户券（小程序端）

    实时计算展示态：db 中状态为 unused 但实际已过期的券,
    对外展示为 expired,避免 Celery 任务窗口期内的状态不一致。
    """

    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    formatted_code = serializers.CharField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    campaign_name = serializers.CharField(source='campaign.name', read_only=True, default='')
    merchant_name = serializers.SerializerMethodField()

    # ★ 新增:把券类型扁平化暴露,下单选券时前端要根据它算抵扣
    coupon_type = serializers.CharField(
        source='coupon_template.coupon_type', read_only=True,
    )
    coupon_type_display = serializers.CharField(
        source='coupon_template.get_coupon_type_display', read_only=True,
    )

    class Meta:
        model = UserCoupon
        fields = [
            'id', 'code', 'formatted_code',
            'status', 'status_display',
            'snapshot_name', 'snapshot_image_url',
            'snapshot_face_value', 'snapshot_min_consumption', 'snapshot_discount_rate',
            'valid_from', 'valid_to',
            'claimed_at', 'used_at', 'merchant_id',
            'campaign_name', 'is_expired', 'merchant_name',
            'coupon_type', 'coupon_type_display',  # ★ 新增
        ]

    def _effective_status(self, obj):
        """db status='unused' 但实际已过期 → 展示为 expired"""
        if obj.status == 'unused' and obj.is_expired:
            return 'expired'
        return obj.status

    def get_status(self, obj):
        return self._effective_status(obj)

    def get_status_display(self, obj):
        status_map = dict(UserCoupon.STATUS_CHOICES)
        return status_map.get(self._effective_status(obj), obj.status)

    def get_merchant_name(self, obj):
        """
        优先从 context 的 merchant_map 取(列表/详情接口已批量预查),
        fallback 单查兜底其它调用场景(比如 claim 接口序列化新券时)。
        """
        if not obj.merchant_id:
            return ''

        # 优先用 ViewSet 注入的批量 map
        merchant_map = self.context.get('merchant_map')
        if merchant_map is not None:
            return merchant_map.get(obj.merchant_id, '')

        # Fallback:单查(适用于 claim 等场景)
        from merchants.models import Merchant
        try:
            m = Merchant.objects.only('name').get(id=obj.merchant_id)
            return m.name or ''
        except Merchant.DoesNotExist:
            return ''


class UserCouponAdminSerializer(serializers.ModelSerializer):
    """
    用户券（管理端，含用户信息）

    管理端也加上展示态兜底，让管理员看到的状态跟用户端一致
    """

    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    formatted_code = serializers.CharField(read_only=True)
    user_nickname = serializers.CharField(source='user.nickname', read_only=True, default='')
    user_phone = serializers.CharField(source='user.phone', read_only=True, default='')
    campaign_name = serializers.CharField(source='campaign.name', read_only=True, default='')
    redeemed_by_name = serializers.CharField(source='redeemed_by.username',
                                             read_only=True, default='')

    class Meta:
        model = UserCoupon
        fields = [
            'id', 'code', 'formatted_code',
            'user', 'user_nickname', 'user_phone',
            'campaign', 'campaign_name',
            'status', 'status_display',
            'snapshot_name', 'snapshot_face_value',
            'valid_from', 'valid_to',
            'claimed_at', 'used_at',
            'redeemed_by', 'redeemed_by_name',
            'redemption_amount', 'remark',
        ]

    def _effective_status(self, obj):
        if obj.status == 'unused' and obj.is_expired:
            return 'expired'
        return obj.status

    def get_status(self, obj):
        return self._effective_status(obj)

    def get_status_display(self, obj):
        status_map = dict(UserCoupon.STATUS_CHOICES)
        return status_map.get(self._effective_status(obj), obj.status)


# ============================================================
# 核销
# ============================================================
class RedemptionQuerySerializer(serializers.Serializer):
    """核销前查询券信息"""
    code = serializers.CharField(max_length=20, help_text='核销码，可带连字符')

    def validate_code(self, value):
        return normalize_code(value)


class RedemptionSerializer(serializers.Serializer):
    """执行核销"""
    code = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2,
                                      required=False, allow_null=True)
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')

    def validate_code(self, value):
        return normalize_code(value)


class RedemptionLogSerializer(serializers.ModelSerializer):
    """核销日志"""

    action_display = serializers.CharField(source='get_action_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username',
                                          read_only=True, default='')
    coupon_code = serializers.CharField(source='user_coupon.code', read_only=True)

    class Meta:
        model = RedemptionLog
        fields = [
            'id', 'user_coupon', 'coupon_code',
            'operator', 'operator_name',
            'action', 'action_display',
            'amount', 'remark', 'ip_address', 'created_at',
        ]


# ============================================================
# 商户端 — 券模板
# ============================================================
class MerchantCouponTemplateSerializer(serializers.ModelSerializer):
    """商户端券模板序列化器"""

    coupon_type_display = serializers.CharField(source='get_coupon_type_display', read_only=True)
    validity_type_display = serializers.CharField(source='get_validity_type_display', read_only=True)
    is_public = serializers.SerializerMethodField()

    class Meta:
        model = CouponTemplate
        fields = [
            'id', 'name', 'description',
            'coupon_type', 'coupon_type_display',
            'face_value', 'min_consumption', 'discount_rate',
            'validity_type', 'validity_type_display',
            'valid_days', 'valid_start', 'valid_end',
            'image_url', 'use_instructions', 'is_active',
            'merchant_id', 'is_public',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'merchant_id', 'created_at', 'updated_at',
        ]

    def get_is_public(self, obj):
        return obj.merchant_id is None

    def validate(self, attrs):
        validity_type = attrs.get('validity_type', getattr(self.instance, 'validity_type', None))
        if validity_type == 'fixed':
            if not attrs.get('valid_start') or not attrs.get('valid_end'):
                raise serializers.ValidationError('固定时间段类型必须填写有效起止时间')
        elif validity_type == 'relative':
            if not attrs.get('valid_days'):
                raise serializers.ValidationError('相对有效期类型必须填写有效天数')
        return attrs


# ============================================================
# 商户端 — 活动
# ============================================================
class MerchantCampaignListSerializer(serializers.ModelSerializer):
    """商户端活动列表"""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    coupon_name = serializers.CharField(source='coupon_template.name', read_only=True)
    coupon_image_url = serializers.URLField(source='coupon_template.image_url', read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'cover_image_url',
            'status', 'status_display',
            'start_time', 'end_time',
            'coupon_name', 'coupon_image_url', 'quantity_per_claim',
            'total_quota', 'claimed_count', 'remaining_quota',
            'per_user_limit', 'is_running',
            'created_at',
        ]


class MerchantCampaignDetailSerializer(serializers.ModelSerializer):
    """商户端活动详情/创建"""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    coupon_template_detail = MerchantCouponTemplateSerializer(source='coupon_template', read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'description', 'rules',
            'cover_image_url',
            'coupon_template', 'coupon_template_detail',
            'quantity_per_claim',
            'start_time', 'end_time',
            'status', 'status_display',
            'total_quota', 'claimed_count', 'remaining_quota',
            'per_user_limit',
            'wx_scene', 'wx_code_image_url', 'wx_code_page',
            'is_running',
            'merchant_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'wx_scene', 'wx_code_image_url',
            'claimed_count', 'merchant_id',
            'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        start = attrs.get('start_time') or getattr(self.instance, 'start_time', None)
        end = attrs.get('end_time') or getattr(self.instance, 'end_time', None)
        if start and end and start >= end:
            raise serializers.ValidationError('结束时间必须晚于开始时间')

        # 校验:商户只能用平台公共模板或自己的私有模板
        tpl = attrs.get('coupon_template') or getattr(self.instance, 'coupon_template', None)
        if tpl is not None:
            merchant_id = self.context.get('merchant_id')
            if tpl.merchant_id is not None and tpl.merchant_id != merchant_id:
                raise serializers.ValidationError('无法使用其他商家的私有券模板')
            if not tpl.is_active:
                raise serializers.ValidationError('该券模板已停用')

        return attrs


# ============================================================
# 商户端 — 用户券(只读,核销用)
# ============================================================
class MerchantUserCouponSerializer(serializers.ModelSerializer):
    """
    商户端查看券信息(核销前预览/核销记录)
    """

    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    formatted_code = serializers.CharField(read_only=True)
    user_nickname = serializers.CharField(source='user.nickname', read_only=True, default='')
    user_phone = serializers.CharField(source='user.phone', read_only=True, default='')
    campaign_name = serializers.CharField(source='campaign.name', read_only=True, default='')

    class Meta:
        model = UserCoupon
        fields = [
            'id', 'code', 'formatted_code',
            'user', 'user_nickname', 'user_phone',
            'campaign', 'campaign_name', 'merchant_id',
            'status', 'status_display',
            'snapshot_name', 'snapshot_image_url',
            'snapshot_face_value', 'snapshot_min_consumption', 'snapshot_discount_rate',
            'valid_from', 'valid_to',
            'claimed_at', 'used_at',
            'redeemer_type', 'redeemer_id', 'redeemer_name',
            'redemption_amount', 'remark',
        ]

    def _effective_status(self, obj):
        if obj.status == 'unused' and obj.is_expired:
            return 'expired'
        return obj.status

    def get_status(self, obj):
        return self._effective_status(obj)

    def get_status_display(self, obj):
        status_map = dict(UserCoupon.STATUS_CHOICES)
        return status_map.get(self._effective_status(obj), obj.status)


# ============================================================
# 商户端 — 核销日志
# ============================================================
class MerchantRedemptionLogSerializer(serializers.ModelSerializer):
    """商户端核销日志"""

    action_display = serializers.CharField(source='get_action_display', read_only=True)
    coupon_code = serializers.CharField(source='user_coupon.code', read_only=True)
    coupon_name = serializers.CharField(source='user_coupon.snapshot_name', read_only=True)
    user_nickname = serializers.CharField(source='user_coupon.user.nickname',
                                          read_only=True, default='')

    class Meta:
        model = RedemptionLog
        fields = [
            'id', 'user_coupon', 'coupon_code', 'coupon_name', 'user_nickname',
            'actor_type', 'actor_id', 'actor_name',
            'action', 'action_display',
            'amount', 'remark', 'ip_address', 'created_at',
        ]