# -*- coding: utf-8 -*-
import uuid

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError


class Prize(models.Model):
    """
    奖品模板
    """

    PRIZE_TYPE_CHOICES = (
        ('service', '服务类'),
        ('physical', '实物类'),
    )

    STATUS_CHOICES = (
        ('draft', '草稿'),
        ('active', '启用'),
        ('disabled', '停用'),
    )

    name = models.CharField(max_length=100, verbose_name='奖品名称')
    prize_type = models.CharField(max_length=20, choices=PRIZE_TYPE_CHOICES, verbose_name='奖品类型')

    title = models.CharField(max_length=200, verbose_name='中奖标题')
    subtitle = models.CharField(max_length=255, blank=True, default='', verbose_name='副标题')
    content = models.TextField(verbose_name='中奖内容')
    cover = models.URLField(blank=True, null=True, verbose_name='奖品封面')

    redeem_instruction = models.TextField(blank=True, default='', verbose_name='兑奖说明')
    redeem_contact = models.CharField(max_length=100, blank=True, default='', verbose_name='兑奖联系人')
    redeem_phone = models.CharField(max_length=30, blank=True, default='', verbose_name='兑奖联系电话')
    redeem_address = models.CharField(max_length=255, blank=True, default='', verbose_name='兑奖地点')

    valid_days = models.PositiveIntegerField(null=True, blank=True, verbose_name='发放后有效天数')
    start_time = models.DateTimeField(null=True, blank=True, verbose_name='可领取开始时间')
    end_time = models.DateTimeField(null=True, blank=True, verbose_name='可领取结束时间')

    need_address = models.BooleanField(default=False, verbose_name='是否需要收货地址')
    need_appointment = models.BooleanField(default=False, verbose_name='是否需要预约')

    sort = models.IntegerField(default=0, verbose_name='排序')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='状态')

    created_by = models.ForeignKey(
        'staff.Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_prizes',
        verbose_name='创建管理员'
    )
    updated_by = models.ForeignKey(
        'staff.Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_prizes',
        verbose_name='更新管理员'
    )

    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'prizes'
        verbose_name = '奖品模板'
        verbose_name_plural = '奖品模板'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['prize_type', 'status']),
            models.Index(fields=['status', 'sort']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.prize_type == 'physical' and not self.need_address:
            raise ValidationError('实物类奖品必须需要收货地址')

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('可领取开始时间必须小于结束时间')

        if self.valid_days is not None and self.valid_days == 0:
            raise ValidationError('有效天数必须大于 0')


class UserPrize(models.Model):
    """
    用户中奖记录
    """

    STATUS_CHOICES = (
        ('pending', '待领取'),
        ('claimed', '已申请兑奖'),
        ('processing', '处理中'),
        ('redeemed', '已兑奖'),
        ('expired', '已过期'),
        ('cancelled', '已作废'),
        ('rejected', '已驳回'),
    )

    SOURCE_CHOICES = (
        ('manual', '管理员手动发放'),
        ('activity', '活动中奖'),
        ('system', '系统发放'),
    )

    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='user_prizes',
        verbose_name='中奖用户'
    )
    prize = models.ForeignKey(
        'prize.Prize',
        on_delete=models.PROTECT,
        related_name='user_prizes',
        verbose_name='奖品模板'
    )

    # 快照
    prize_snapshot_name = models.CharField(max_length=100, verbose_name='奖品名称快照')
    prize_snapshot_type = models.CharField(max_length=20, verbose_name='奖品类型快照')
    title = models.CharField(max_length=200, verbose_name='中奖标题快照')
    subtitle = models.CharField(max_length=255, blank=True, default='', verbose_name='副标题快照')
    content = models.TextField(verbose_name='中奖内容快照')
    cover = models.URLField(blank=True, null=True, verbose_name='封面快照')

    redeem_instruction = models.TextField(blank=True, default='', verbose_name='兑奖说明快照')
    redeem_contact = models.CharField(max_length=100, blank=True, default='', verbose_name='兑奖联系人快照')
    redeem_phone = models.CharField(max_length=30, blank=True, default='', verbose_name='兑奖联系电话快照')
    redeem_address = models.CharField(max_length=255, blank=True, default='', verbose_name='兑奖地点快照')

    need_address = models.BooleanField(default=False, verbose_name='是否需要收货地址')
    need_appointment = models.BooleanField(default=False, verbose_name='是否需要预约')

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual', verbose_name='来源')
    batch_no = models.CharField(max_length=50, blank=True, default='', verbose_name='批次号')

    exchange_code = models.CharField(max_length=32, unique=True, db_index=True, verbose_name='兑奖码')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')

    issued_at = models.DateTimeField(default=timezone.now, verbose_name='发放时间')
    valid_start_time = models.DateTimeField(null=True, blank=True, verbose_name='有效开始时间')
    valid_end_time = models.DateTimeField(null=True, blank=True, verbose_name='有效结束时间')

    read_at = models.DateTimeField(null=True, blank=True, verbose_name='已读时间')
    claimed_at = models.DateTimeField(null=True, blank=True, verbose_name='申请兑奖时间')
    redeemed_at = models.DateTimeField(null=True, blank=True, verbose_name='兑奖完成时间')

    # 用户提交信息
    contact_name = models.CharField(max_length=50, blank=True, default='', verbose_name='联系人')
    contact_phone = models.CharField(max_length=20, blank=True, default='', verbose_name='联系电话')
    user_remark = models.CharField(max_length=255, blank=True, default='', verbose_name='用户备注')

    address = models.ForeignKey(
        'user.UserAddress',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prize_records',
        verbose_name='收货地址'
    )

    # 地址快照
    receiver_name_snapshot = models.CharField(max_length=50, blank=True, default='', verbose_name='收货人快照')
    receiver_phone_snapshot = models.CharField(max_length=20, blank=True, default='', verbose_name='收货手机号快照')
    province_snapshot = models.CharField(max_length=20, blank=True, default='', verbose_name='省快照')
    city_snapshot = models.CharField(max_length=20, blank=True, default='', verbose_name='市快照')
    district_snapshot = models.CharField(max_length=20, blank=True, default='', verbose_name='区快照')
    detail_address_snapshot = models.CharField(max_length=255, blank=True, default='', verbose_name='详细地址快照')

    admin_remark = models.CharField(max_length=255, blank=True, default='', verbose_name='管理员备注')

    issued_by = models.ForeignKey(
        'staff.Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_user_prizes',
        verbose_name='发放管理员'
    )
    handled_by = models.ForeignKey(
        'staff.Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_user_prizes',
        verbose_name='处理管理员'
    )

    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_prizes'
        verbose_name = '用户奖品记录'
        verbose_name_plural = '用户奖品记录'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'issued_at']),
            models.Index(fields=['valid_end_time']),
            models.Index(fields=['batch_no']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.user_id}-{self.prize_snapshot_name}-{self.status}'

    @staticmethod
    def generate_exchange_code():
        return uuid.uuid4().hex[:12].upper()

    def save(self, *args, **kwargs):
        if not self.exchange_code:
            self.exchange_code = self.generate_exchange_code()

        if self.prize_id:
            if not self.prize_snapshot_name:
                self.prize_snapshot_name = self.prize.name
            if not self.prize_snapshot_type:
                self.prize_snapshot_type = self.prize.prize_type
            if not self.title:
                self.title = self.prize.title
            if not self.subtitle:
                self.subtitle = self.prize.subtitle
            if not self.content:
                self.content = self.prize.content
            if not self.cover:
                self.cover = self.prize.cover
            if not self.redeem_instruction:
                self.redeem_instruction = self.prize.redeem_instruction
            if not self.redeem_contact:
                self.redeem_contact = self.prize.redeem_contact
            if not self.redeem_phone:
                self.redeem_phone = self.prize.redeem_phone
            if not self.redeem_address:
                self.redeem_address = self.prize.redeem_address

            self.need_address = self.prize.need_address
            self.need_appointment = self.prize.need_appointment

        super().save(*args, **kwargs)

    def clean(self):
        if self.valid_start_time and self.valid_end_time and self.valid_start_time >= self.valid_end_time:
            raise ValidationError('有效开始时间必须小于结束时间')

    @property
    def is_expired(self):
        return bool(self.valid_end_time and timezone.now() > self.valid_end_time)

    @property
    def can_claim(self):
        if self.status != 'pending':
            return False
        now = timezone.now()
        if self.valid_start_time and now < self.valid_start_time:
            return False
        if self.valid_end_time and now > self.valid_end_time:
            return False
        return True

    def set_address_snapshot(self, address):
        if not address:
            return
        self.receiver_name_snapshot = address.receiver_name or ''
        self.receiver_phone_snapshot = address.receiver_phone or ''
        self.province_snapshot = address.province or ''
        self.city_snapshot = address.city or ''
        self.district_snapshot = address.district or ''
        self.detail_address_snapshot = address.detail_address or ''

    def mark_expired_if_needed(self):
        if self.status in ['pending', 'claimed', 'processing'] and self.is_expired:
            old_status = self.status
            self.status = 'expired'
            self.save(update_fields=['status', 'updated_at'])
            UserPrizeLog.objects.create(
                user_prize=self,
                action='expire',
                old_status=old_status,
                new_status='expired',
                note='系统自动过期'
            )
            return True
        return False


class UserPrizeLog(models.Model):
    """
    用户奖品记录日志
    """

    ACTION_CHOICES = (
        ('issue', '发放'),
        ('read', '已读'),
        ('claim', '申请兑奖'),
        ('process', '处理中'),
        ('redeem', '已兑奖'),
        ('reject', '驳回'),
        ('cancel', '作废'),
        ('expire', '过期'),
        ('edit', '编辑'),
    )

    user_prize = models.ForeignKey(
        'prize.UserPrize',
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name='用户奖品记录'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name='操作类型')
    operator_staff = models.ForeignKey(
        'staff.Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prize_logs',
        verbose_name='操作管理员'
    )
    old_status = models.CharField(max_length=20, blank=True, default='', verbose_name='旧状态')
    new_status = models.CharField(max_length=20, blank=True, default='', verbose_name='新状态')
    note = models.CharField(max_length=255, blank=True, default='', verbose_name='备注')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='操作时间')

    class Meta:
        db_table = 'user_prize_logs'
        verbose_name = '用户奖品日志'
        verbose_name_plural = '用户奖品日志'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['user_prize', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user_prize_id}-{self.action}'
