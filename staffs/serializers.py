# -*- coding: utf-8 -*-
# @Time    : 2026/4/14 19:10
# @Author  : Delock

import re

from django.utils import timezone
from rest_framework import serializers

from .models import Staff, StaffSchedule, StaffTimeSlot


# ══════════════════════════════════════════════════════════════
# 公共校验 / 脱敏
# ══════════════════════════════════════════════════════════════

# 基础校验:15 位纯数字 或 17 位数字 + 末位 0-9/X/x
ID_CARD_RE = re.compile(r'^\d{15}$|^\d{17}[\dXx]$')


def validate_id_card_no(value):
    """身份证号基础校验:长度 + 数字/末位 X(不做校验位运算)"""
    if not value:
        return value
    if not ID_CARD_RE.match(value):
        raise serializers.ValidationError('身份证号格式不正确(15位或18位,末位可为X)')
    return value


def mask_id_card(value: str) -> str:
    """
    身份证号脱敏:保留前6后4
    18位: 110101********1234
    15位: 110101*****1234
    其他短串: 首尾各保留1位
    """
    if not value:
        return ''
    s = str(value)
    if len(s) >= 10:
        return s[:6] + '*' * (len(s) - 10) + s[-4:]
    if len(s) >= 4:
        return s[:1] + '*' * (len(s) - 2) + s[-1:]
    return '*' * len(s)


# ══════════════════════════════════════════════════════════════
# 认证相关
# ══════════════════════════════════════════════════════════════

class StaffSendSMSSerializer(serializers.Serializer):
    phone = serializers.RegexField(r'^\d{11}$', error_messages={'invalid': '手机号格式不正确'})
    scene = serializers.ChoiceField(choices=['login', 'reset_password'])


class StaffPasswordLoginSerializer(serializers.Serializer):
    phone    = serializers.RegexField(r'^\d{11}$', error_messages={'invalid': '手机号格式不正确'})
    password = serializers.CharField(min_length=6)


class StaffSMSLoginSerializer(serializers.Serializer):
    phone = serializers.RegexField(r'^\d{11}$', error_messages={'invalid': '手机号格式不正确'})
    code  = serializers.CharField(min_length=6, max_length=6)


class StaffResetPasswordSerializer(serializers.Serializer):
    phone        = serializers.RegexField(r'^\d{11}$')
    code         = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(min_length=6, max_length=64)


class StaffChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(min_length=6)
    new_password = serializers.CharField(min_length=6, max_length=64)


# ══════════════════════════════════════════════════════════════
# 员工自身视图(身份证号脱敏)
# ══════════════════════════════════════════════════════════════

class StaffProfileSerializer(serializers.ModelSerializer):
    """
    员工查看自己的信息
    id_card_no 脱敏返回,防止设备截图/共享屏幕造成泄露
    商家端见 StaffDetailSerializer 返回完整身份证号
    """
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    full_address  = serializers.CharField(read_only=True)
    # 身份证号:脱敏
    id_card_no       = serializers.SerializerMethodField()
    # 待审核字段中的身份证号也要脱敏
    pending_changes  = serializers.SerializerMethodField()

    class Meta:
        model  = Staff
        fields = [
            'id', 'merchant_name',

            # 基础展示
            'name', 'avatar', 'gender', 'birthday', 'introduction',
            'specialties', 'certificates', 'employee_no',
            'phone', 'work_status',

            # 实名(已审核通过的当前值)
            'real_name', 'id_card_no',
            'id_card_front', 'id_card_back', 'health_certificate',

            # 住址
            'province', 'city', 'district', 'address', 'full_address',
            'home_longitude', 'home_latitude',

            # HR
            'hire_date', 'leave_date', 'work_years',
            'emergency_contact_name', 'emergency_contact_phone',

            # 服务能力
            'service_radius', 'can_handle_urgent', 'can_receive_transfer',
            'max_concurrent_orders',

            # 排班(员工查看自己的默认周模板和特殊休息日)
            'work_schedule', 'rest_dates',

            # 评分
            'rating', 'total_orders', 'monthly_orders',
            'total_reviews', 'good_review_rate',
            'is_recommended', 'recommend_reason',

            # 实名审核状态
            'verification_status', 'pending_changes',
            'verification_remark', 'verification_submitted_at',
            'verified_at',

            'status', 'last_login', 'created_at',
        ]

    def get_id_card_no(self, obj):
        return mask_id_card(obj.id_card_no)

    def get_pending_changes(self, obj):
        """脱敏待审核字段中的敏感信息(目前仅 id_card_no)"""
        changes = dict(obj.pending_changes or {})
        if changes.get('id_card_no'):
            changes['id_card_no'] = mask_id_card(changes['id_card_no'])
        return changes


class StaffUpdateSelfSerializer(serializers.ModelSerializer):
    """
    员工更新自己的非敏感信息
    实名/住址/HR 等敏感字段必须走 verification 接口,这里禁止直接改
    """

    class Meta:
        model  = Staff
        fields = [
            'name', 'avatar', 'gender', 'introduction', 'specialties',
            'work_status', 'can_receive_transfer',
            'current_location_lng', 'current_location_lat',
        ]

    def update(self, instance, validated_data):
        if 'current_location_lng' in validated_data or 'current_location_lat' in validated_data:
            validated_data['location_updated_at'] = timezone.now()
        return super().update(instance, validated_data)


