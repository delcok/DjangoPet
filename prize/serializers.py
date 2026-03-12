# -*- coding: utf-8 -*-
# @Time    : 2026/3/12 15:57
# @Author  : Delock

from django.utils import timezone
from rest_framework import serializers

from user.models import User, UserAddress
from .models import Prize, UserPrize, UserPrizeLog


class PrizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prize
        fields = '__all__'
        read_only_fields = ('created_by', 'updated_by', 'created_at', 'updated_at')


class PrizeListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prize
        fields = (
            'id', 'name', 'prize_type', 'title', 'subtitle', 'cover',
            'need_address', 'need_appointment', 'status',
            'start_time', 'end_time', 'valid_days', 'created_at'
        )


class UserPrizeLogSerializer(serializers.ModelSerializer):
    operator_staff_name = serializers.SerializerMethodField()

    class Meta:
        model = UserPrizeLog
        fields = (
            'id', 'action', 'operator_staff', 'operator_staff_name',
            'old_status', 'new_status', 'note', 'created_at'
        )

    def get_operator_staff_name(self, obj):
        return obj.operator_staff.username if obj.operator_staff else ''


class UserPrizeSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_phone = serializers.SerializerMethodField()
    prize_name = serializers.CharField(source='prize_snapshot_name', read_only=True)
    prize_type = serializers.CharField(source='prize_snapshot_type', read_only=True)
    logs = UserPrizeLogSerializer(many=True, read_only=True)

    class Meta:
        model = UserPrize
        fields = '__all__'

    def get_user_name(self, obj):
        return obj.user.display_name if obj.user else ''

    def get_user_phone(self, obj):
        return obj.user.phone if obj.user else ''


class UserPrizeListSerializer(serializers.ModelSerializer):
    prize_name = serializers.CharField(source='prize_snapshot_name', read_only=True)
    prize_type = serializers.CharField(source='prize_snapshot_type', read_only=True)

    class Meta:
        model = UserPrize
        fields = (
            'id', 'prize_name', 'prize_type', 'title', 'subtitle', 'cover',
            'status', 'exchange_code', 'issued_at', 'valid_start_time',
            'valid_end_time', 'claimed_at', 'redeemed_at'
        )


class AdminIssuePrizeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    prize_id = serializers.IntegerField(required=True)
    valid_start_time = serializers.DateTimeField(required=False, allow_null=True)
    valid_end_time = serializers.DateTimeField(required=False, allow_null=True)
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(choices=UserPrize.SOURCE_CHOICES, required=False, default='manual')

    def validate(self, attrs):
        try:
            user = User.objects.get(id=attrs['user_id'], is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('用户不存在或已禁用')

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
    user_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    prize_id = serializers.IntegerField(required=True)
    valid_start_time = serializers.DateTimeField(required=False, allow_null=True)
    valid_end_time = serializers.DateTimeField(required=False, allow_null=True)
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(choices=UserPrize.SOURCE_CHOICES, required=False, default='manual')
    batch_no = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        user_ids = list(set(attrs['user_ids']))
        users = User.objects.filter(id__in=user_ids, is_active=True)

        if not users.exists():
            raise serializers.ValidationError('没有可发放的有效用户')

        user_map = {u.id: u for u in users}
        missing_ids = [uid for uid in user_ids if uid not in user_map]
        if missing_ids:
            raise serializers.ValidationError(f'以下用户不存在或已禁用: {missing_ids}')

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


class AdminStatusUpdateSerializer(serializers.Serializer):
    admin_remark = serializers.CharField(required=False, allow_blank=True, default='')
    note = serializers.CharField(required=False, allow_blank=True, default='')
