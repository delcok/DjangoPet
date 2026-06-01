# -*- coding: utf-8 -*-
"""
服务模块数据模型

═══════════════════════════════════════════════════════════════════════════
设计原则
═══════════════════════════════════════════════════════════════════════════

1. 商家是服务的载体,服务默认继承商家配置
   - Merchant 已有: 经纬度 / business_hours / delivery_range / delivery_fee
                   / free_delivery_threshold / min_order_amount
   - Service 上的 `*_override` 字段为 null 时表示"沿用商家配置"
   - 业务层一律调用 service.effective_xxx 属性,避免到处判空

2. 四种服务类型互斥使用四个 JSON 配置
   - walk_in     到店制   ─→ 只允许 staff(可选), 营业时间用商家
   - appointment 预约制   ─→ appointment_config + schedule_rules + 可选 urgent/dispatch
   - on_demand   按需制   ─→ dispatch_config(必填) + 可选 urgent
   - scheduled   周期制   ─→ delivery_config(必填)
   - 由 serializer.validate 强制约束,模型层只做存储

3. 规格 specifications 是时长真源
   - 每个 spec 含 key/name/price/unit/duration_minutes/party_size
   - 多规格不同时长时, ScheduleRule.slot_granularity_minutes 是日历切片粒度
   - 下单时按 ceil(spec.duration / granularity) 占用连续 N 格

4. 排班语义重命名
   - slot_duration  → slot_granularity_minutes  (粒度,不是服务时长)
   - slot_capacity  → parallel_capacity         (并发上限,对齐"几个工位")
"""

from datetime import datetime, timedelta
from decimal import Decimal
import math

from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone as dj_tz


# ═══════════════════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════════════════

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        abstract = True


# ═══════════════════════════════════════════════════════════════════════
# 服务分类
# ═══════════════════════════════════════════════════════════════════════

