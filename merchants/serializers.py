# -*- coding: utf-8 -*-
import re
from rest_framework import serializers
from .models import Merchant, MerchantCategory, BusinessDistrict, MerchantSubAccount


def validate_phone(value):
    if not re.match(r'^1[3-9]\d{9}$', value):
        raise serializers.ValidationError('请输入正确的手机号')
    return value


def validate_password(value):
    if len(value) < 6:
        raise serializers.ValidationError('密码长度不能少于6位')
    if len(value) > 20:
        raise serializers.ValidationError('密码长度不能超过20位')
    return value


# ══════════════════════════════════════════════════════════════
# 登录相关
# ══════════════════════════════════════════════════════════════

class SendSMSCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=17, validators=[validate_phone])
    scene = serializers.ChoiceField(
        choices=['login', 'register', 'reset_password', 'bind_phone', 'change_bank'],
        default='login'
    )


class PasswordLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=17, validators=[validate_phone])
    password = serializers.CharField(min_length=6, max_length=20, write_only=True)


class SMSLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=17, validators=[validate_phone])
    code = serializers.CharField(min_length=4, max_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=17, validators=[validate_phone])
    code = serializers.CharField(min_length=4, max_length=6)
    new_password = serializers.CharField(
        min_length=6, max_length=20,
        write_only=True,
        validators=[validate_password]
    )


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        min_length=6, max_length=20,
        write_only=True,
        validators=[validate_password]
    )


# ══════════════════════════════════════════════════════════════
# 分类与商圈
# ══════════════════════════════════════════════════════════════

class MerchantCategorySerializer(serializers.ModelSerializer):
    merchant_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MerchantCategory
        fields = ['id', 'name', 'icon', 'sort_order', 'merchant_count', 'is_active']


class MerchantCategoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantCategory
        fields = '__all__'


class BusinessDistrictSerializer(serializers.ModelSerializer):
    merchant_count = serializers.IntegerField(read_only=True)
    region_display = serializers.CharField(read_only=True)

    class Meta:
        model = BusinessDistrict
        fields = [
            'id', 'name', 'province', 'city', 'district', 'address',
            'longitude', 'latitude', 'radius',
            'heat_score', 'is_active', 'merchant_count', 'region_display'
        ]


class BusinessDistrictAdminSerializer(serializers.ModelSerializer):
    merchant_count = serializers.IntegerField(read_only=True)
    region_display = serializers.CharField(read_only=True)
    full_address = serializers.CharField(read_only=True)

    class Meta:
        model = BusinessDistrict
        fields = [
            'id', 'name', 'province', 'city', 'district', 'address',
            'longitude', 'latitude', 'radius',
            'boundary', 'heat_score', 'sort_order',
            'is_active', 'merchant_count',
            'region_display', 'full_address',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_boundary(self, value):
        """
        ✅ 修复 #15: 校验 boundary JSON 格式
        要求: list of [lng, lat] 数对,长度 >= 3 才构成有效多边形
        """
        if value is None:
            return value
        if not isinstance(value, list):
            raise serializers.ValidationError('boundary 必须是数组')
        if len(value) > 0 and len(value) < 3:
            raise serializers.ValidationError('多边形顶点至少 3 个')
        for i, pt in enumerate(value):
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise serializers.ValidationError(
                    f'第 {i+1} 个顶点格式错误,应为 [lng, lat]'
                )
            try:
                lng = float(pt[0])
                lat = float(pt[1])
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    f'第 {i+1} 个顶点的经纬度必须是数字'
                )
            if not (-180 <= lng <= 180):
                raise serializers.ValidationError(
                    f'第 {i+1} 个顶点经度超出范围'
                )
            if not (-90 <= lat <= 90):
                raise serializers.ValidationError(
                    f'第 {i+1} 个顶点纬度超出范围'
                )
        return value


class BusinessDistrictDetailSerializer(serializers.ModelSerializer):
    merchant_count = serializers.IntegerField(read_only=True)
    full_address = serializers.CharField(read_only=True)
    region_display = serializers.CharField(read_only=True)

    class Meta:
        model = BusinessDistrict
        fields = '__all__'


class BusinessDistrictSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessDistrict
        fields = ['id', 'name', 'province', 'city', 'district']


# ══════════════════════════════════════════════════════════════
# 商家 - 用户端
# ══════════════════════════════════════════════════════════════

class MerchantListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    district_name = serializers.CharField(
        source='business_district.name',
        read_only=True,
        default=''
    )
    distance = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = [
            'id', 'name', 'logo', 'description',
            'category_name', 'district_name',
            'address', 'longitude', 'latitude',
            'rating', 'monthly_sales', 'total_sales',
            'delivery_fee', 'free_delivery_threshold', 'min_order_amount',
            'is_open', 'is_recommended',
            'support_home_delivery', 'support_self_pickup',
            'distance'
        ]

    def get_distance(self, obj):
        request = self.context.get('request')
        if not request:
            return None

        user_lng = request.query_params.get('longitude')
        user_lat = request.query_params.get('latitude')

        if not (user_lng and user_lat and obj.longitude and obj.latitude):
            return None

        try:
            from math import radians, sin, cos, sqrt, atan2

            lng1, lat1 = float(user_lng), float(user_lat)
            lng2, lat2 = float(obj.longitude), float(obj.latitude)

            R = 6371000

            lat1, lat2, lng1, lng2 = map(radians, [lat1, lat2, lng1, lng2])
            dlat = lat2 - lat1
            dlng = lng2 - lng1

            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            distance = R * c

            if distance < 1000:
                return f"{int(distance)}m"
            else:
                return f"{distance / 1000:.1f}km"
        except (TypeError, ValueError):
            return None


