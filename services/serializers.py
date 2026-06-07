# -*- coding: utf-8 -*-

import math
import re
from decimal import Decimal

from rest_framework import serializers

from .models import (
    ServiceCategory, Service,
    ServiceScheduleRule, ServiceTimeSlot,
    ServiceFavorite,
)
from staffs.models import Staff


# ═══════════════════════════════════════════════════════════════════════
# 服务分类
# ═══════════════════════════════════════════════════════════════════════

class ServiceCategorySerializer(serializers.ModelSerializer):
    """分类基础序列化器"""
    children = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source='parent.name', read_only=True, default='')

    class Meta:
        model = ServiceCategory
        fields = [
            'id', 'name', 'parent', 'parent_name', 'level',
            'icon', 'image', 'description',
            'sort_order', 'is_active', 'is_hot',
            'service_count', 'children',
        ]
        read_only_fields = ['id', 'level', 'service_count']

    def get_children(self, obj):
        children = obj.children.filter(is_active=True).order_by('-sort_order', 'id')
        return ServiceCategorySimpleSerializer(children, many=True).data


class ServiceCategorySimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'level', 'icon', 'image', 'is_active']


class ServiceCategoryTreeSerializer(serializers.ModelSerializer):
    """嵌套展开(用于级联选择器)"""
    children = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = [
            'id', 'name', 'parent', 'level',
            'icon', 'image', 'description',
            'sort_order', 'is_hot', 'is_active',
            'service_count', 'children',
        ]

    def get_children(self, obj):
        include_inactive = self.context.get('include_inactive', False)
        qs = obj.children.all() if include_inactive else obj.children.filter(is_active=True)
        children = qs.order_by('-sort_order', 'id')
        return ServiceCategoryTreeSerializer(
            children, many=True, context=self.context
        ).data


class ServiceCategoryFlatSerializer(serializers.ModelSerializer):
    """扁平化(带完整路径)"""
    full_name = serializers.SerializerMethodField()
    is_leaf = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'full_name', 'level', 'parent', 'is_leaf', 'is_active']

    def get_full_name(self, obj):
        names = [obj.name]
        p = obj.parent
        while p:
            names.insert(0, p.name)
            p = p.parent
        return ' > '.join(names)

    def get_is_leaf(self, obj):
        return not obj.children.filter(is_active=True).exists()


class ServiceCategoryCreateSerializer(serializers.ModelSerializer):
    """管理员创建/编辑分类"""

    class Meta:
        model = ServiceCategory
        fields = [
            'name', 'parent', 'icon', 'image', 'description',
            'sort_order', 'is_active', 'is_hot',
        ]

    def validate_parent(self, value):
        if value and value.level >= 3:
            raise serializers.ValidationError('父分类已达最大层级,无法再添加子分类')
        return value

    def validate(self, attrs):
        name = attrs.get('name')
        parent = attrs.get('parent')
        if name and parent:
            instance_id = self.instance.id if self.instance else None
            qs = ServiceCategory.objects.filter(parent=parent, name=name)
            if instance_id:
                qs = qs.exclude(id=instance_id)
            if qs.exists():
                raise serializers.ValidationError({
                    'name': '同级分类下已存在相同名称',
                })
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# 员工 / 嵌套展示
# ═══════════════════════════════════════════════════════════════════════

class MerchantStaffSimpleSerializer(serializers.ModelSerializer):
    """服务详情里嵌套的员工 chip 信息"""

    class Meta:
        model = Staff
        fields = [
            'id', 'name', 'avatar', 'rating',
            'total_orders', 'good_review_rate', 'work_status',
        ]


class StaffMembersField(serializers.PrimaryKeyRelatedField):
    """
    创建/编辑服务时的员工字段:
    - 只能选当前商家在职的员工(防止越权或选到离职员工)
    - merchant 从 request.auth 解析,与 MerchantStaffViewSet._get_merchant_id 保持一致
    """

    def get_queryset(self):
        request = self.context.get('request')
        if not request:
            return Staff.objects.none()

        # 与 MerchantStaffViewSet._get_merchant_id 完全一致的解析逻辑
        auth = getattr(request, 'auth', None) or {}
        merchant_id = None
        if auth.get('merchant_id'):
            # 子账号: 用 JWT 里携带的 merchant_id
            merchant_id = auth['merchant_id']
        elif auth.get('type') == 'merchant':
            # 主账号: user_id 就是 merchant 自己的主键
            merchant_id = auth.get('user_id')

        if not merchant_id:
            return Staff.objects.none()

        return Staff.objects.filter(
            merchant_id=merchant_id,
            status=Staff.Status.ACTIVE,
        )