class ServiceCategory(TimeStampedModel):
    """
    全局服务分类(最多三级)
    一级: 生活服务/家政服务/美容美发...
    二级: 保洁/维修/美甲...
    三级: 日常保洁/深度保洁/开荒保洁...
    """

    class Level(models.IntegerChoices):
        FIRST = 1, '一级'
        SECOND = 2, '二级'
        THIRD = 3, '三级'

    name = models.CharField(max_length=50, verbose_name='分类名称')
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='children',
        verbose_name='上级分类',
    )
    level = models.PositiveSmallIntegerField(
        choices=Level.choices, default=Level.FIRST,
        db_index=True, verbose_name='分类层级',
    )
    icon = models.CharField(max_length=255, blank=True, default='', verbose_name='图标')
    image = models.CharField(max_length=500, blank=True, default='', verbose_name='封面图')
    description = models.CharField(max_length=200, blank=True, default='', verbose_name='描述')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='启用')
    is_hot = models.BooleanField(default=False, verbose_name='热门')
    service_count = models.PositiveIntegerField(default=0, verbose_name='服务数量')

    class Meta:
        db_table = 'service_category'
        verbose_name = '服务分类'
        verbose_name_plural = verbose_name
        ordering = ['-sort_order', 'id']
        indexes = [
            models.Index(fields=['level', 'is_active']),
            models.Index(fields=['parent', 'is_active', 'sort_order']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.parent:
            self.level = self.parent.level + 1
            if self.level > 3:
                raise ValueError('分类层级最多支持三级')
        else:
            self.level = 1
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        names = [self.name]
        p = self.parent
        while p:
            names.insert(0, p.name)
            p = p.parent
        return ' > '.join(names)

    @property
    def is_leaf(self) -> bool:
        return not self.children.filter(is_active=True).exists()

    @classmethod
    def get_tree(cls, only_active=True):
        qs = cls.objects.filter(level=1)
        if only_active:
            qs = qs.filter(is_active=True)
        return qs.prefetch_related('children', 'children__children')


# ═══════════════════════════════════════════════════════════════════════
# 服务
# ═══════════════════════════════════════════════════════════════════════

class Service(TimeStampedModel):
    # ──────────── 枚举 ────────────
    class ServiceType(models.TextChoices):
        WALK_IN = 'walk_in', '到店制'
        APPOINTMENT = 'appointment', '预约制'
        ON_DEMAND = 'on_demand', '按需制'
        SCHEDULED = 'scheduled', '周期制'

    class ServiceMode(models.TextChoices):
        STORE = 'store', '到店'
        HOME = 'home', '上门'
        PICKUP = 'pickup', '取送'

    class PriceUnit(models.TextChoices):
        PER_TIME = 'time', '次'
        PER_HOUR = 'hour', '小时'
        PER_PIECE = 'piece', '件'
        PER_BARREL = 'barrel', '桶'
        PER_BOTTLE = 'bottle', '瓶'
        PER_SQUARE = 'square', '平方米'
        PER_PERSON = 'person', '人'
        PER_UNIT = 'unit', '个'
        PER_MACHINE = 'machine', '台'
        PER_KG = 'kg', '千克'

    class Status(models.TextChoices):
        DRAFT = 'draft', '草稿'
        ACTIVE = 'active', '已上架'
        INACTIVE = 'inactive', '已下架'

    # ─────────────────────────────────────────────────────────
    # 关联
    # ─────────────────────────────────────────────────────────
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='services',
        verbose_name='所属商家',
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='services',
        verbose_name='服务分类',
    )

    # ─────────────────────────────────────────────────────────
    # 基础展示
    # ─────────────────────────────────────────────────────────
    name = models.CharField(max_length=100, verbose_name='服务名称')
    subtitle = models.CharField(max_length=200, blank=True, default='', verbose_name='副标题')
    cover_image = models.CharField(max_length=500, blank=True, default='', verbose_name='封面图')
    images = models.JSONField(default=list, blank=True, verbose_name='轮播图')
    detail_images = models.JSONField(default=list, blank=True, verbose_name='详情长图')
    description = models.TextField(blank=True, default='', verbose_name='服务描述')
    detail_content = models.TextField(blank=True, default='', verbose_name='详情富文本')
    service_notice = models.TextField(blank=True, default='', verbose_name='服务须知')

    # ─────────────────────────────────────────────────────────
    # 类型 & 方式
    # ─────────────────────────────────────────────────────────
    service_type = models.CharField(
        max_length=20,
        choices=ServiceType.choices,
        default=ServiceType.WALK_IN,
        db_index=True,
        verbose_name='服务类型',
    )
    service_mode = models.CharField(
        max_length=20,
        choices=ServiceMode.choices,
        default=ServiceMode.STORE,
        verbose_name='服务方式',
    )

    # ─────────────────────────────────────────────────────────
    # 定价
    # ─────────────────────────────────────────────────────────
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='起价',
        help_text='单规格时为唯一售价;多规格时自动 = min(spec.price)',
    )
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='原价(划线价)',
    )
    price_unit = models.CharField(
        max_length=20,
        choices=PriceUnit.choices,
        default=PriceUnit.PER_TIME,
        verbose_name='默认计价单位',
        help_text='单规格时使用;多规格时各 spec 自带 unit',
    )
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0'),
        verbose_name='预约定金',
        help_text='0 表示无需定金',
    )

    # ─────────── 金币抵扣 ───────────
    allow_coin_deduction = models.BooleanField(default=True, verbose_name='允许金币抵扣')
    max_coin_deduction = models.PositiveIntegerField(
        default=0, verbose_name='单笔最大抵扣金币',
        help_text='0 表示不单独限制,受平台全局规则约束',
    )
    points_reward = models.PositiveIntegerField(
        default=0, verbose_name='完成赠送积分',
    )

    # ─────────── 数量与库存 ───────────
    min_quantity = models.PositiveSmallIntegerField(default=1, verbose_name='最少下单量')
    max_quantity = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='最多下单量')
    stock = models.IntegerField(default=-1, verbose_name='库存', help_text='-1=不限')

    # ─────────────────────────────────────────────────────────
    # 规格(时长真源)
    # ─────────────────────────────────────────────────────────
    specifications = models.JSONField(
        default=list, blank=True,
        verbose_name='服务规格',
        help_text='''
[
    {
        "key": "basic",                 // 规格唯一 key,订单关联用,改名不影响
        "name": "基础护理",              // 展示名
        "price": "88.00",                // 价格
        "unit": "次",                    // 计价单位 label
        "duration_minutes": 30,          // 时长(分钟),appointment 必填
        "party_size": null,              // 容纳人数,如包房 6 人,null=单人
        "stock": null                    // 该规格独立库存,null=共用 service.stock
    }
]
        ''',
    )
    default_duration_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='默认服务时长(分钟)',
        help_text='specifications 为空时使用;否则各 spec 自带 duration_minutes',
    )

    # ─────────────────────────────────────────────────────────
    # 员工
    # ─────────────────────────────────────────────────────────
    require_staff = models.BooleanField(default=False, verbose_name='需要指派员工')
    allow_choose_staff = models.BooleanField(default=False, verbose_name='允许客户选员工')
    staff_members = models.ManyToManyField(
        'staffs.Staff', blank=True,
        related_name='services',
        verbose_name='可服务员工',
    )

    # ─────────────────────────────────────────────────────────
    # 通用订单约束
    # ─────────────────────────────────────────────────────────
    free_cancel_hours = models.PositiveSmallIntegerField(
        default=2, verbose_name='免费取消时限(小时)',
    )
    max_daily_orders = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='每日最大接单量',
    )
    max_concurrent_orders = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='同时在途订单上限',
        help_text='派单类服务限制(如配送员/师傅并发上限),null=不限',
    )
    auto_confirm = models.BooleanField(
        default=False, verbose_name='自动确认订单',
        help_text='下单后系统自动接单,无需商家点确认',
    )
    required_info = models.JSONField(
        default=list, blank=True,
        verbose_name='下单需填写信息',
        help_text='可选项: address/contact_phone/problem_desc/problem_images/party_size/remark',
    )

    # ─────────────────────────────────────────────────────────
    # 商家级配置覆盖(null=继承 Merchant)
    # ─────────────────────────────────────────────────────────
    business_hours_override = models.JSONField(
        null=True, blank=True,
        verbose_name='服务专属营业时间',
        help_text='''
覆盖 merchant.business_hours 的服务专属时间窗,如"午餐限定 11:00-14:00"
格式: {
    "weekdays": [1,2,3,4,5,6,7],
    "windows": [{"start":"11:00","end":"14:00"}],
    "holidays": ["2026-01-01"]
}
        ''',
    )
    service_radius_override = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='服务范围(米)',
        help_text='null=继承 merchant.delivery_range,如大件家电限 3 公里',
    )
    delivery_fee_override = models.DecimalField(
        max_digits=6, decimal_places=2,
        null=True, blank=True,
        verbose_name='配送费',
        help_text='null=继承 merchant.delivery_fee',
    )
    free_delivery_threshold_override = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='免配送费门槛',
        help_text='null=继承 merchant.free_delivery_threshold',
    )
    min_order_amount_override = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='起送金额',
        help_text='null=继承 merchant.min_order_amount',
    )

    # ─────────────────────────────────────────────────────────
    # 类型专属配置(四选一,由 serializer 强制)
    # ─────────────────────────────────────────────────────────
    appointment_config = models.JSONField(
        null=True, blank=True,
        verbose_name='预约配置',
        help_text='''仅 service_type=appointment 时填写:
{
    "schedule_type": "customer",         // customer=客户选时段 / merchant=商家协商
    "advance_booking_hours": 2,           // 需提前多久预约
    "max_advance_days": 30,               // 最多可提前几天
    "buffer_time_minutes": 0              // 服务间隔(防排太满)
}
        ''',
    )
    dispatch_config = models.JSONField(
        null=True, blank=True,
        verbose_name='派单配置',
        help_text='''仅 require_staff=True 且类型支持派单时填写:
{
    "support_auto_dispatch": true,        // 是否启用自动派单
    "accept_timeout_minutes": 5,          // 员工接单超时
    "max_dispatch_attempts": 3            // 最多尝试派几个员工
}
        ''',
    )
    urgent_config = models.JSONField(
        null=True, blank=True,
        verbose_name='加急配置',
        help_text='''仅 appointment / on_demand 可填:
{
    "surcharge": "20.00",                 // 加急加价
    "response_minutes": 30                // 承诺响应时间
}
        ''',
    )
    delivery_config = models.JSONField(
        null=True, blank=True,
        verbose_name='周期配送配置',
        help_text='''仅 service_type=scheduled 必填:
{
    "cycle": "daily",                          // daily/weekly/biweekly/monthly
    "quantity_per_delivery": 1,                 // 每次配送数量
    "delivery_time_window": {                   // 配送时间窗(改成区间,避免承诺单点)
        "start": "07:00",
        "end": "09:00"
    },
    "skip_weekdays": [6, 7],                    // 跳过的星期 (1=周一)
    "skip_dates": ["2026-02-15"],               // 跳过的具体日期
    "min_duration_days": 30,                    // 最少订阅天数(统一单位,避免周/月歧义)
    "allow_pause": true,                        // 允许中途暂停
    "max_pause_days_per_period": 7              // 每订阅期最长累计暂停天数
}
        ''',
    )

    # ─────────────────────────────────────────────────────────
    # 排序 / 推荐 / 标记
    # ─────────────────────────────────────────────────────────
    sort_order = models.PositiveIntegerField(default=0, verbose_name='排序权重')
    is_hot = models.BooleanField(default=False, verbose_name='热门')
    is_recommended = models.BooleanField(default=False, verbose_name='推荐')

    # ─────────────────────────────────────────────────────────
    # 统计
    # ─────────────────────────────────────────────────────────
    total_sales = models.PositiveIntegerField(default=0, verbose_name='总销量')
    view_count = models.PositiveIntegerField(default=0, verbose_name='浏览量')
    favorite_count = models.PositiveIntegerField(default=0, verbose_name='收藏数')
    order_count = models.PositiveIntegerField(default=0, verbose_name='订单数')
    review_count = models.PositiveIntegerField(default=0, verbose_name='评价数')
    rating = models.DecimalField(
        max_digits=2, decimal_places=1, default=Decimal('5.0'),
        verbose_name='评分',
    )

    # ─────────────────────────────────────────────────────────
    # 状态
    # ─────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name='状态',
    )

    class Meta:
        db_table = 'service'
        verbose_name = '服务'
        verbose_name_plural = verbose_name
        ordering = ['-is_recommended', '-sort_order', '-total_sales']
        indexes = [
            models.Index(fields=['merchant', 'status', 'service_type']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['status', 'sort_order']),
        ]

    def __str__(self):
        return f"{self.name}({self.get_service_type_display()})"

    # ═════════════════════════════════════════════════════════
    # 计算属性: effective_xxx —— 最终生效值(自动 fallback 到商家)
    # ═════════════════════════════════════════════════════════

    @property
    def effective_business_hours(self) -> dict:
        """实际生效的营业时间(服务覆盖 > 商家默认)"""
        if self.business_hours_override:
            return self.business_hours_override
        return self.merchant.business_hours or {}

    @property
    def effective_radius_meters(self) -> int:
        """实际生效的服务半径(米)"""
        if self.service_radius_override is not None:
            return self.service_radius_override
        return self.merchant.delivery_range

    @property
    def effective_delivery_fee(self) -> Decimal:
        """实际生效的配送费"""
        if self.delivery_fee_override is not None:
            return self.delivery_fee_override
        return self.merchant.delivery_fee

    @property
    def effective_free_delivery_threshold(self):
        """实际生效的免配送费门槛"""
        if self.free_delivery_threshold_override is not None:
            return self.free_delivery_threshold_override
        return self.merchant.free_delivery_threshold

    @property
    def effective_min_order_amount(self) -> Decimal:
        """实际生效的起送金额"""
        if self.min_order_amount_override is not None:
            return self.min_order_amount_override
        return self.merchant.min_order_amount

    @property
    def is_available(self) -> bool:
        if self.status != self.Status.ACTIVE:
            return False
        if self.stock == 0:
            return False
        if not self.merchant.is_open:
            return False
        return True

    @property
    def is_offsite(self) -> bool:
        """是否非到店类型(需要配送/上门信息)"""
        return self.service_mode in (self.ServiceMode.HOME, self.ServiceMode.PICKUP)

    @property
    def is_delivery_type(self) -> bool:
        """是否为配送类(送水/送奶)"""
        return self.service_type in (
            self.ServiceType.ON_DEMAND,
            self.ServiceType.SCHEDULED,
        )

    # ═════════════════════════════════════════════════════════
    # 规格工具方法
    # ═════════════════════════════════════════════════════════

    def get_spec(self, spec_key: str) -> dict:
        """按 key 取规格;不存在抛 KeyError"""
        for sp in (self.specifications or []):
            if sp.get('key') == spec_key:
                return sp
        raise KeyError(f'规格不存在: {spec_key}')

    def get_spec_duration_minutes(self, spec_key: str = None) -> int:
        """
        取规格时长(分钟)
        - 多规格: 必须传 spec_key
        - 单规格(specifications 为空): 用 default_duration_minutes,缺省 60
        """
        if self.specifications:
            if not spec_key:
                raise ValueError('多规格服务下单必须指定 spec_key')
            return int(self.get_spec(spec_key).get('duration_minutes') or 60)
        return int(self.default_duration_minutes or 60)

    # ═════════════════════════════════════════════════════════
    # 预约时段(appointment 类型专用)
    # ═════════════════════════════════════════════════════════

    def get_available_slots(self, target_date, spec_key: str = None):
        """
        获取某天的可预约时段(合并已落库 + 规则推算)

        - 如果传 spec_key,会自动按该规格时长过滤"作为起点可行"的时段
          (即起点后续 N 格都未满才可作为起点)
        - 不传 spec_key 时返回原子时段列表

        Returns: list[{
            'id': int|None,
            'date': 'YYYY-MM-DD',
            'start_time': 'HH:MM:SS',
            'end_time': 'HH:MM:SS',
            'capacity': int,                  # 该时段并发上限
            'booked_count': int,
            'remaining': int,
            'status': str,
            'is_bookable': bool,
            'rule_id': int|None,
            'spec_compatible': bool|None      # 若传 spec_key,标记该起点是否能完整放下
        }]
        """
        today = dj_tz.localdate()

        if target_date < today:
            return []

        # max_advance_days 现在在 appointment_config 里
        max_advance = (self.appointment_config or {}).get('max_advance_days', 30)
        if max_advance and (target_date - today).days > max_advance:
            return []

        # 1) 已落库
        existing_qs = self.time_slots.filter(date=target_date).order_by('start_time')
        existing_map = {}
        for slot in existing_qs:
            key = (slot.start_time.strftime('%H:%M:%S'),
                   slot.end_time.strftime('%H:%M:%S'))
            existing_map[key] = {
                'id': slot.id,
                'date': target_date.isoformat(),
                'start_time': slot.start_time.strftime('%H:%M:%S'),
                'end_time': slot.end_time.strftime('%H:%M:%S'),
                'capacity': slot.capacity,
                'booked_count': slot.booked_count,
                'remaining': slot.remaining,
                'status': slot.status,
                'is_bookable': slot.is_bookable,
                'rule_id': slot.rule_id,
            }

        # 2) 规则推算
        weekday = target_date.isoweekday()
        rules = self.schedule_rules.filter(is_active=True)
        advance_hours = (self.appointment_config or {}).get('advance_booking_hours', 0)
        buffer_min = (self.appointment_config or {}).get('buffer_time_minutes', 0)

        earliest_dt = None
        if target_date == today:
            now_naive = dj_tz.localtime().replace(tzinfo=None)
            earliest_dt = now_naive + timedelta(hours=advance_hours or 0)

        virtual_slots = []
        for rule in rules:
            weekdays_normalized = [
                int(w) for w in (rule.weekdays or []) if str(w).isdigit()
            ]
            if weekday not in weekdays_normalized:
                continue
            if not rule.slot_granularity_minutes or rule.slot_granularity_minutes <= 0:
                continue

            start_dt = datetime.combine(target_date, rule.start_time)
            end_dt = datetime.combine(target_date, rule.end_time)
            if end_dt <= start_dt:
                continue

            delta = timedelta(minutes=rule.slot_granularity_minutes)
            buffer = timedelta(minutes=buffer_min)
            cursor = start_dt

            while cursor + delta <= end_dt:
                slot_start = cursor
                slot_end = cursor + delta
                cursor = slot_end + buffer

                if earliest_dt and slot_start < earliest_dt:
                    continue

                start_str = slot_start.time().strftime('%H:%M:%S')
                end_str = slot_end.time().strftime('%H:%M:%S')
                key = (start_str, end_str)

                if key in existing_map:
                    if existing_map[key].get('rule_id') is None:
                        existing_map[key]['rule_id'] = rule.id
                    continue

                virtual_slots.append({
                    'id': None,
                    'date': target_date.isoformat(),
                    'start_time': start_str,
                    'end_time': end_str,
                    'capacity': rule.parallel_capacity,
                    'booked_count': 0,
                    'remaining': rule.parallel_capacity,
                    'status': self.time_slots.model.Status.AVAILABLE,
                    'is_bookable': True,
                    'rule_id': rule.id,
                })

        all_slots = list(existing_map.values()) + virtual_slots
        all_slots.sort(key=lambda s: s['start_time'])

        # 3) 若指定规格,标记"作为起点能否完整放下"
        if spec_key:
            duration = self.get_spec_duration_minutes(spec_key)
            granularity = rules.first().slot_granularity_minutes if rules.exists() else 30
            slots_needed = math.ceil(duration / granularity)
            for i, s in enumerate(all_slots):
                window = all_slots[i:i + slots_needed]
                ok = (
                        len(window) == slots_needed
                        and all(w['is_bookable'] and w['remaining'] > 0 for w in window)
                        # 连续性检查: 后一格的 start == 前一格的 end
                        and all(
                    window[j]['start_time'] == window[j - 1]['end_time']
                    for j in range(1, len(window))
                )
                )
                s['spec_compatible'] = ok

        return all_slots

    def materialize_slots(self, target_date):
        """把指定日期的虚拟时段全部物化到 ServiceTimeSlot 表(幂等)"""
        slots = self.get_available_slots(target_date)
        created = 0
        with transaction.atomic():
            for s in slots:
                if s['id'] is not None:
                    continue
                _, was_created = self.time_slots.get_or_create(
                    date=target_date,
                    start_time=s['start_time'],
                    defaults={
                        'end_time': s['end_time'],
                        'capacity': s['capacity'],
                        'rule_id': s.get('rule_id'),
                    },
                )
                if was_created:
                    created += 1
        return created

    def book_slots(self, target_date, start_time_str: str, spec_key: str = None):
        """
        预约入口: 按规格时长占用连续 N 格

        :param target_date: 日期
        :param start_time_str: 起始时间 'HH:MM:SS'
        :param spec_key: 规格 key(多规格必填,单规格可省)
        :return: list[ServiceTimeSlot] 被占用的所有时段
        :raises ValueError: 时段不足/不连续/已满
        """
        duration_minutes = self.get_spec_duration_minutes(spec_key)
        rule = self.schedule_rules.filter(is_active=True).first()
        if not rule:
            raise ValueError('该服务未配置排班规则')

        # ★ 新增:服务端二次校验 advance_booking_hours
        advance_hours = (self.appointment_config or {}).get('advance_booking_hours', 0)
        now_naive = dj_tz.localtime().replace(tzinfo=None)
        try:
            start_t = datetime.strptime(start_time_str, '%H:%M:%S').time()
        except ValueError:
            start_t = datetime.strptime(start_time_str, '%H:%M').time()
        slot_start_dt = datetime.combine(target_date, start_t)
        if slot_start_dt < now_naive + timedelta(hours=advance_hours or 0):
            raise ValueError(
                f'该时段距当前时间不足 {advance_hours} 小时，无法预约'
            )

        granularity = rule.slot_granularity_minutes
        slots_needed = math.ceil(duration_minutes / granularity)

        with transaction.atomic():
            # 先确保起始格落库
            self.materialize_slots(target_date)

            qs = list(
                self.time_slots
                .select_for_update()
                .filter(date=target_date, start_time__gte=start_time_str)
                .order_by('start_time')[:slots_needed]
            )

            if len(qs) < slots_needed:
                raise ValueError('剩余时段不足以容纳所选规格')

            # 连续性校验(防中间被跳过)
            for i in range(1, len(qs)):
                if qs[i].start_time != qs[i - 1].end_time:
                    raise ValueError('连续时段中断,无法跨非连续时段预约')

            # 全部有名额才扣减
            for s in qs:
                if not s.is_bookable:
                    raise ValueError(f'时段 {s.start_time} 已不可预约')

            for s in qs:
                s.book()

        return qs