class StaffSubmitVerificationSerializer(serializers.Serializer):
    """
    员工提交实名/住址/个人信息审核
    所有字段可选,支持部分提交
    多次部分提交会累积合并到同一份待审核中,直到商家审核
    """
    real_name              = serializers.CharField(required=False, allow_blank=True, max_length=50)
    id_card_no             = serializers.CharField(required=False, allow_blank=True, max_length=20)
    id_card_front          = serializers.CharField(required=False, allow_blank=True, max_length=255)
    id_card_back           = serializers.CharField(required=False, allow_blank=True, max_length=255)
    health_certificate     = serializers.CharField(required=False, allow_blank=True, max_length=255)

    province = serializers.CharField(required=False, allow_blank=True, max_length=50)
    city     = serializers.CharField(required=False, allow_blank=True, max_length=50)
    district = serializers.CharField(required=False, allow_blank=True, max_length=50)
    address  = serializers.CharField(required=False, allow_blank=True, max_length=255)
    home_longitude = serializers.DecimalField(
        required=False, allow_null=True, max_digits=10, decimal_places=7
    )
    home_latitude = serializers.DecimalField(
        required=False, allow_null=True, max_digits=10, decimal_places=7
    )

    birthday   = serializers.DateField(required=False, allow_null=True)
    work_years = serializers.IntegerField(required=False, min_value=0, max_value=80)
    emergency_contact_name  = serializers.CharField(required=False, allow_blank=True, max_length=50)
    emergency_contact_phone = serializers.CharField(required=False, allow_blank=True, max_length=17)

    def validate_id_card_no(self, value):
        return validate_id_card_no(value)

    def validate(self, attrs):
        if not any(v not in (None, '') for v in attrs.values()):
            raise serializers.ValidationError('至少需要提交一个字段')
        return attrs


class StaffVerificationReviewSerializer(serializers.Serializer):
    """商家端审核 approve / reject"""
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    remark = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        if attrs['action'] == 'reject' and not attrs.get('remark'):
            raise serializers.ValidationError({'remark': '拒绝时必须填写原因'})
        return attrs


# ══════════════════════════════════════════════════════════════
# 商家端 - 员工管理(身份证号完整,商家需核对)
# ══════════════════════════════════════════════════════════════

class StaffListSerializer(serializers.ModelSerializer):
    """商家端 - 员工列表"""

    class Meta:
        model  = Staff
        fields = [
            'id', 'name', 'real_name',
            'avatar', 'gender', 'phone', 'employee_no',
            'work_status', 'status',
            'verification_status',
            'rating', 'total_orders', 'monthly_orders', 'good_review_rate',
            'dispatch_weight', 'is_recommended', 'sort_order',
            'can_handle_urgent', 'can_receive_transfer',
            'hire_date',
            'created_at',
        ]


class StaffDetailSerializer(serializers.ModelSerializer):
    """
    商家端 - 员工详情(全字段,id_card_no 完整返回)
    商家需要核对身份证图片和号码,所以这里不脱敏
    """
    service_categories = serializers.SerializerMethodField()
    full_address = serializers.CharField(read_only=True)

    class Meta:
        model  = Staff
        fields = [
            'id',
            'name', 'real_name', 'avatar', 'gender', 'birthday',
            'phone', 'employee_no',
            'introduction', 'specialties', 'certificates',

            # 实名(完整,不脱敏)
            'id_card_no', 'id_card_front', 'id_card_back', 'health_certificate',

            # 住址
            'province', 'city', 'district', 'address', 'full_address',
            'home_longitude', 'home_latitude',

            # HR
            'hire_date', 'leave_date', 'work_years',
            'emergency_contact_name', 'emergency_contact_phone',

            'work_status', 'status',
            'service_categories', 'service_radius',
            'max_concurrent_orders', 'can_handle_urgent', 'can_receive_transfer',
            'work_schedule', 'rest_dates',
            'rating', 'total_orders', 'monthly_orders',
            'total_reviews', 'good_review_rate',
            'dispatch_weight', 'avg_response_minutes', 'acceptance_rate',
            'is_recommended', 'sort_order', 'recommend_reason',
            'current_location_lng', 'current_location_lat', 'location_updated_at',

            # 实名审核
            'verification_status', 'pending_changes',
            'verification_remark', 'verification_submitted_at',
            'verified_at', 'verified_by',

            'last_login', 'created_at', 'updated_at',
        ]

    def get_service_categories(self, obj):
        return list(obj.service_categories.values('id', 'name'))