# ═══════════════════════════════════════════════════════════════════════
# 服务列表(C 端 / 搜索)
# ═══════════════════════════════════════════════════════════════════════

class ServiceListSerializer(serializers.ModelSerializer):
    """卡片维度的轻量序列化"""

    service_type_display = serializers.CharField(source='get_service_type_display', read_only=True)
    service_mode_display = serializers.CharField(source='get_service_mode_display', read_only=True)
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    category_name = serializers.CharField(source='category.name', default='', read_only=True)
    category_full_name = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()
    spec_coin_rules = serializers.SerializerMethodField()

    # 从 urgent_config 衍生的展示字段(列表卡片需要显示"支持加急"角标)
    support_urgent = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'subtitle', 'cover_image',
            'service_type', 'service_type_display',
            'service_mode', 'service_mode_display',
            'price', 'original_price', 'price_unit',
            'status', 'points_reward', 'spec_coin_rules',
            'total_sales', 'rating', 'review_count',
            'is_recommended', 'is_hot', 'support_urgent',
            'merchant', 'merchant_name',
            'category', 'category_name', 'category_full_name',
            'is_favorited', 'detail_images',
        ]

    def get_spec_coin_rules(self, obj):
        if not obj.specifications:
            return {}
        return {
            sp['key']: obj.get_spec_coin_rule(sp['key'])
            for sp in obj.specifications if sp.get('key')
        }

    def get_is_favorited(self, obj):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return False
        from user.models import User
        if not isinstance(request.user, User):
            return False
        return ServiceFavorite.objects.filter(user=request.user, service=obj).exists()

    def get_category_full_name(self, obj):
        if not obj.category:
            return ''
        names = [obj.category.name]
        p = obj.category.parent
        while p:
            names.insert(0, p.name)
            p = p.parent
        return ' > '.join(names)

    def get_support_urgent(self, obj):
        return bool(obj.urgent_config)


# ═══════════════════════════════════════════════════════════════════════
# 服务详情(C 端展示 + 商家端编辑回填)
# ═══════════════════════════════════════════════════════════════════════

class ServiceDetailSerializer(serializers.ModelSerializer):
    """
    既给 C 端展示用,也给商家端编辑回填用,所以表单需要的字段全部返回。
    商家级配置的 effective_* 都计算后返回,前端不用再去看 merchant 字段。
    """

    service_type_display = serializers.CharField(source='get_service_type_display', read_only=True)
    service_mode_display = serializers.CharField(source='get_service_mode_display', read_only=True)
    price_unit_display = serializers.CharField(source='get_price_unit_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    category = ServiceCategorySimpleSerializer(read_only=True)
    category_path = serializers.SerializerMethodField()

    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_logo = serializers.CharField(source='merchant.logo', read_only=True)
    merchant_phone = serializers.CharField(source='merchant.contact_phone', read_only=True)
    merchant_address = serializers.SerializerMethodField()

    # 实际生效的商家级配置(只读派生值)
    effective_business_hours = serializers.JSONField(read_only=True)
    effective_radius_meters = serializers.IntegerField(read_only=True)
    effective_delivery_fee = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True,
    )
    effective_free_delivery_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True,
    )
    effective_min_order_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )

    is_available = serializers.BooleanField(read_only=True)
    is_offsite = serializers.BooleanField(read_only=True)
    is_delivery_type = serializers.BooleanField(read_only=True)

    staff_members = MerchantStaffSimpleSerializer(many=True, read_only=True)
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id',
            # ─ 基础
            'name', 'subtitle', 'cover_image', 'images',
            'description', 'detail_content', 'service_notice', 'detail_images',
            # ─ 类型
            'service_type', 'service_type_display',
            'service_mode', 'service_mode_display',
            # ─ 价格
            'price', 'original_price', 'price_unit', 'price_unit_display',
            'deposit_amount',
            # ─ 金币 / 积分
            'allow_coin_deduction', 'max_coin_deduction', 'points_reward',
            # ─ 数量
            'min_quantity', 'max_quantity', 'stock',
            # ─ 规格(含 duration)
            'specifications', 'default_duration_minutes',
            # ─ 员工
            'require_staff', 'allow_choose_staff', 'staff_members',
            # ─ 通用订单约束
            'free_cancel_hours', 'max_daily_orders', 'max_concurrent_orders',
            'auto_confirm', 'required_info',
            # ─ 商家级覆盖(可空,空=继承)
            'business_hours_override', 'service_radius_override',
            'delivery_fee_override', 'free_delivery_threshold_override',
            'min_order_amount_override',
            # ─ 实际生效值(只读)
            'effective_business_hours', 'effective_radius_meters',
            'effective_delivery_fee', 'effective_free_delivery_threshold',
            'effective_min_order_amount',
            # ─ 类型专属配置
            'appointment_config', 'dispatch_config',
            'urgent_config', 'delivery_config',
            # ─ 排序 / 推荐 / 派生
            'sort_order', 'is_recommended', 'is_hot',
            'is_available', 'is_offsite', 'is_delivery_type',
            # ─ 状态
            'status', 'status_display',
            # ─ 统计
            'total_sales', 'view_count', 'favorite_count',
            'order_count', 'review_count', 'rating',
            # ─ 分类
            'category', 'category_path',
            # ─ 商家
            'merchant', 'merchant_name', 'merchant_logo',
            'merchant_phone', 'merchant_address',
            'is_favorited',
            'created_at',
        ]

    def get_is_favorited(self, obj):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return False
        from user.models import User
        if not isinstance(request.user, User):
            return False
        return ServiceFavorite.objects.filter(user=request.user, service=obj).exists()

    def get_merchant_address(self, obj):
        m = obj.merchant
        return f"{m.province}{m.city}{m.district}{m.address}" if m else ''

    def get_category_path(self, obj):
        if not obj.category:
            return []
        path = [{'id': obj.category.id, 'name': obj.category.name}]
        p = obj.category.parent
        while p:
            path.insert(0, {'id': p.id, 'name': p.name})
            p = p.parent
        return path