# ═══════════════════════════════════════════════════════════════════════
# 排班规则(仅 appointment + customer 调度类型使用)
# ═══════════════════════════════════════════════════════════════════════

class ServiceScheduleRule(TimeStampedModel):
    """
    周期性排班模板

    重要语义:
    - slot_granularity_minutes 是"日历切片粒度",不是单次服务时长
    - 单次服务时长由 spec.duration_minutes 决定
    - 下单时按 ceil(spec.duration / slot_granularity_minutes) 占用连续 N 格
    - 建议粒度: 15 / 30 / 60 分钟,太小会让日历碎片化
    """

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='schedule_rules',
        verbose_name='服务',
    )
    weekdays = models.JSONField(
        verbose_name='适用星期',
        help_text='数组, 1=周一 ... 7=周日',
    )
    start_time = models.TimeField(verbose_name='营业开始')
    end_time = models.TimeField(verbose_name='营业结束')
    slot_granularity_minutes = models.PositiveSmallIntegerField(
        verbose_name='时段粒度(分钟)',
        help_text='日历切片粒度,建议 15/30/60,与规格时长配合使用',
    )
    parallel_capacity = models.PositiveSmallIntegerField(
        verbose_name='并发上限',
        help_text='同一时刻最多可接几单(=工位数/在岗员工数)',
    )
    is_active = models.BooleanField(default=True, verbose_name='启用')

    class Meta:
        db_table = 'service_schedule_rule'
        verbose_name = '排班规则'
        verbose_name_plural = verbose_name

    def __str__(self):
        days = ','.join(str(d) for d in (self.weekdays or []))
        return f"{self.service.name} 周[{days}] {self.start_time}-{self.end_time}"