class StaffCreateSerializer(serializers.ModelSerializer):
    """
    商家端 - 创建员工

    支持两种创建模式:

    ① 最小账号(推荐,鼓励员工自助补全):
       仅传 name + phone + password
       结果: verification_status = UNVERIFIED
       后续: 员工登录后 POST /api/staff/profile/verification/ 提交身份证/住址等
            → 状态变 PENDING(此时不参与自动派单)
            → 商家 POST .../review_verification/ 审核
            → 通过后状态 APPROVED,字段生效

    ② 完整代填(商家直接录入员工资料):
       同时传 real_name + id_card_no + 其他字段
       结果: verification_status = APPROVED(商家代填视为已审核,跳过审核流程)
       后续: 员工登录可直接接单,商家可随时通过 PUT 修改任意字段
    """
    password = serializers.CharField(min_length=6, max_length=64, write_only=True)
    service_category_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model  = Staff
        fields = [
            'id',  # 响应返回

            # 必填
            'name', 'phone', 'password',

            # 可选(全部可在创建后由员工提交或商家更新补充)
            'real_name', 'gender', 'birthday',
            'avatar', 'introduction', 'specialties', 'certificates', 'employee_no',

            'id_card_no', 'id_card_front', 'id_card_back', 'health_certificate',

            'province', 'city', 'district', 'address',
            'home_longitude', 'home_latitude',

            'hire_date', 'work_years',
            'emergency_contact_name', 'emergency_contact_phone',

            'service_category_ids',
            'max_concurrent_orders', 'service_radius',
            'can_handle_urgent', 'can_receive_transfer',
            'work_schedule', 'rest_dates',
            'is_recommended', 'sort_order', 'recommend_reason',
            'dispatch_weight',

            # 响应附带,告诉商家创建后的认证状态
            'verification_status',
        ]
        read_only_fields = ['id', 'verification_status']

    def validate_phone(self, value):
        merchant = self.context['merchant']
        if Staff.objects.filter(merchant=merchant, phone=value).exists():
            raise serializers.ValidationError('该手机号已在本商家注册')
        return value

    def validate_id_card_no(self, value):
        return validate_id_card_no(value)

    def create(self, validated_data):
        raw_password         = validated_data.pop('password')
        service_category_ids = validated_data.pop('service_category_ids', [])
        merchant             = self.context['merchant']

        staff = Staff(merchant=merchant, **validated_data)
        staff.set_password(raw_password)

        # 商家创建时若同时填了真实姓名+身份证号,视为审核通过
        # 否则 verification_status 保持默认 UNVERIFIED,等员工自助提交
        if validated_data.get('real_name') and validated_data.get('id_card_no'):
            staff.verification_status = Staff.VerificationStatus.APPROVED
            staff.verified_at = timezone.now()
            staff.verified_by = self.context.get('reviewer', '商家创建')

        staff.save()

        if service_category_ids:
            staff.service_categories.set(service_category_ids)

        return staff


class StaffAdminUpdateSerializer(serializers.ModelSerializer):
    """
    商家端 - 更新员工信息(全字段编辑,不走审核流程,字段立即生效)
    商家拥有全部修改权限,无论 verification_status 处于何种状态
    """
    service_category_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model  = Staff
        fields = [
            'name', 'real_name', 'gender', 'birthday',
            'avatar', 'introduction', 'specialties', 'certificates',
            'employee_no',

            'id_card_no', 'id_card_front', 'id_card_back', 'health_certificate',

            'province', 'city', 'district', 'address',
            'home_longitude', 'home_latitude',

            'hire_date', 'leave_date', 'work_years',
            'emergency_contact_name', 'emergency_contact_phone',

            'service_category_ids',
            'max_concurrent_orders', 'service_radius',
            'can_handle_urgent', 'can_receive_transfer',
            'work_schedule', 'rest_dates',
            'status',
            'is_recommended', 'sort_order', 'recommend_reason',
            'dispatch_weight',
        ]

    def validate_id_card_no(self, value):
        return validate_id_card_no(value)

    def update(self, instance, validated_data):
        service_category_ids = validated_data.pop('service_category_ids', None)
        instance = super().update(instance, validated_data)
        if service_category_ids is not None:
            instance.service_categories.set(service_category_ids)
        return instance


class StaffResetPasswordByMerchantSerializer(serializers.Serializer):
    """商家端 - 重置员工密码"""
    password = serializers.CharField(min_length=6, max_length=64)


# ══════════════════════════════════════════════════════════════
# 排班相关
# ══════════════════════════════════════════════════════════════

class StaffScheduleSerializer(serializers.ModelSerializer):

    class Meta:
        model  = StaffSchedule
        fields = [
            'id', 'date', 'is_working',
            'start_time', 'end_time',
            'break_start', 'break_end',
            'max_orders', 'source', 'note',
        ]
        read_only_fields = ['id', 'source']

    def create(self, validated_data):
        validated_data['source'] = StaffSchedule.Source.MANUAL
        return super().create(validated_data)


# ══════════════════════════════════════════════════════════════
# 时间槽(只读,用于调度查询)
# ══════════════════════════════════════════════════════════════

class StaffTimeSlotSerializer(serializers.ModelSerializer):
    order_no = serializers.CharField(source='service_order.order_no', read_only=True)

    class Meta:
        model  = StaffTimeSlot
        fields = ['id', 'order_no', 'date', 'start_time', 'end_time', 'status']