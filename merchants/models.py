from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from decimal import Decimal
from math import radians, sin, cos, asin, sqrt


class MerchantCategory(models.Model):
    """商家分类"""

    name = models.CharField(max_length=50, verbose_name='分类名称')
    icon = models.CharField(max_length=255, blank=True, default='', verbose_name='分类图标')
    sort_order = models.PositiveIntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='默认佣金率(%)',
        help_text='该分类下商家的默认佣金比例'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'merchant_category'
        verbose_name = '商家分类'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class BusinessDistrict(models.Model):
    """商圈"""

    name = models.CharField(max_length=100, verbose_name='商圈名称')
    province = models.CharField(max_length=50, blank=True, default='', verbose_name='省份')
    city = models.CharField(max_length=50, blank=True, default='', verbose_name='城市')
    district = models.CharField(max_length=50, blank=True, default='', verbose_name='区县')
    address = models.CharField(max_length=255, blank=True, default='', verbose_name='详细地址')
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='中心经度'
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='中心纬度'
    )
    radius = models.PositiveIntegerField(
        default=3000, verbose_name='覆盖半径(米)'
    )
    boundary = models.JSONField(
        null=True, blank=True, verbose_name='商圈边界坐标',
        help_text='多边形顶点 [[lng,lat], ...]'
    )
    heat_score = models.PositiveIntegerField(
        default=0, verbose_name='热度值',
        help_text='根据订单量、浏览量等计算'
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'business_district'
        verbose_name = '商圈'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', '-heat_score', 'id']
        indexes = [
            models.Index(fields=['province', 'city', 'district']),
        ]

    def __str__(self):
        return f"{self.city} - {self.name}" if self.city else self.name

    @property
    def full_address(self) -> str:
        return f"{self.province}{self.city}{self.district}{self.address}"

    @property
    def region_display(self) -> str:
        parts = [p for p in [self.province, self.city, self.district] if p]
        return ' / '.join(parts) if parts else ''


class Merchant(models.Model):
    """商家"""

    class Status(models.TextChoices):
        PENDING = 'pending', '待审核'
        ACTIVE = 'active', '正常营业'
        SUSPENDED = 'suspended', '已暂停'
        REJECTED = 'rejected', '审核拒绝'
        CLOSED = 'closed', '已关闭'
        DRAFT = 'draft', '资料待完善'

    name = models.CharField(max_length=100, blank=True, default='', verbose_name='商家名称')
    logo = models.CharField(max_length=255, blank=True, default='', verbose_name='Logo')
    images = models.JSONField(
        default=list, blank=True, verbose_name='商家图片',
        help_text='图片URL数组，最多9张'
    )
    description = models.TextField(blank=True, default='', verbose_name='商家简介')
    announcement = models.TextField(blank=True, default='', verbose_name='商家公告')

    category = models.ForeignKey(
        MerchantCategory, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='merchants', verbose_name='商家分类'
    )
    business_district = models.ForeignKey(
        BusinessDistrict, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='merchants',
        verbose_name='所属商圈'
    )

    phone = models.CharField(
        max_length=17, unique=True, db_index=True,
        verbose_name='登录手机号'
    )
    password = models.CharField(max_length=128, verbose_name='登录密码')

    contact_name = models.CharField(max_length=50, blank=True, default='', verbose_name='联系人姓名')
    contact_phone = models.CharField(
        max_length=17, blank=True, default='',
        verbose_name='客服电话',
        help_text='对用户展示的联系电话'
    )

    province = models.CharField(max_length=50, blank=True, default='', verbose_name='省份')
    city = models.CharField(max_length=50, blank=True, default='', verbose_name='城市')
    district = models.CharField(max_length=50, blank=True, default='', verbose_name='区县')
    address = models.CharField(max_length=255, verbose_name='详细地址', blank=True)
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='经度'
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='纬度'
    )

    business_hours = models.JSONField(
        default=dict, blank=True, verbose_name='营业时间',
        help_text='格式: {"mon":{"open":"09:00","close":"22:00"},...}'
    )
    is_open = models.BooleanField(default=True, verbose_name='是否营业中')

    support_home_delivery = models.BooleanField(
        default=True, verbose_name='支持配送上门'
    )
    support_self_pickup = models.BooleanField(
        default=False, verbose_name='支持到店自提'
    )

    class FreightMode(models.TextChoices):
        FREE = 'free', '全店包邮'
        FLAT = 'flat', '统一运费'
        DISTANCE = 'distance', '按距离阶梯'

    freight_mode = models.CharField(
        max_length=20, choices=FreightMode.choices,
        default=FreightMode.FLAT, verbose_name='运费计算模式'
    )
    distance_rules = models.JSONField(
        default=list, blank=True, verbose_name='距离阶梯规则',
        help_text='仅 freight_mode=distance 生效。'
                  '格式: [{"max_km":3,"fee":5},{"max_km":10,"fee":10},{"max_km":null,"fee":20}]。'
                  'max_km=null 表示该档之外的兜底'
    )

    pickup_discount_type = models.CharField(
        max_length=20, default='none',
        choices=[('none', '无'), ('amount', '立减金额'), ('percent', '按比例打折')],
        verbose_name='自提优惠类型',
        help_text='自提天然免运费,这里是【商品金额】的额外让利'
    )
    pickup_discount_value = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name='自提优惠值',
        help_text='amount=立减元数;percent=折扣百分比(如5表示95折)'
    )
    pickup_note = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='自提说明',
        help_text='展示给用户的取货须知,如"凭核销码到前台领取"'
    )

    delivery_fee = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name='配送费'
    )
    free_delivery_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='免配送费门槛'
    )
    min_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='起送金额'
    )
    delivery_range = models.PositiveIntegerField(
        default=5000, verbose_name='配送范围(米)',
        help_text='单位米;0 表示未配置,将拒绝配送'
    )

    rating = models.DecimalField(
        max_digits=2, decimal_places=1, default=5.0,
        verbose_name='综合评分'
    )
    total_sales = models.PositiveIntegerField(default=0, verbose_name='总销量')
    monthly_sales = models.PositiveIntegerField(default=0, verbose_name='月销量')

    is_recommended = models.BooleanField(
        default=False, db_index=True, verbose_name='是否推荐'
    )
    recommend_sort = models.PositiveIntegerField(
        default=0, verbose_name='推荐排序权重'
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name='排序权重')

    license_no = models.CharField(
        max_length=50, blank=True, default='', verbose_name='营业执照号'
    )
    license_image = models.CharField(
        max_length=255, blank=True, default='', verbose_name='营业执照图片'
    )
    id_card_front = models.CharField(
        max_length=255, blank=True, default='', verbose_name='身份证正面'
    )
    id_card_back = models.CharField(
        max_length=255, blank=True, default='', verbose_name='身份证背面'
    )

    bank_name = models.CharField(max_length=100, blank=True, default='', verbose_name='开户银行')
    bank_account_name = models.CharField(max_length=50, blank=True, default='', verbose_name='开户名')
    bank_account_no = models.CharField(max_length=30, blank=True, default='', verbose_name='银行卡号')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='佣金率(%)'
    )

    wechat_mch_id = models.CharField(
        max_length=32, blank=True, default='', verbose_name='微信支付商户号'
    )
    alipay_pid = models.CharField(
        max_length=32, blank=True, default='', verbose_name='支付宝PID'
    )

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True,
        verbose_name='状态'
    )
    reject_reason = models.TextField(blank=True, default='', verbose_name='拒绝原因')
    login_fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='连续登录失败次数'
    )
    locked_until = models.DateTimeField(
        null=True, blank=True, verbose_name='锁定截止时间'
    )
    token_version = models.PositiveIntegerField(
        default=1, verbose_name='Token版本',
        help_text='修改密码或强制下线时递增'
    )
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'merchant'
        verbose_name = '商家'
        verbose_name_plural = verbose_name
        ordering = ['-sort_order', '-created_at']
        indexes = [
            models.Index(fields=['status', 'is_open', '-rating']),
            models.Index(fields=['category', 'status', 'is_open']),
            models.Index(fields=['business_district', 'status', 'is_open']),
            models.Index(fields=['is_recommended', '-recommend_sort']),
            models.Index(fields=['longitude', 'latitude']),
            models.Index(fields=['support_self_pickup', 'status', 'is_open']),
        ]

    def __str__(self):
        return self.name

    def set_password(self, raw_password: str):
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    # ✅ 修复 #1: 改名 is_operational,避免与 Django 约定的 is_active 字段冲突。
    #    DRF 的认证/权限/admin 都会读 user.is_active,
    #    旧 property 在非 ACTIVE 状态下返回 False 会导致这些组件误判为"未登录/不可用"。
    @property
    def is_operational(self) -> bool:
        """是否可对外营业(status=ACTIVE)"""
        return self.status == self.Status.ACTIVE

    @property
    def full_address(self) -> str:
        return f"{self.province}{self.city}{self.district}{self.address}"

    @property
    def is_authenticated(self) -> bool:
        return True

    def calc_freight(self, items, delivery_type,
                     receiver_lat=None, receiver_lng=None) -> dict:
        """计算运费 + 自提让利

        items: [{'goods': Goods, 'quantity': int, 'price': Decimal/数值}, ...]
        delivery_type: 'home_delivery' 或 'self_pickup'

        返回 dict: {
            ok: bool, error: str,
            freight: Decimal, goods_discount: Decimal,
            distance_km: float, free_shipping_reason: str
        }
        """
        res = {
            'ok': True, 'error': '',
            'freight': Decimal('0'),
            'goods_discount': Decimal('0'),
            'distance_km': 0.0,
            'free_shipping_reason': '',
        }

        def fail(msg):
            res['ok'] = False
            res['error'] = msg
            return res

        if not items:
            return fail('购物车为空')

        subtotal = sum(
            (Decimal(str(it['price'])) * int(it['quantity']) for it in items),
            Decimal('0'),
        )

        # ✅ 修复 #F: 先检测"既不允许配送也不允许自提"的死锁商品
        for it in items:
            g = it['goods']
            ad = getattr(g, 'allow_delivery', True)
            ap = getattr(g, 'allow_pickup', True)
            if ad is False and ap is False:
                title = getattr(g, 'title', '商品')
                return fail(f'商品「{title}」配送方式未配置,无法销售')

        # 1) Goods 配送/自提开关兼容性
        has_pickup_only = any(
            getattr(it['goods'], 'allow_delivery', True) is False
            for it in items
        )
        has_delivery_only = any(
            getattr(it['goods'], 'allow_pickup', True) is False
            for it in items
        )
        if has_pickup_only and has_delivery_only:
            return fail('购物车同时包含仅自提和仅配送商品,请分单下单')
        if delivery_type == 'home_delivery' and has_pickup_only:
            return fail('购物车含仅自提商品,请改选自提')
        if delivery_type == 'self_pickup' and has_delivery_only:
            return fail('购物车含仅配送商品,请改选配送')

        # 2) 商家配送能力
        if delivery_type == 'home_delivery' and not self.support_home_delivery:
            return fail('该商家暂不支持配送')
        if delivery_type == 'self_pickup' and not self.support_self_pickup:
            return fail('该商家暂不支持自提')

        # 3) 自提分支
        if delivery_type == 'self_pickup':
            if self.pickup_discount_type == 'amount':
                res['goods_discount'] = min(
                    Decimal(str(self.pickup_discount_value)), subtotal
                )
            elif self.pickup_discount_type == 'percent':
                pct = Decimal(str(self.pickup_discount_value)) / Decimal('100')
                res['goods_discount'] = (subtotal * pct).quantize(Decimal('0.01'))
            return res

        # 4) 配送分支
        if subtotal < Decimal(str(self.min_order_amount)):
            return fail(f'订单未达起送价 ¥{self.min_order_amount}')
        if receiver_lat is None or receiver_lng is None:
            return fail('请选择收货地址')
        if self.latitude is None or self.longitude is None:
            return fail('商家未设置坐标,暂时无法配送')

        # 直线距离
        lat1, lng1 = float(self.latitude), float(self.longitude)
        lat2, lng2 = float(receiver_lat), float(receiver_lng)
        rlat1, rlat2 = radians(lat1), radians(lat2)
        a = (sin((rlat2 - rlat1) / 2) ** 2
             + cos(rlat1) * cos(rlat2) * sin(radians(lng2 - lng1) / 2) ** 2)
        distance_km = 2 * asin(sqrt(a)) * 6371.0
        res['distance_km'] = round(distance_km, 2)

        # ✅ 修复 #2(中): delivery_range=0 视为"未配置",直接拒绝,避免"无限远"歧义
        if self.delivery_range <= 0:
            return fail('商家未设置配送范围')
        if distance_km * 1000 > self.delivery_range:
            return fail(f'超出配送范围(最远 {self.delivery_range / 1000:.1f} 公里)')

        # 店铺侧运费
        if self.freight_mode == 'free':
            shop_fee = Decimal('0')
        elif self.freight_mode == 'distance' and self.distance_rules:
            INF = 10 ** 9
            rules = sorted(
                self.distance_rules,
                key=lambda r: r.get('max_km') if r.get('max_km') is not None else INF
            )
            shop_fee = Decimal(str(self.delivery_fee))  # 兜底
            for r in rules:
                mk = r.get('max_km')
                if mk is None or distance_km <= float(mk):
                    shop_fee = Decimal(str(r.get('fee', 0)))
                    break
        else:
            shop_fee = Decimal(str(self.delivery_fee))

        # ✅ 修复 #4: 删除误导性注释。当前实现仅按店铺规则计算,
        #    未来要支持"商品级运费覆盖"再在此处聚合
        res['freight'] = shop_fee

        # 免运门槛
        threshold = self.free_delivery_threshold
        if threshold is not None and subtotal >= Decimal(str(threshold)):
            res['freight'] = Decimal('0')
            res['free_shipping_reason'] = f'满 ¥{threshold} 已包邮'
        elif self.freight_mode == 'free':
            res['free_shipping_reason'] = '全店包邮'

        return res

    def distance_km_to(self, lat, lng):
        """直线距离(km)。坐标缺失返回 None。"""
        if (self.latitude is None or self.longitude is None
                or lat is None or lng is None):
            return None
        try:
            lat1, lng1 = float(self.latitude), float(self.longitude)
            lat2, lng2 = float(lat), float(lng)
        except (TypeError, ValueError):
            return None
        rlat1, rlat2 = radians(lat1), radians(lat2)
        a = (sin((rlat2 - rlat1) / 2) ** 2
             + cos(rlat1) * cos(rlat2) * sin(radians(lng2 - lng1) / 2) ** 2)
        return round(2 * asin(sqrt(a)) * 6371.0, 3)

    def check_service_range(self, lat, lng, radius_meters=None):
        """
        校验坐标是否在服务半径内。
        radius_meters: 显式传入则优先(用于服务订单的 effective_radius_meters);
                       不传则用 self.delivery_range。
        返回 dict: {ok, error, distance_km, radius_meters}
        """
        radius = int(radius_meters) if radius_meters else int(self.delivery_range or 0)
        base = {'ok': False, 'error': '', 'distance_km': None, 'radius_meters': radius}

        if radius <= 0:
            return {**base, 'error': '商家未设置服务范围'}
        if self.latitude is None or self.longitude is None:
            return {**base, 'error': '商家未设置坐标,暂时无法服务'}
        if lat is None or lng is None:
            return {**base, 'error': '地址坐标缺失,请重新选择地址'}

        dist = self.distance_km_to(lat, lng)
        if dist is None:
            return {**base, 'error': '地址坐标无效'}

        in_range = dist * 1000 <= radius
        return {
            'ok': in_range,
            'error': '' if in_range else
            f'超出服务范围(最远 {radius / 1000:.1f} 公里,实际 {dist:.2f} 公里)',
            'distance_km': dist,
            'radius_meters': radius,
        }


class MerchantSubAccount(models.Model):
    """商家子账号"""

    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE,
        related_name='sub_accounts', verbose_name='所属商家'
    )
    name = models.CharField(max_length=50, verbose_name='账号名称')
    phone = models.CharField(max_length=17, verbose_name='登录手机号')
    password = models.CharField(max_length=128, verbose_name='登录密码')
    permissions = models.JSONField(
        default=list, blank=True, verbose_name='权限列表',
        help_text='如 ["order_view", "order_process", "product_edit"]'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    login_fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='连续登录失败次数'
    )
    locked_until = models.DateTimeField(
        null=True, blank=True, verbose_name='锁定截止时间'
    )
    token_version = models.PositiveIntegerField(default=1, verbose_name='Token版本')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'merchant_sub_account'
        verbose_name = '商家子账号'
        verbose_name_plural = verbose_name
        unique_together = ['merchant', 'phone']

    def __str__(self):
        return f"{self.merchant.name} - {self.name}"

    def set_password(self, raw_password: str):
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    @property
    def is_authenticated(self) -> bool:
        return True