# ═══════════════════════════════════════════════════════════════════════
# 时段 / 排班
# ═══════════════════════════════════════════════════════════════════════

class ServiceTimeSlotSerializer(serializers.ModelSerializer):
    remaining = serializers.ReadOnlyField()
    is_bookable = serializers.ReadOnlyField()

    class Meta:
        model = ServiceTimeSlot
        fields = [
            'id', 'date', 'start_time', 'end_time',
            'capacity', 'booked_count', 'remaining',
            'status', 'is_bookable',
        ]


class ServiceScheduleRuleSerializer(serializers.ModelSerializer):
    """
    排班规则 —— 字段已重命名:
      slot_granularity_minutes(取代 slot_duration)
      parallel_capacity(取代 slot_capacity)
    """

    class Meta:
        model = ServiceScheduleRule
        fields = [
            'id', 'weekdays', 'start_time', 'end_time',
            'slot_granularity_minutes', 'parallel_capacity', 'is_active',
        ]

    def validate_weekdays(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError('适用星期至少选 1 天')
        for d in value:
            if not isinstance(d, int) or not (1 <= d <= 7):
                raise serializers.ValidationError('星期数值必须是 1-7')
        return value

    def validate_slot_granularity_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError('粒度必须 > 0')
        if value > 480:
            raise serializers.ValidationError('粒度不能超过 8 小时')
        return value

    def validate_parallel_capacity(self, value):
        if value <= 0:
            raise serializers.ValidationError('并发上限必须 >= 1')
        return value

    def validate(self, attrs):
        st = attrs.get('start_time') or (self.instance and self.instance.start_time)
        et = attrs.get('end_time') or (self.instance and self.instance.end_time)
        gran = attrs.get('slot_granularity_minutes') or (
            self.instance and self.instance.slot_granularity_minutes
        )

        if st and et and et <= st:
            raise serializers.ValidationError({'end_time': '结束时间必须晚于开始时间'})

        if st and et and gran:
            total = (et.hour * 60 + et.minute) - (st.hour * 60 + st.minute)
            if total < gran:
                raise serializers.ValidationError({
                    'slot_granularity_minutes': f'营业时长({total}分钟)小于粒度({gran}分钟),无法切片',
                })
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# 服务创建 / 编辑(商家端) —— 类型分发校验
# ═══════════════════════════════════════════════════════════════════════

class MerchantServiceCreateSerializer(serializers.ModelSerializer):
    """
    创建/编辑服务的核心 serializer。

    设计要点:
    - validate() 按 service_type 分发到对应 _validate_<type>() 方法
    - _must_be_null / _must_be_present 把字段错误精确定位到字段名
    - 草稿(status=draft)放宽必填校验,只校验跨类型一致性
    - 上架(status=active)严格校验所有规则
    """

    staff_members = StaffMembersField(many=True, required=False)

    class Meta:
        model = Service
        fields = [
            'id',
            # 基础
            'name', 'subtitle', 'cover_image', 'images',
            'description', 'detail_content', 'service_notice', 'detail_images',
            # 类型
            'service_type', 'service_mode',
            # 关联
            'category',
            # 价格
            'price', 'original_price', 'price_unit', 'deposit_amount',
            # 金币 / 积分
            'allow_coin_deduction', 'max_coin_deduction', 'points_reward',
            # 数量 / 库存
            'min_quantity', 'max_quantity', 'stock',
            # 规格
            'specifications', 'default_duration_minutes',
            # 员工
            'require_staff', 'allow_choose_staff', 'staff_members',
            # 通用订单
            'free_cancel_hours', 'max_daily_orders', 'max_concurrent_orders',
            'auto_confirm', 'required_info',
            # 商家级覆盖
            'business_hours_override', 'service_radius_override',
            'delivery_fee_override', 'free_delivery_threshold_override',
            'min_order_amount_override',
            # 类型专属
            'appointment_config', 'dispatch_config',
            'urgent_config', 'delivery_config',
            # 展示 / 状态
            'sort_order', 'is_recommended', 'is_hot', 'status',
        ]
        read_only_fields = ['id']

    TYPE_MODE_RULES = {
        Service.ServiceType.WALK_IN:     [Service.ServiceMode.STORE],
        Service.ServiceType.APPOINTMENT: [
            Service.ServiceMode.STORE,
            Service.ServiceMode.HOME,
            Service.ServiceMode.PICKUP,
        ],
        Service.ServiceType.ON_DEMAND:   [
            Service.ServiceMode.HOME,
            Service.ServiceMode.PICKUP,
        ],
        Service.ServiceType.SCHEDULED:   [
            Service.ServiceMode.HOME,
            Service.ServiceMode.PICKUP,
        ],
    }

    ALLOWED_REQUIRED_INFO = {
        'address', 'contact_phone', 'problem_desc',
        'problem_images', 'party_size', 'remark',
    }

    DELIVERY_CYCLES = {'daily', 'weekly', 'biweekly', 'monthly'}

    # ──────────── 单字段校验 ────────────

    def validate_category(self, value):
        if value and not value.is_active:
            raise serializers.ValidationError('该分类已停用,请选择其他分类')
        return value

    def validate_required_info(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('格式错误,必须是数组')
        for item in value:
            if item not in self.ALLOWED_REQUIRED_INFO:
                raise serializers.ValidationError(
                    f'不支持的下单字段: {item},可选: {sorted(self.ALLOWED_REQUIRED_INFO)}'
                )
        return value

    # ══════════════════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════════════════

    def _get(self, attrs, field, default=None):
        """
        编辑(PATCH)时若字段未传,从 self.instance 取值;否则用 default。
        """
        if field in attrs:
            return attrs[field]
        if self.instance:
            return getattr(self.instance, field, default)
        return default

    def _must_be_null(self, attrs, fields, reason=''):
        """声明这些字段在当前类型下"不应填写"。已填则报错。"""
        errors = {}
        for f in fields:
            val = self._get(attrs, f)
            if val is not None and val != '' and val != [] and val != {}:
                errors[f] = reason or '该字段在当前服务类型下不应填写'
        if errors:
            raise serializers.ValidationError(errors)

    def _must_be_present(self, attrs, fields, reason=''):
        """声明这些字段在当前类型下"必填"。未填则报错。"""
        errors = {}
        for f in fields:
            val = self._get(attrs, f)
            if val is None or val == '' or val == [] or val == {}:
                errors[f] = reason or '该字段在当前服务类型下必填'
        if errors:
            raise serializers.ValidationError(errors)

    # ══════════════════════════════════════════════════════════════════
    # validate 主流程
    # ══════════════════════════════════════════════════════════════════

    def validate(self, attrs):
        # 1) 通用校验
        self._validate_common(attrs)

        # 2) 规格结构校验
        self._validate_specifications(attrs)

        # 3) 商家覆盖值范围校验
        self._validate_overrides(attrs)

        # 4) 类型分发
        st = self._get(attrs, 'service_type')
        dispatch = {
            Service.ServiceType.WALK_IN: self._validate_walk_in,
            Service.ServiceType.APPOINTMENT: self._validate_appointment,
            Service.ServiceType.ON_DEMAND: self._validate_on_demand,
            Service.ServiceType.SCHEDULED: self._validate_scheduled,
        }
        if st in dispatch:
            dispatch[st](attrs)

        # 5) 上架前的"全量必填"检查
        status_val = self._get(attrs, 'status')
        if status_val == Service.Status.ACTIVE:
            self._validate_for_publishing(attrs)

        return attrs

    # ──────────── 通用校验 ────────────

    def _validate_common(self, attrs):
        """跨类型一致性检查"""
        # type ↔ mode
        st = self._get(attrs, 'service_type')
        sm = self._get(attrs, 'service_mode')
        if st and sm:
            allowed = self.TYPE_MODE_RULES.get(st, [])
            if allowed and sm not in allowed:
                st_label = Service.ServiceType(st).label
                sm_label = Service.ServiceMode(sm).label
                raise serializers.ValidationError({
                    'service_mode': f'服务类型「{st_label}」不支持服务方式「{sm_label}」',
                })

        # 员工开关一致性
        require_staff = self._get(attrs, 'require_staff', False)
        allow_choose = self._get(attrs, 'allow_choose_staff', False)
        if allow_choose and not require_staff:
            raise serializers.ValidationError({
                'allow_choose_staff': '需先开启「需要指派员工」才能允许客户选员工',
            })

        # 价格关系
        price = self._get(attrs, 'price')
        op = self._get(attrs, 'original_price')
        if price is not None and op is not None and op > 0 and op < price:
            raise serializers.ValidationError({
                'original_price': '原价不能低于售价',
            })

        # 数量关系
        min_q = self._get(attrs, 'min_quantity', 1)
        max_q = self._get(attrs, 'max_quantity')
        if max_q is not None and max_q > 0 and min_q is not None and max_q < min_q:
            raise serializers.ValidationError({
                'max_quantity': '最大下单量不能小于最少下单量',
            })

    # ──────────── 规格校验 ────────────

    def _validate_specifications(self, attrs):
        """
        规格结构:
        [{key, name, price, unit, duration_minutes?, party_size?, stock?}]
        - key 必须唯一,只允许小写字母/数字/下划线/连字符
        - name/price/unit 必填
        - duration_minutes 在 appointment 类型下必填且 > 0
        """
        if 'specifications' not in attrs:
            return
        specs = attrs.get('specifications') or []
        if not isinstance(specs, list):
            raise serializers.ValidationError({'specifications': '必须是数组'})

        st = self._get(attrs, 'service_type')
        key_pattern = re.compile(r'^[a-z0-9_\-]+$')
        seen_keys = set()
        normalized = []

        for i, sp in enumerate(specs):
            if not isinstance(sp, dict):
                raise serializers.ValidationError({
                    'specifications': f'第 {i + 1} 项不是对象',
                })

            key = (sp.get('key') or '').strip()
            name = (sp.get('name') or '').strip()
            unit = (sp.get('unit') or '').strip()

            if not key or not key_pattern.match(key):
                raise serializers.ValidationError({
                    'specifications': f'第 {i + 1} 项的 key 必填,仅允许小写字母/数字/下划线/连字符',
                })
            if key in seen_keys:
                raise serializers.ValidationError({
                    'specifications': f'规格 key 重复: {key}',
                })
            seen_keys.add(key)

            if not name:
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 name 必填',
                })
            if not unit:
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 unit 必填',
                })

            try:
                price = Decimal(str(sp.get('price', '0')))
            except Exception:
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 price 不是有效数字',
                })
            if price <= 0:
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 price 必须 > 0',
                })

            duration = sp.get('duration_minutes')
            if st == Service.ServiceType.APPOINTMENT:
                if duration is None or not isinstance(duration, int) or duration <= 0:
                    raise serializers.ValidationError({
                        'specifications': f'预约制服务的规格「{key}」必须填写 duration_minutes(>0)',
                    })
            else:
                # 非预约制允许不填(送水送奶等没有"时长"概念)
                if duration is not None and (not isinstance(duration, int) or duration <= 0):
                    raise serializers.ValidationError({
                        'specifications': f'规格「{key}」的 duration_minutes 必须是正整数',
                    })

            party_size = sp.get('party_size')
            if party_size is not None and (not isinstance(party_size, int) or party_size <= 0):
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 party_size 必须是正整数',
                })

            stock = sp.get('stock')
            if stock is not None and (not isinstance(stock, int) or stock < -1):
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 stock 必须是整数(-1 表示不限)',
                })

            # 规格级金币抵扣(可选,缺省=沿用 service 级)
            allow_coin = sp.get('allow_coin_deduction')
            if allow_coin is not None and not isinstance(allow_coin, bool):
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 allow_coin_deduction 必须是布尔值',
                })
            max_coin = sp.get('max_coin_deduction')
            if max_coin is not None and (not isinstance(max_coin, int) or max_coin < 0):
                raise serializers.ValidationError({
                    'specifications': f'规格「{key}」的 max_coin_deduction 必须是非负整数',
                })

            normalized.append({
                'key': key,
                'name': name,
                'price': str(price),
                'unit': unit,
                **({'duration_minutes': duration} if duration else {}),
                **({'party_size': party_size} if party_size else {}),
                **({'stock': stock} if stock is not None else {}),
                **({'allow_coin_deduction': allow_coin} if allow_coin is not None else {}),
                **({'max_coin_deduction': max_coin} if max_coin is not None else {}),
            })

        attrs['specifications'] = normalized

        # 多规格时, service.price 自动同步为 min(spec.price),前端不必再传
        if normalized:
            min_price = min(Decimal(sp['price']) for sp in normalized)
            attrs['price'] = min_price
        else:
            # 单规格服务: appointment 类型必须填 default_duration_minutes
            if st == Service.ServiceType.APPOINTMENT:
                dd = self._get(attrs, 'default_duration_minutes')
                if dd is None or dd <= 0:
                    raise serializers.ValidationError({
                        'default_duration_minutes':
                            '预约制单规格服务必须填写默认服务时长(default_duration_minutes)',
                    })

    # ──────────── 覆盖值校验 ────────────

    def _validate_overrides(self, attrs):
        """
        商家覆盖字段都是可空的,只校验"如果填了,值必须合理"。
        """
        radius = self._get(attrs, 'service_radius_override')
        if radius is not None and radius < 100:
            raise serializers.ValidationError({
                'service_radius_override': '服务半径不能小于 100 米',
            })

        fee = self._get(attrs, 'delivery_fee_override')
        if fee is not None and fee < 0:
            raise serializers.ValidationError({
                'delivery_fee_override': '配送费不能为负',
            })

        threshold = self._get(attrs, 'free_delivery_threshold_override')
        if threshold is not None and threshold < 0:
            raise serializers.ValidationError({
                'free_delivery_threshold_override': '免配送费门槛不能为负',
            })

        min_amount = self._get(attrs, 'min_order_amount_override')
        if min_amount is not None and min_amount < 0:
            raise serializers.ValidationError({
                'min_order_amount_override': '起送金额不能为负',
            })

        # business_hours_override 结构粗校验
        bh = self._get(attrs, 'business_hours_override')
        if bh is not None:
            if not isinstance(bh, dict):
                raise serializers.ValidationError({
                    'business_hours_override': '必须是对象',
                })
            wdays = bh.get('weekdays')
            if not isinstance(wdays, list) or not wdays:
                raise serializers.ValidationError({
                    'business_hours_override': 'weekdays 必填,至少 1 天',
                })
            wins = bh.get('windows')
            if not isinstance(wins, list) or not wins:
                raise serializers.ValidationError({
                    'business_hours_override': 'windows 必填,至少 1 个时间段',
                })
            for w in wins:
                if not isinstance(w, dict) or 'start' not in w or 'end' not in w:
                    raise serializers.ValidationError({
                        'business_hours_override': 'windows 元素必须含 start 和 end',
                    })

    # ══════════════════════════════════════════════════════════════════
    # 类型专属校验
    # ══════════════════════════════════════════════════════════════════

    def _validate_walk_in(self, attrs):
        """
        到店制:客户来店里,商家临场接待。
        - 不允许 appointment_config / dispatch_config / urgent_config / delivery_config
        - service_mode 必须是 store
        - require_staff 可选(如选理发师)
        - 营业时间默认继承商家
        """
        self._must_be_null(attrs, [
            'appointment_config', 'dispatch_config',
            'urgent_config', 'delivery_config',
            'service_radius_override',
            'delivery_fee_override',
            'free_delivery_threshold_override',
            'min_order_amount_override',
        ], reason='到店制不需要该字段')

    def _validate_appointment(self, attrs):
        """
        预约制:必须有 appointment_config。
        - schedule_type=customer 时 schedule_rules 由 viewset 子接口管理
        - schedule_type=merchant 时不允许加急(协商型本身就是定制)
        - delivery_config 必须为空
        """
        self._must_be_null(attrs, ['delivery_config'], reason='预约制不使用周期配送配置')
        self._must_be_present(attrs, ['appointment_config'], reason='预约制必须填写预约配置')

        cfg = self._get(attrs, 'appointment_config') or {}
        st_choice = cfg.get('schedule_type')
        if st_choice not in ('customer', 'merchant'):
            raise serializers.ValidationError({
                'appointment_config': 'schedule_type 必须是 customer 或 merchant',
            })

        for k, label, min_v, max_v in [
            ('advance_booking_hours', '提前预约小时数', 0, 720),
            ('max_advance_days', '最远可约天数', 1, 365),
            ('buffer_time_minutes', '服务间隔', 0, 240),
        ]:
            v = cfg.get(k)
            if v is None:
                continue
            if not isinstance(v, int) or v < min_v or v > max_v:
                raise serializers.ValidationError({
                    'appointment_config': f'{label}({k}) 必须是 {min_v}-{max_v} 之间的整数',
                })

        # 商家协商模式不允许加急
        if st_choice == 'merchant' and self._get(attrs, 'urgent_config'):
            raise serializers.ValidationError({
                'urgent_config': '商家协商型预约不支持加急(协商本身就是定制响应)',
            })

        self._validate_urgent_config(attrs)
        self._validate_dispatch_config(attrs)

    def _validate_on_demand(self, attrs):
        """
        按需制:点一次送一次,必须有员工执行,所以 require_staff 强制 True。
        - 必须有 dispatch_config
        - 必须设置服务半径(继承商家或覆盖)
        - delivery_config / appointment_config 必须为空
        """
        self._must_be_null(attrs, [
            'appointment_config', 'delivery_config',
        ], reason='按需制不使用该字段')

        # 强制必须有员工(否则没人能执行)
        require_staff = self._get(attrs, 'require_staff', False)
        if not require_staff:
            raise serializers.ValidationError({
                'require_staff': '按需制服务必须开启「需要指派员工」(否则没有员工可派单)',
            })

        self._must_be_present(attrs, ['dispatch_config'], reason='按需制必须配置派单参数')

        self._validate_urgent_config(attrs)
        self._validate_dispatch_config(attrs)

    def _validate_scheduled(self, attrs):
        """
        周期制:订阅自动配送,必须配置 delivery_config。
        - 不允许加急(订阅制本身是慢节奏)
        - 不允许 appointment_config(周期由 delivery_config 决定)
        """
        self._must_be_null(attrs, [
            'appointment_config', 'urgent_config',
        ], reason='周期制不使用该字段')

        self._must_be_present(attrs, ['delivery_config'], reason='周期制必须配置周期配送参数')
        self._validate_delivery_config(attrs)
        self._validate_dispatch_config(attrs)

    # ──────────── config 内部结构校验 ────────────

    def _validate_urgent_config(self, attrs):
        cfg = self._get(attrs, 'urgent_config')
        if not cfg:
            return
        if not isinstance(cfg, dict):
            raise serializers.ValidationError({'urgent_config': '必须是对象'})

        try:
            surcharge = Decimal(str(cfg.get('surcharge', '0')))
        except Exception:
            raise serializers.ValidationError({'urgent_config': 'surcharge 不是有效金额'})
        if surcharge < 0:
            raise serializers.ValidationError({'urgent_config': 'surcharge 不能为负'})

        rt = cfg.get('response_minutes')
        if rt is not None:
            if not isinstance(rt, int) or rt <= 0 or rt > 720:
                raise serializers.ValidationError({
                    'urgent_config': 'response_minutes 必须是 1-720 之间的整数',
                })

    def _validate_dispatch_config(self, attrs):
        cfg = self._get(attrs, 'dispatch_config')
        if not cfg:
            return
        if not isinstance(cfg, dict):
            raise serializers.ValidationError({'dispatch_config': '必须是对象'})

        require_staff = self._get(attrs, 'require_staff', False)
        if not require_staff:
            raise serializers.ValidationError({
                'dispatch_config': '未开启「需要指派员工」时不应填写派单配置',
            })

        auto = cfg.get('support_auto_dispatch', True)
        if not isinstance(auto, bool):
            raise serializers.ValidationError({
                'dispatch_config': 'support_auto_dispatch 必须是布尔值',
            })

        timeout = cfg.get('accept_timeout_minutes', 5)
        if not isinstance(timeout, int) or timeout <= 0 or timeout > 60:
            raise serializers.ValidationError({
                'dispatch_config': 'accept_timeout_minutes 必须是 1-60 之间的整数',
            })

        attempts = cfg.get('max_dispatch_attempts', 3)
        if not isinstance(attempts, int) or attempts <= 0 or attempts > 20:
            raise serializers.ValidationError({
                'dispatch_config': 'max_dispatch_attempts 必须是 1-20 之间的整数',
            })

    def _validate_delivery_config(self, attrs):
        cfg = self._get(attrs, 'delivery_config') or {}
        if not isinstance(cfg, dict):
            raise serializers.ValidationError({'delivery_config': '必须是对象'})

        cycle = cfg.get('cycle')
        if cycle not in self.DELIVERY_CYCLES:
            raise serializers.ValidationError({
                'delivery_config': f'cycle 必须是 {sorted(self.DELIVERY_CYCLES)} 之一',
            })

        qpd = cfg.get('quantity_per_delivery')
        if not isinstance(qpd, int) or qpd <= 0:
            raise serializers.ValidationError({
                'delivery_config': 'quantity_per_delivery 必须是正整数',
            })

        window = cfg.get('delivery_time_window')
        if not isinstance(window, dict) or 'start' not in window or 'end' not in window:
            raise serializers.ValidationError({
                'delivery_config': 'delivery_time_window 必须含 start 和 end',
            })
        if not self._is_valid_hhmm(window.get('start')) or not self._is_valid_hhmm(window.get('end')):
            raise serializers.ValidationError({
                'delivery_config': 'delivery_time_window 的 start/end 必须是 HH:MM 格式',
            })
        if window['start'] >= window['end']:
            raise serializers.ValidationError({
                'delivery_config': 'delivery_time_window.end 必须晚于 start',
            })

        # 可选字段
        skip_weekdays = cfg.get('skip_weekdays', [])
        if not isinstance(skip_weekdays, list):
            raise serializers.ValidationError({
                'delivery_config': 'skip_weekdays 必须是数组',
            })
        for d in skip_weekdays:
            if not isinstance(d, int) or not (1 <= d <= 7):
                raise serializers.ValidationError({
                    'delivery_config': 'skip_weekdays 元素必须是 1-7',
                })

        min_days = cfg.get('min_duration_days')
        if min_days is not None and (not isinstance(min_days, int) or min_days <= 0):
            raise serializers.ValidationError({
                'delivery_config': 'min_duration_days 必须是正整数',
            })

        allow_pause = cfg.get('allow_pause', False)
        if not isinstance(allow_pause, bool):
            raise serializers.ValidationError({
                'delivery_config': 'allow_pause 必须是布尔值',
            })

        max_pause = cfg.get('max_pause_days_per_period')
        if max_pause is not None and (not isinstance(max_pause, int) or max_pause < 0):
            raise serializers.ValidationError({
                'delivery_config': 'max_pause_days_per_period 必须是非负整数',
            })

    def _is_valid_hhmm(self, s) -> bool:
        if not isinstance(s, str):
            return False
        return bool(re.match(r'^([01]\d|2[0-3]):[0-5]\d$', s))

    # ──────────── 上架前补充检查 ────────────

    def _validate_for_publishing(self, attrs):
        """status=active 时的额外强校验"""
        # 基础字段
        if not self._get(attrs, 'name'):
            raise serializers.ValidationError({'name': '服务名称必填'})
        if not self._get(attrs, 'cover_image'):
            raise serializers.ValidationError({'cover_image': '封面图必填'})
        if not self._get(attrs, 'category'):
            raise serializers.ValidationError({'category': '请选择服务分类'})

        price = self._get(attrs, 'price')
        if price is None or price <= 0:
            raise serializers.ValidationError({'price': '请填写有效售价'})

        # 上架时,开启了员工指派必须分配员工
        require_staff = self._get(attrs, 'require_staff', False)
        if require_staff:
            staff_members = attrs.get('staff_members')
            if staff_members is None and self.instance:
                staff_members = list(self.instance.staff_members.all())
            if not staff_members:
                raise serializers.ValidationError({
                    'staff_members': '开启「需要指派员工」并要上架的服务必须至少分配一名员工',
                })

        # 上架时根据 mode 检查必填的 required_info
        sm = self._get(attrs, 'service_mode')
        req_info = self._get(attrs, 'required_info') or []
        if sm == Service.ServiceMode.HOME and 'address' not in req_info:
            raise serializers.ValidationError({
                'required_info': '上门服务必须收集客户地址(在 required_info 中添加 address)',
            })
        if sm == Service.ServiceMode.PICKUP and 'address' not in req_info:
            raise serializers.ValidationError({
                'required_info': '取送服务必须收集客户地址(在 required_info 中添加 address)',
            })

        # 按需制 / 周期制 上架前必须有效服务半径
        st = self._get(attrs, 'service_type')
        if st in (Service.ServiceType.ON_DEMAND, Service.ServiceType.SCHEDULED):
            # 用 instance.effective_radius_meters 或推断
            override = self._get(attrs, 'service_radius_override')
            if override is None and self.instance:
                merchant_radius = getattr(self.instance.merchant, 'delivery_range', 0)
                if not merchant_radius:
                    raise serializers.ValidationError({
                        'service_radius_override':
                            '配送类服务上架前,商家必须设置 delivery_range,或在此处覆盖一个服务半径',
                    })


# ═══════════════════════════════════════════════════════════════════════
# 收藏
# ═══════════════════════════════════════════════════════════════════════

class ServiceFavoriteSerializer(serializers.ModelSerializer):
    service = ServiceListSerializer(read_only=True)

    class Meta:
        model = ServiceFavorite
        fields = ['id', 'service', 'created_at']