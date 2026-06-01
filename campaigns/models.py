# -*- coding: utf-8 -*-
"""促销活动 & 优惠券模型"""
from datetime import timedelta

from django.db import models
from django.utils import timezone

from user.models import User
from managers.models import Manager
from utils.coupon_code import generate_redemption_code


class CouponTemplate(models.Model):
    """优惠券模板（券的"出厂规则"，名义券，金额等字段可选）"""

    COUPON_TYPE_CHOICES = [
        ('cash', '代金券'),
        ('discount', '折扣券'),
        ('exchange', '兑换券'),
        ('gift', '礼品券'),
        ('other', '其他'),
    ]
    VALIDITY_TYPE_CHOICES = [
        ('fixed', '固定时间段'),
        ('relative', '领取后N天'),
        ('permanent', '长期有效'),
    ]

    name = models.CharField('券名称', max_length=100)
    description = models.TextField('券描述', blank=True, default='')
    coupon_type = models.CharField('券类型', max_length=20,
                                   choices=COUPON_TYPE_CHOICES, default='other')

    # ====== 名义字段（全部可选，仅作展示/埋点） ======
    face_value = models.DecimalField('面值/抵扣金额', max_digits=10, decimal_places=2,
                                     null=True, blank=True,
                                     help_text='名义金额，仅展示用')
    min_consumption = models.DecimalField('最低消费门槛', max_digits=10, decimal_places=2,
                                          null=True, blank=True)
    discount_rate = models.DecimalField('折扣率', max_digits=4, decimal_places=2,
                                        null=True, blank=True,
                                        help_text='0.80 表示 8 折')

    # ====== 有效期规则 ======
    validity_type = models.CharField('有效期类型', max_length=20,
                                     choices=VALIDITY_TYPE_CHOICES, default='relative')
    valid_days = models.PositiveIntegerField('领取后有效天数', null=True, blank=True)
    valid_start = models.DateTimeField('固定有效开始', null=True, blank=True)
    valid_end = models.DateTimeField('固定有效结束', null=True, blank=True)

    # ====== 媒体资源（OSS URL） ======
    image_url = models.URLField('券面图片URL', max_length=500, blank=True, default='')

    use_instructions = models.TextField('使用说明', blank=True, default='')
    is_active = models.BooleanField('是否启用', default=True)

    merchant_id = models.PositiveIntegerField(
        '所属商家ID', null=True, blank=True, db_index=True,
        help_text='留空=平台公共模板,所有商家可用;非空=商家私有模板',
    )
    created_by_merchant_type = models.CharField(
        '商家创建者类型', max_length=20, blank=True, default='',
        choices=[('merchant', '主账号'), ('merchant_sub', '子账号')],
    )
    created_by_merchant_id = models.PositiveIntegerField(
        '商家创建者ID', null=True, blank=True,
    )

    created_by = models.ForeignKey(Manager, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_coupon_templates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coupon_template'
        verbose_name = '优惠券模板'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def calculate_validity(self, claim_time=None):
        """根据规则计算某次领取的实际有效期 -> (valid_from, valid_to)"""
        claim_time = claim_time or timezone.now()
        if self.validity_type == 'fixed':
            return self.valid_start or claim_time, self.valid_end
        if self.validity_type == 'permanent':
            # 长期有效，给一个远期时间(2099-12-31)
            far_future = claim_time.replace(year=2099, month=12, day=31,
                                            hour=23, minute=59, second=59)
            return claim_time, far_future
        # relative
        days = self.valid_days or 30
        return claim_time, claim_time + timedelta(days=days)


class Campaign(models.Model):
    """促销活动（一个活动 = 一个二维码 = 一种券）"""

    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('active', '进行中'),
        ('paused', '已暂停'),
        ('ended', '已结束'),
    ]

    name = models.CharField('活动名称', max_length=100)
    description = models.TextField('活动描述', blank=True, default='')
    rules = models.TextField('活动规则', blank=True, default='')

    # 媒体资源（OSS URL）
    cover_image_url = models.URLField('封面图URL', max_length=500, blank=True, default='')

    # 关联券模板（一活动一种券）
    coupon_template = models.ForeignKey(CouponTemplate, on_delete=models.PROTECT,
                                        related_name='campaigns', verbose_name='发放的券')
    quantity_per_claim = models.PositiveIntegerField('单次领取张数', default=1)

    # 时间
    start_time = models.DateTimeField('开始时间')
    end_time = models.DateTimeField('结束时间')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES,
                              default='draft', db_index=True)

    # 库存与限制
    total_quota = models.PositiveIntegerField('总发放数量', null=True, blank=True,
                                              help_text='留空表示不限')
    claimed_count = models.PositiveIntegerField('已领取数量', default=0)
    per_user_limit = models.PositiveIntegerField('每人限领次数', default=1)

    # ====== 微信小程序码 ======
    wx_scene = models.CharField('小程序码 scene', max_length=32,
                                unique=True, db_index=True,
                                help_text='生成小程序码携带的活动唯一标识')
    wx_code_image_url = models.URLField('小程序码图片URL', max_length=500,
                                        blank=True, default='')
    wx_code_page = models.CharField('小程序码跳转页面', max_length=128,
                                    default='pages/campaigns/campaigns')

    # ====== 归属(★ 新增) ======
    merchant_id = models.PositiveIntegerField(
        '所属商家ID', null=True, blank=True, db_index=True,
        help_text='留空=平台活动;非空=商家活动',
    )
    created_by_merchant_type = models.CharField(
        '商家创建者类型', max_length=20, blank=True, default='',
        choices=[('merchant', '主账号'), ('merchant_sub', '子账号')],
    )
    created_by_merchant_id = models.PositiveIntegerField(
        '商家创建者ID', null=True, blank=True,
    )

    created_by = models.ForeignKey(Manager, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_campaigns')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'campaign'
        verbose_name = '促销活动'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_running(self) -> bool:
        now = timezone.now()
        return self.status == 'active' and self.start_time <= now <= self.end_time

    @property
    def remaining_quota(self):
        if self.total_quota is None:
            return None
        return max(self.total_quota - self.claimed_count, 0)


class UserCoupon(models.Model):
    """用户领到的券实例"""

    STATUS_CHOICES = [
        ('unused', '未使用'),
        ('used', '已使用'),
        ('expired', '已过期'),
        ('cancelled', '已作废'),
    ]

    # 核销码：12位，人工可输入
    code = models.CharField('核销码', max_length=16, unique=True, db_index=True,
                            default=generate_redemption_code)

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='coupons')
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True,
                                 related_name='user_coupons')
    coupon_template = models.ForeignKey(CouponTemplate, on_delete=models.PROTECT)

    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES,
                              default='unused', db_index=True)

    # ====== 模板字段快照（防止模板被改影响已发券） ======
    snapshot_name = models.CharField('券名称快照', max_length=100)
    snapshot_image_url = models.URLField('券面图URL快照', max_length=500,
                                         blank=True, default='')
    snapshot_face_value = models.DecimalField('面值快照', max_digits=10, decimal_places=2,
                                              null=True, blank=True)
    snapshot_min_consumption = models.DecimalField('门槛快照', max_digits=10, decimal_places=2,
                                                   null=True, blank=True)
    snapshot_discount_rate = models.DecimalField('折扣率快照', max_digits=4, decimal_places=2,
                                                 null=True, blank=True)

    # 有效期
    valid_from = models.DateTimeField('生效时间')
    valid_to = models.DateTimeField('失效时间', null=True, blank=True)

    # 时间戳
    claimed_at = models.DateTimeField('领取时间', auto_now_add=True)
    used_at = models.DateTimeField('核销时间', null=True, blank=True)

    # 核销信息
    redeemed_by = models.ForeignKey(Manager, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name='redeemed_coupons',
                                    verbose_name='核销操作员')

    # ====== 归属(★ 新增,冗余字段,领券时从 campaign 拷) ======
    merchant_id = models.PositiveIntegerField(
        '所属商家ID', null=True, blank=True, db_index=True,
    )

    # ====== 通用核销人引用(★ 新增,支持商家核销) ======
    # 旧 redeemed_by FK 保留兼容历史数据,新逻辑统一用 redeemer_*
    redeemer_type = models.CharField(
        '核销人类型', max_length=20, blank=True, default='',
        choices=[
            ('manager', '管理员'),
            ('merchant', '商户主账号'),
            ('merchant_sub', '商户子账号'),
        ],
    )
    redeemer_id = models.PositiveIntegerField('核销人ID', null=True, blank=True)
    redeemer_name = models.CharField('核销人名称(快照)', max_length=100, blank=True, default='')

    redemption_amount = models.DecimalField('实际核销金额', max_digits=10, decimal_places=2,
                                            null=True, blank=True,
                                            help_text='可选，名义金额仅作埋点')
    remark = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        db_table = 'user_coupon'
        verbose_name = '用户券'
        verbose_name_plural = verbose_name
        ordering = ['-claimed_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['campaign', 'user']),
            models.Index(fields=['merchant_id', 'status']),  # ★ 新增
        ]

    def __str__(self):
        return f'{self.code}({self.snapshot_name})'

    @property
    def formatted_code(self) -> str:
        c = self.code
        return f'{c[:4]}-{c[4:8]}-{c[8:12]}' if len(c) >= 12 else c

    @property
    def is_expired(self) -> bool:
        if self.valid_to is None:
            return False
        return timezone.now() > self.valid_to