class MerchantDetailSerializer(serializers.ModelSerializer):
    category = MerchantCategorySerializer(read_only=True)
    business_district = BusinessDistrictSerializer(read_only=True)

    class Meta:
        model = Merchant
        fields = [
            'id', 'name', 'logo', 'images', 'description', 'announcement',
            'category', 'business_district',
            'contact_phone', 'address', 'full_address',
            'longitude', 'latitude',
            'business_hours', 'is_open',
            'support_home_delivery', 'support_self_pickup',
            'pickup_discount_type', 'pickup_discount_value', 'pickup_note',
            'delivery_fee', 'free_delivery_threshold', 'min_order_amount', 'delivery_range',
            'rating', 'monthly_sales', 'total_sales',
            'is_recommended'
        ]


# ══════════════════════════════════════════════════════════════
# 商家 - 商家端
# ══════════════════════════════════════════════════════════════

class MerchantProfileSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Merchant
        fields = [
            'id', 'name', 'logo', 'images', 'description', 'announcement',
            'category', 'category_name',
            'phone', 'contact_name', 'contact_phone',
            'province', 'city', 'district', 'address', 'full_address',
            'longitude', 'latitude',
            'business_hours', 'is_open',
            'support_home_delivery', 'support_self_pickup',
            'delivery_fee', 'free_delivery_threshold', 'min_order_amount', 'delivery_range',
            'rating', 'monthly_sales', 'total_sales',
            'status', 'status_display', 'reject_reason',
            'created_at'
        ]
        read_only_fields = [
            'id', 'phone', 'rating', 'monthly_sales', 'total_sales',
            'status', 'reject_reason', 'created_at'
        ]


class MerchantUpdateSerializer(serializers.ModelSerializer):
    """
    商家更新自身信息(仅限日常运营字段)
    地址/经纬度/分类/商圈/资质/结算 → 管理员改
    配送相关 → 走 /merchant/delivery-config/

    ✅ 修复 #6: 移除配送字段。
    旧版同时在这里和 MerchantDeliveryConfigSerializer 里暴露配送字段,
    商家可以走 profile 接口绕过配送配置的所有校验
    (如至少一种配送方式、distance_rules 格式等)。
    """

    class Meta:
        model = Merchant
        fields = [
            'name', 'logo', 'images', 'description', 'announcement',
            'contact_name', 'contact_phone',
            'business_hours', 'is_open',
            # 配送字段全部移除,统一走 delivery-config 接口
        ]

    def validate_images(self, value):
        if len(value) > 9:
            raise serializers.ValidationError('最多上传9张图片')
        return value


# ══════════════════════════════════════════════════════════════
# 商家 - 管理端
# ══════════════════════════════════════════════════════════════

class MerchantAdminListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    district_name = serializers.CharField(
        source='business_district.name',
        read_only=True,
        default=''
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Merchant
        fields = [
            'id', 'name', 'logo', 'phone',
            'category', 'category_name', 'contact_name', 'contact_phone',
            'business_district', 'district_name',
            'address', 'rating', 'monthly_sales',
            'longitude', 'latitude',
            'status', 'status_display',
            'is_open', 'is_recommended',
            # ✅ 修复 #13: 列表暴露配送方式,方便管理员一眼看到
            'support_home_delivery', 'support_self_pickup', 'freight_mode',
            'created_at'
        ]


class MerchantAdminDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    district_name = serializers.CharField(
        source='business_district.name',
        read_only=True,
        default=''
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Merchant
        fields = '__all__'
        read_only_fields = ['password', 'token_version']


class MerchantAdminUpdateSerializer(serializers.ModelSerializer):
    # 显式声明 phone,以便加额外校验
    phone = serializers.CharField(max_length=17, validators=[validate_phone])

    class Meta:
        model = Merchant
        fields = [
            'name', 'logo', 'images', 'description', 'announcement',
            'category', 'business_district',
            'phone',                           # ← 新增:登录手机号
            'contact_name', 'contact_phone',
            'province', 'city', 'district', 'address',
            'longitude', 'latitude',
            'business_hours', 'is_open',
            'delivery_fee', 'free_delivery_threshold', 'min_order_amount', 'delivery_range',
            'license_no', 'license_image', 'id_card_front', 'id_card_back',
            'bank_name', 'bank_account_name', 'bank_account_no',
            'commission_rate',
            'status', 'reject_reason',
            'is_recommended', 'recommend_sort', 'sort_order',
        ]

    def validate_phone(self, value):
        """登录手机号唯一性校验(排除自身)"""
        qs = Merchant.objects.filter(phone=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('该手机号已被其他商家占用')
        return value


class MerchantAuditSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    reject_reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        if attrs['action'] == 'reject' and not attrs.get('reject_reason'):
            raise serializers.ValidationError({'reject_reason': '拒绝时必须填写原因'})
        return attrs


# ══════════════════════════════════════════════════════════════
# 子账号
# ══════════════════════════════════════════════════════════════

class MerchantSubAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantSubAccount
        fields = [
            'id', 'name', 'phone', 'permissions',
            'is_active', 'last_login', 'created_at'
        ]


class MerchantSubAccountCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = MerchantSubAccount
        fields = ['name', 'phone', 'password', 'permissions', 'is_active']

    def validate_phone(self, value):
        validate_phone(value)
        merchant = self.context.get('merchant')
        if merchant and MerchantSubAccount.objects.filter(
                merchant=merchant, phone=value
        ).exists():
            raise serializers.ValidationError('该手机号已添加')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        sub_account = MerchantSubAccount(**validated_data)
        sub_account.set_password(password)
        sub_account.save()
        return sub_account


# ══════════════════════════════════════════════════════════════
# Token 响应
# ══════════════════════════════════════════════════════════════

class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    token_type = serializers.CharField(default='Bearer')
    expires_in = serializers.IntegerField()
    merchant = MerchantProfileSerializer()


class MerchantBankAccountUpdateSerializer(serializers.Serializer):
    bank_name = serializers.CharField(max_length=100)
    bank_account_name = serializers.CharField(max_length=50)
    bank_account_no = serializers.CharField(max_length=30)
    code = serializers.CharField(max_length=6, help_text='手机短信验证码')

    def validate_bank_account_no(self, value):
        v = value.replace(' ', '')
        if not v.isdigit() or not (10 <= len(v) <= 25):
            raise serializers.ValidationError('银行卡号格式不正确')
        return v


class MerchantDeliveryConfigSerializer(serializers.ModelSerializer):
    """商家端 - 配送配置(读 / 写)"""

    class Meta:
        model = Merchant
        fields = [
            'support_home_delivery',
            'support_self_pickup',
            'freight_mode',
            'delivery_fee',
            'distance_rules',
            'min_order_amount',
            'free_delivery_threshold',
            'delivery_range',
            'pickup_discount_type',
            'pickup_discount_value',
            'pickup_note',
        ]

    def validate(self, attrs):
        instance = self.instance

        def _final(key):
            if key in attrs:
                return attrs[key]
            return getattr(instance, key, None) if instance else None

        # 1) 至少支持一种配送方式
        if _final('support_home_delivery') is False and _final('support_self_pickup') is False:
            raise serializers.ValidationError(
                '至少需要支持一种配送方式(送货上门 / 到店自提)'
            )

        # 2) distance_rules 格式校验
        rules = attrs.get('distance_rules')
        if rules is not None:
            if not isinstance(rules, list):
                raise serializers.ValidationError({'distance_rules': '必须是数组'})
            for i, r in enumerate(rules):
                if not isinstance(r, dict):
                    raise serializers.ValidationError(
                        {'distance_rules': f'第 {i+1} 条规则格式错误'}
                    )
                max_km = r.get('max_km')
                if max_km is not None:
                    try:
                        if float(max_km) <= 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        raise serializers.ValidationError({
                            'distance_rules': f'第 {i+1} 条 max_km 必须是正数或 null'
                        })
                fee = r.get('fee')
                if fee is None:
                    raise serializers.ValidationError({
                        'distance_rules': f'第 {i+1} 条缺少 fee 字段'
                    })
                try:
                    if float(fee) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    raise serializers.ValidationError({
                        'distance_rules': f'第 {i+1} 条 fee 必须是 >= 0 的数字'
                    })

        # 3) freight_mode=distance 时必须有 distance_rules
        if _final('freight_mode') == 'distance':
            final_rules = rules if rules is not None else getattr(instance, 'distance_rules', None)
            if not final_rules:
                raise serializers.ValidationError({
                    'distance_rules': '按距离阶梯模式必须至少配置一条规则'
                })

        # 4) ✅ 修复 #3: 自提优惠值校验,discount_value 也用最终生效值
        # 旧 bug: 用户上次存了 pickup_discount_value=150,这次只改 type 从 amount → percent,
        # 校验跳过,数据库就出现非法的 percent=150% 状态
        discount_type = _final('pickup_discount_type')
        discount_value = _final('pickup_discount_value')
        if discount_value is not None:
            if discount_value < 0:
                raise serializers.ValidationError({
                    'pickup_discount_value': '优惠值不能为负数'
                })
            if discount_type == 'percent' and discount_value > 100:
                raise serializers.ValidationError({
                    'pickup_discount_value': '按比例打折时,优惠值不能超过 100'
                })

        # 5) 金额字段不能为负
        for key in ('min_order_amount', 'delivery_fee', 'free_delivery_threshold'):
            v = attrs.get(key)
            if v is not None and v < 0:
                raise serializers.ValidationError({key: '不能为负数'})

        return attrs