# ═══════════════════════════════════════════════════════════════════════
# 具体时段(物化的可约名额)
# ═══════════════════════════════════════════════════════════════════════

class ServiceTimeSlot(TimeStampedModel):
    """某日某时段的可约名额(由 ScheduleRule 推算或手动创建)"""

    class Status(models.TextChoices):
        AVAILABLE = 'available', '可预约'
        FULL = 'full', '已满'
        CLOSED = 'closed', '已关闭'

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='time_slots',
        verbose_name='服务',
    )
    rule = models.ForeignKey(
        ServiceScheduleRule,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='来源规则',
    )
    date = models.DateField(verbose_name='日期')
    start_time = models.TimeField(verbose_name='开始时间')
    end_time = models.TimeField(verbose_name='结束时间')
    capacity = models.PositiveSmallIntegerField(verbose_name='并发上限')
    booked_count = models.PositiveSmallIntegerField(default=0, verbose_name='已约数')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        verbose_name='状态',
    )

    class Meta:
        db_table = 'service_time_slot'
        verbose_name = '可预约时段'
        verbose_name_plural = verbose_name
        unique_together = ['service', 'date', 'start_time']
        indexes = [
            models.Index(fields=['service', 'date', 'status']),
        ]

    def __str__(self):
        return f"{self.service.name} {self.date} {self.start_time}"

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.booked_count)

    @property
    def is_bookable(self) -> bool:
        return self.status == self.Status.AVAILABLE and self.remaining > 0

    def book(self):
        if not self.is_bookable:
            raise ValueError('该时段不可预约')
        self.booked_count += 1
        if self.booked_count >= self.capacity:
            self.status = self.Status.FULL
        self.save(update_fields=['booked_count', 'status', 'updated_at'])

    def cancel_book(self):
        if self.booked_count > 0:
            self.booked_count -= 1
            if self.status == self.Status.FULL:
                self.status = self.Status.AVAILABLE
            self.save(update_fields=['booked_count', 'status', 'updated_at'])


# ═══════════════════════════════════════════════════════════════════════
# 收藏
# ═══════════════════════════════════════════════════════════════════════

class ServiceFavorite(models.Model):
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='service_favorites',
        verbose_name='用户',
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='服务',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'service_favorite'
        verbose_name = '服务收藏'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'service']

    def __str__(self):
        return f"{self.user} 收藏 {self.service.name}"