class RedemptionLog(models.Model):
    """核销日志（审计用）"""

    ACTION_CHOICES = [
        ('redeem', '核销'),
        ('cancel', '作废'),
        ('refund', '退回'),
    ]

    user_coupon = models.ForeignKey(UserCoupon, on_delete=models.CASCADE,
                                    related_name='redemption_logs')
    operator = models.ForeignKey(Manager, on_delete=models.SET_NULL, null=True,
                                 related_name='coupon_operations')
    action = models.CharField('操作类型', max_length=20,
                              choices=ACTION_CHOICES, default='redeem')
    amount = models.DecimalField('涉及金额', max_digits=10, decimal_places=2,
                                 null=True, blank=True)
    remark = models.CharField('备注', max_length=200, blank=True, default='')
    # ====== 通用操作人(★ 新增,支持商家核销) ======
    actor_type = models.CharField(
        '操作人类型', max_length=20, blank=True, default='',
        choices=[
            ('manager', '管理员'),
            ('merchant', '商户主账号'),
            ('merchant_sub', '商户子账号'),
        ],
    )
    actor_id = models.PositiveIntegerField('操作人ID', null=True, blank=True)
    actor_name = models.CharField('操作人名称(快照)', max_length=100, blank=True, default='')

    ip_address = models.GenericIPAddressField('操作IP', null=True, blank=True)
    created_at = models.DateTimeField('操作时间', auto_now_add=True)

    class Meta:
        db_table = 'coupon_redemption_log'
        verbose_name = '核销日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']