# -*- coding: utf-8 -*-
# @Time    : 2026/3/12 15:57
# @Author  : Delock

from django.utils import timezone
from rest_framework import serializers

from user.models import User
from address.models import UserAddress
from merchants.models import Merchant
from .models import Prize, UserPrize, UserPrizeLog


def get_user_display_name(user):
    if not user:
        return ''

    return (
        getattr(user, 'display_name', None)
        or getattr(user, 'username', None)
        or getattr(user, 'nickname', None)
        or ''
    )


def get_operator_display_name(operator):
    if not operator:
        return ''

    return (
        getattr(operator, 'username', None)
        or getattr(operator, 'name', None)
        or getattr(operator, 'company_name', None)
        or getattr(operator, 'shop_name', None)
        or str(operator)
    )


class MerchantSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ['id', 'name', 'status']


class PrizeListSerializer(serializers.ModelSerializer):
    merchant_info = serializers.SerializerMethodField()
    owner_type_display = serializers.CharField(source='get_owner_type_display', read_only=True)
    prize_type_display = serializers.CharField(source='get_prize_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Prize
        fields = (
            'id',
            'owner_type',
            'owner_type_display',
            'merchant',
            'merchant_info',
            'name',
            'prize_type',
            'prize_type_display',
            'title',
            'subtitle',
            'cover',
            'need_address',
            'need_appointment',
            'status',
            'status_display',
            'start_time',
            'end_time',
            'valid_days',
            'sort',
            'created_at',
            'updated_at',
        )

    def get_merchant_info(self, obj):
        if not obj.merchant:
            return None

        return {
            'id': obj.merchant.id,
            'name': getattr(obj.merchant, 'name', '') or str(obj.merchant),
            'status': getattr(obj.merchant, 'status', ''),
        }


class AdminPrizeSerializer(serializers.ModelSerializer):
    merchant_id = serializers.PrimaryKeyRelatedField(
        source='merchant',
        queryset=Merchant.objects.all(),
        required=False,
        allow_null=True,
        write_only=True
    )
    merchant_info = serializers.SerializerMethodField()
    owner_type_display = serializers.CharField(source='get_owner_type_display', read_only=True)
    prize_type_display = serializers.CharField(source='get_prize_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Prize
        fields = '__all__'
        read_only_fields = (
            'merchant',
            'created_by_manager',
            'updated_by_manager',
            'created_by_merchant',
            'updated_by_merchant',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        prize_type = attrs.get('prize_type', getattr(self.instance, 'prize_type', None))
        need_address = attrs.get('need_address', getattr(self.instance, 'need_address', False))

        if prize_type == 'physical' and not need_address:
            raise serializers.ValidationError('实物类奖品必须需要收货地址')

        start_time = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = attrs.get('end_time', getattr(self.instance, 'end_time', None))

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError('可领取开始时间必须小于结束时间')

        valid_days = attrs.get('valid_days', getattr(self.instance, 'valid_days', None))
        if valid_days is not None and valid_days == 0:
            raise serializers.ValidationError('有效天数必须大于 0')

        owner_type = attrs.get('owner_type', getattr(self.instance, 'owner_type', 'platform'))
        merchant = attrs.get('merchant', getattr(self.instance, 'merchant', None))

        if merchant:
            attrs['owner_type'] = 'merchant'
        elif owner_type == 'merchant':
            raise serializers.ValidationError('商户奖品必须传入 merchant_id')
        else:
            attrs['owner_type'] = 'platform'
            attrs['merchant'] = None

        return attrs

    def get_merchant_info(self, obj):
        if not obj.merchant:
            return None

        return {
            'id': obj.merchant.id,
            'name': getattr(obj.merchant, 'name', '') or str(obj.merchant),
            'status': getattr(obj.merchant, 'status', ''),
        }


class MerchantPrizeSerializer(serializers.ModelSerializer):
    merchant_info = serializers.SerializerMethodField()
    owner_type_display = serializers.CharField(source='get_owner_type_display', read_only=True)
    prize_type_display = serializers.CharField(source='get_prize_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Prize
        fields = '__all__'
        read_only_fields = (
            'owner_type',
            'merchant',
            'created_by_manager',
            'updated_by_manager',
            'created_by_merchant',
            'updated_by_merchant',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        prize_type = attrs.get('prize_type', getattr(self.instance, 'prize_type', None))
        need_address = attrs.get('need_address', getattr(self.instance, 'need_address', False))

        if prize_type == 'physical' and not need_address:
            raise serializers.ValidationError('实物类奖品必须需要收货地址')

        start_time = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = attrs.get('end_time', getattr(self.instance, 'end_time', None))

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError('可领取开始时间必须小于结束时间')

        valid_days = attrs.get('valid_days', getattr(self.instance, 'valid_days', None))
        if valid_days is not None and valid_days == 0:
            raise serializers.ValidationError('有效天数必须大于 0')

        return attrs

    def get_merchant_info(self, obj):
        if not obj.merchant:
            return None

        return {
            'id': obj.merchant.id,
            'name': getattr(obj.merchant, 'name', '') or str(obj.merchant),
            'status': getattr(obj.merchant, 'status', ''),
        }


class UserPrizeLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    operator_type_display = serializers.CharField(source='get_operator_type_display', read_only=True)
    operator_display_name = serializers.SerializerMethodField()

    class Meta:
        model = UserPrizeLog
        fields = (
            'id',
            'action',
            'action_display',
            'operator_type',
            'operator_type_display',
            'operator_name',
            'operator_display_name',
            'old_status',
            'new_status',
            'note',
            'created_at',
        )

    def get_operator_display_name(self, obj):
        if obj.operator_name:
            return obj.operator_name

        if obj.operator_manager:
            return get_operator_display_name(obj.operator_manager)

        if obj.operator_merchant:
            return get_operator_display_name(obj.operator_merchant)

        return obj.get_operator_type_display()


class UserPrizeSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_phone = serializers.SerializerMethodField()
    merchant_info = serializers.SerializerMethodField()

    prize_name = serializers.CharField(source='prize_snapshot_name', read_only=True)
    prize_type = serializers.CharField(source='prize_snapshot_type', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)

    logs = UserPrizeLogSerializer(many=True, read_only=True)

    class Meta:
        model = UserPrize
        fields = '__all__'

    def get_user_name(self, obj):
        return get_user_display_name(obj.user)

    def get_user_phone(self, obj):
        return getattr(obj.user, 'phone', '') if obj.user else ''

    def get_merchant_info(self, obj):
        if not obj.merchant:
            return None

        return {
            'id': obj.merchant.id,
            'name': getattr(obj.merchant, 'name', '') or str(obj.merchant),
            'status': getattr(obj.merchant, 'status', ''),
        }


class UserPrizeListSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_phone = serializers.SerializerMethodField()
    merchant_info = serializers.SerializerMethodField()

    prize_name = serializers.CharField(source='prize_snapshot_name', read_only=True)
    prize_type = serializers.CharField(source='prize_snapshot_type', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = UserPrize
        fields = (
            'id',
            'user',
            'user_name',
            'user_phone',
            'merchant',
            'merchant_info',
            'prize',
            'prize_name',
            'prize_type',
            'title',
            'subtitle',
            'cover',
            'status',
            'status_display',
            'source',
            'source_display',
            'exchange_code',
            'batch_no',
            'issued_at',
            'valid_start_time',
            'valid_end_time',
            'read_at',
            'claimed_at',
            'redeemed_at',
            'created_at',
        )

    def get_user_name(self, obj):
        return get_user_display_name(obj.user)

    def get_user_phone(self, obj):
        return getattr(obj.user, 'phone', '') if obj.user else ''

    def get_merchant_info(self, obj):
        if not obj.merchant:
            return None

        return {
            'id': obj.merchant.id,
            'name': getattr(obj.merchant, 'name', '') or str(obj.merchant),
            'status': getattr(obj.merchant, 'status', ''),
        }


class AdminIssuePrizeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    prize_id = serializers.IntegerField(required=True)
    valid_start_time = serializers.DateTimeField(required=False, allow_null=True)
    valid_end_time = serializers.DateTimeField(required=False, allow_null=True)
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(
        choices=UserPrize.SOURCE_CHOICES,
        required=False,
        default='manual'
    )

    def validate(self, attrs):
        try:
            user = User.objects.get(id=attrs['user_id'], is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('用户不存在或已禁用')

        if getattr(user, 'is_banned', False):
            raise serializers.ValidationError('用户已被封禁，不能发放奖品')

        try:
            prize = Prize.objects.get(id=attrs['prize_id'], status='active')
        except Prize.DoesNotExist:
            raise serializers.ValidationError('奖品不存在或未启用')

        valid_start_time = attrs.get('valid_start_time')
        valid_end_time = attrs.get('valid_end_time')

        if valid_start_time and valid_end_time and valid_start_time >= valid_end_time:
            raise serializers.ValidationError('有效开始时间必须小于有效结束时间')

        attrs['user'] = user
        attrs['prize'] = prize

        return attrs


class AdminBatchIssuePrizeSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )
    prize_id = serializers.IntegerField(required=True)
    valid_start_time = serializers.DateTimeField(required=False, allow_null=True)
    valid_end_time = serializers.DateTimeField(required=False, allow_null=True)
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(
        choices=UserPrize.SOURCE_CHOICES,
        required=False,
        default='manual'
    )
    batch_no = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        user_ids = list(set(attrs['user_ids']))

        users = User.objects.filter(
            id__in=user_ids,
            is_active=True
        ).exclude(
            is_banned=True
        )

        if not users.exists():
            raise serializers.ValidationError('没有可发放的有效用户')

        user_map = {user.id: user for user in users}
        missing_ids = [uid for uid in user_ids if uid not in user_map]

        if missing_ids:
            raise serializers.ValidationError(f'以下用户不存在、已禁用或已封禁: {missing_ids}')

        try:
            prize = Prize.objects.get(id=attrs['prize_id'], status='active')
        except Prize.DoesNotExist:
            raise serializers.ValidationError('奖品不存在或未启用')

        valid_start_time = attrs.get('valid_start_time')
        valid_end_time = attrs.get('valid_end_time')

        if valid_start_time and valid_end_time and valid_start_time >= valid_end_time:
            raise serializers.ValidationError('有效开始时间必须小于有效结束时间')

        attrs['users'] = list(users)
        attrs['prize'] = prize

        return attrs


class MerchantIssuePrizeSerializer(AdminIssuePrizeSerializer):
    def validate(self, attrs):
        merchant = self.context['merchant']

        try:
            user = User.objects.get(id=attrs['user_id'], is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('用户不存在或已禁用')

        if getattr(user, 'is_banned', False):
            raise serializers.ValidationError('用户已被封禁，不能发放奖品')

        try:
            prize = Prize.objects.get(
                id=attrs['prize_id'],
                status='active',
                owner_type='merchant',
                merchant=merchant
            )
        except Prize.DoesNotExist:
            raise serializers.ValidationError('奖品不存在、未启用，或不属于当前商户')

        valid_start_time = attrs.get('valid_start_time')
        valid_end_time = attrs.get('valid_end_time')

        if valid_start_time and valid_end_time and valid_start_time >= valid_end_time:
            raise serializers.ValidationError('有效开始时间必须小于有效结束时间')

        attrs['user'] = user
        attrs['prize'] = prize

        return attrs


class MerchantBatchIssuePrizeSerializer(AdminBatchIssuePrizeSerializer):
    def validate(self, attrs):
        merchant = self.context['merchant']
        user_ids = list(set(attrs['user_ids']))

        users = User.objects.filter(
            id__in=user_ids,
            is_active=True
        ).exclude(
            is_banned=True
        )

        if not users.exists():
            raise serializers.ValidationError('没有可发放的有效用户')

        user_map = {user.id: user for user in users}
        missing_ids = [uid for uid in user_ids if uid not in user_map]

        if missing_ids:
            raise serializers.ValidationError(f'以下用户不存在、已禁用或已封禁: {missing_ids}')

        try:
            prize = Prize.objects.get(
                id=attrs['prize_id'],
                status='active',
                owner_type='merchant',
                merchant=merchant
            )
        except Prize.DoesNotExist:
            raise serializers.ValidationError('奖品不存在、未启用，或不属于当前商户')

        valid_start_time = attrs.get('valid_start_time')
        valid_end_time = attrs.get('valid_end_time')

        if valid_start_time and valid_end_time and valid_start_time >= valid_end_time:
            raise serializers.ValidationError('有效开始时间必须小于有效结束时间')

        attrs['users'] = list(users)
        attrs['prize'] = prize

        return attrs


class UserPrizeClaimSerializer(serializers.Serializer):
    contact_name = serializers.CharField(required=False, allow_blank=True, default='')
    contact_phone = serializers.CharField(required=False, allow_blank=True, default='')
    address_id = serializers.IntegerField(required=False, allow_null=True)
    user_remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        user_prize = self.context['user_prize']
        request = self.context['request']

        if user_prize.status != 'pending':
            raise serializers.ValidationError('当前状态不可申请兑奖')

        now = timezone.now()

        if user_prize.valid_start_time and now < user_prize.valid_start_time:
            raise serializers.ValidationError('该奖品尚未到可领取时间')

        if user_prize.valid_end_time and now > user_prize.valid_end_time:
            raise serializers.ValidationError('该奖品已过期')

        if user_prize.need_address:
            address_id = attrs.get('address_id')

            if not address_id:
                raise serializers.ValidationError('该奖品必须填写收货地址')

            try:
                address = UserAddress.objects.get(id=address_id, user=request.user)
            except UserAddress.DoesNotExist:
                raise serializers.ValidationError('地址不存在')

            attrs['address'] = address

        return attrs

class StatusUpdateSerializer(serializers.Serializer):
    """状态变更基类：后台备注 + 日志备注"""
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    note = serializers.CharField(required=False, allow_blank=True, default='')


class AdminStatusUpdateSerializer(StatusUpdateSerializer):
    """管理员：可写后台备注 + 日志备注"""
    pass


class MerchantStatusUpdateSerializer(serializers.Serializer):
    """商户：仅日志备注，不允许写后台备注"""
    note = serializers.CharField(required=False, allow_blank=True, default='')