# -*- coding: utf-8 -*-

from datetime import date
from decimal import Decimal

from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone


class Staff(models.Model):
    """商家员工"""

    class Status(models.TextChoices):
        ACTIVE    = 'active',    '在职'
        INACTIVE  = 'inactive',  '离职'
        SUSPENDED = 'suspended', '暂停接单'

    class WorkStatus(models.TextChoices):
        ONLINE  = 'online',  '在线'
        OFFLINE = 'offline', '离线'
        BUSY    = 'busy',    '忙碌'
        REST    = 'rest',    '休息中'

    # ══════ 实名认证状态 ══════
    class VerificationStatus(models.TextChoices):
        UNVERIFIED = 'unverified', '未认证'   # 从未提交过
        PENDING    = 'pending',    '待审核'   # 已提交,等待商家审核
        APPROVED   = 'approved',   '已通过'
        REJECTED   = 'rejected',   '已拒绝'

    # 员工可自行提交、需商家审核的字段白名单
    # 员工 POST verification 接口时,只有这些字段会进入 pending_changes
    # 其他字段即使提交也会被忽略(防止越权改派单权重等)
    EMPLOYEE_SUBMITTABLE_FIELDS = (
        'real_name', 'id_card_no',
        'id_card_front', 'id_card_back', 'health_certificate',
        'province', 'city', 'district', 'address',
        'home_longitude', 'home_latitude',
        'birthday', 'work_years',
        'emergency_contact_name', 'emergency_contact_phone',
    )

    # ══════ 关联商家 ══════
    merchant = models.ForeignKey(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='staff_members', verbose_name='所属商家'
    )

    # ══════ 基础信息 ══════
    # name = 对外展示名(花名/艺名),员工可自行修改无需审核
    # real_name = 真实姓名,实名认证用,需审核
    name = models.CharField(max_length=50, verbose_name='对外展示名')
    real_name = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='真实姓名',
        help_text='实名认证用,需商家审核'
    )
    avatar = models.CharField(max_length=255, blank=True, default='', verbose_name='头像')
    gender = models.CharField(
        max_length=10,
        choices=[('male', '男'), ('female', '女'), ('unknown', '未知')],
        default='unknown', verbose_name='性别'
    )
    birthday = models.DateField(null=True, blank=True, verbose_name='出生日期')
    introduction = models.TextField(blank=True, default='', verbose_name='个人简介')
    specialties = models.JSONField(
        default=list, blank=True, verbose_name='专长标签',
        help_text='如 ["经验丰富", "手法专业", "准时守信"]'
    )
    certificates = models.JSONField(
        default=list, blank=True, verbose_name='资质证书',
        help_text='证书图片URL数组'
    )

    # ══════ 实名认证（OSS URL）══════
    id_card_no = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='身份证号'
    )
    id_card_front = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='身份证人像面', help_text='OSS URL'
    )
    id_card_back = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='身份证国徽面', help_text='OSS URL'
    )
    health_certificate = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='健康证', help_text='OSS URL,部分行业必填'
    )

    # ══════ 住址信息 ══════
    province = models.CharField(max_length=50, blank=True, default='', verbose_name='省份')
    city     = models.CharField(max_length=50, blank=True, default='', verbose_name='城市')
    district = models.CharField(max_length=50, blank=True, default='', verbose_name='区县')
    address  = models.CharField(max_length=255, blank=True, default='', verbose_name='详细地址')
    home_longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='居住地经度',
        help_text='上门服务派单距离计算的基准点（service_radius 用此点）'
    )
    home_latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='居住地纬度'
    )

    # ══════ HR 信息 ══════
    hire_date = models.DateField(
        null=True, blank=True, verbose_name='入职日期',
        help_text='HR 数据,仅商家可改'
    )
    leave_date = models.DateField(
        null=True, blank=True, verbose_name='离职日期',
        help_text='HR 数据,仅商家可改'
    )
    work_years = models.PositiveSmallIntegerField(
        default=0, verbose_name='从业年限',
        help_text='用户侧展示用,如"5年经验"'
    )
    emergency_contact_name = models.CharField(
        max_length=50, blank=True, default='', verbose_name='紧急联系人'
    )
    emergency_contact_phone = models.CharField(
        max_length=17, blank=True, default='', verbose_name='紧急联系人电话'
    )

    # ══════ 登录信息 ══════
    phone = models.CharField(max_length=17, verbose_name='登录手机号')
    password = models.CharField(max_length=128, verbose_name='登录密码')
    employee_no = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='工号', help_text='可作为登录账号'
    )

    # ══════ 服务能力 ══════
    service_categories = models.ManyToManyField(
        'services.ServiceCategory', blank=True,
        related_name='staff_members', verbose_name='可服务分类'
    )
    max_concurrent_orders = models.PositiveSmallIntegerField(
        default=1, verbose_name='最大同时接单数'
    )
    service_radius = models.PositiveIntegerField(
        default=5000, verbose_name='服务半径(米)',
        help_text='仅 ServiceMode.HOME / PICKUP 类服务生效,基准点为 home_longitude/home_latitude'
    )
    can_handle_urgent = models.BooleanField(
        default=False, verbose_name='可接紧急订单'
    )

    # ══════ 派单权重 ══════
    dispatch_weight = models.PositiveSmallIntegerField(
        default=100, verbose_name='派单权重',
        help_text='数值越高系统越优先派单;根据 avg_response_minutes / acceptance_rate 自动调整,也可商家手动设置'
    )
    avg_response_minutes = models.PositiveSmallIntegerField(
        default=0, verbose_name='平均响应时长(分钟)',
        help_text='系统统计,响应越快 dispatch_weight 越高'
    )
    acceptance_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=100.00,
        verbose_name='接单率(%)',
        help_text='系统统计,超时未确认频繁时自动降低 dispatch_weight'
    )
    can_receive_transfer = models.BooleanField(
        default=True, verbose_name='接受转单',
        help_text='False 时系统自动转单跳过此员工,商家强制指派不受限'
    )

    # ══════ 排班 ══════
    work_schedule = models.JSONField(
        default=dict, blank=True, verbose_name='默认周排班',
        help_text='''格式(key 为 1~7,1=周一,7=周日):
        {
            "1": {"is_work": true,  "start": "09:00", "end": "18:00", "break_start": "12:00", "break_end": "13:00"},
            "6": {"is_work": false}
        }'''
    )
    rest_dates = models.JSONField(
        default=list, blank=True, verbose_name='特殊休息日',
        help_text='["2024-12-25", "2024-12-31"]'
    )
    work_status = models.CharField(
        max_length=20, choices=WorkStatus.choices,
        default=WorkStatus.OFFLINE, db_index=True,
        verbose_name='工作状态'
    )
    current_location_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='当前位置经度'
    )
    current_location_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='当前位置纬度'
    )
    location_updated_at = models.DateTimeField(
        null=True, blank=True, verbose_name='位置更新时间'
    )

    # ══════ 评分与统计 ══════
    rating = models.DecimalField(
        max_digits=3, decimal_places=1, default=5.0,
        verbose_name='综合评分'
    )
    total_orders = models.PositiveIntegerField(default=0, verbose_name='总服务次数')
    total_reviews = models.PositiveIntegerField(default=0, verbose_name='总评价数')
    good_review_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=100.00,
        verbose_name='好评率(%)'
    )
    monthly_orders = models.PositiveIntegerField(default=0, verbose_name='月服务次数')
    monthly_stat_reset_at = models.DateTimeField(
        null=True, blank=True, verbose_name='月统计上次重置时间'
    )

    # ══════ 推荐设置（用户侧展示）══════
    is_recommended = models.BooleanField(
        default=False, db_index=True, verbose_name='是否优先推荐'
    )
    sort_order = models.PositiveIntegerField(
        default=0, verbose_name='排序权重(展示用)',
        help_text='控制用户侧展示顺序,与 dispatch_weight 无关'
    )
    recommend_reason = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='推荐理由', help_text='如"金牌技师"、"服务之星"'
    )

    # ══════ 状态与安全 ══════
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.ACTIVE, db_index=True,
        verbose_name='员工状态'
    )
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

    # ══════ 实名审核 ══════
    # 流程:员工 POST 提交 → 合并到 pending_changes,status=PENDING
    #      商家 review approve → 应用 pending_changes 到正式字段,清空 pending_changes
    #      商家 review reject  → 清空 pending_changes,记录 remark
    verification_status = models.CharField(
        max_length=20, choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED, db_index=True,
        verbose_name='实名认证状态'
    )
    pending_changes = models.JSONField(
        default=dict, blank=True,
        verbose_name='待审核的字段变更',
        help_text='员工提交但商家尚未审核的字段值,审核通过后应用到对应字段'
    )
    verification_remark = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='审核备注', help_text='拒绝原因或审核意见'
    )
    verification_submitted_at = models.DateTimeField(
        null=True, blank=True, verbose_name='提交审核时间'
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, verbose_name='审核时间'
    )
    verified_by = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='审核人', help_text='商家主账号或子账号标识'
    )

    # ══════ 时间戳 ══════
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'staff'
        verbose_name = '员工'
        verbose_name_plural = verbose_name
        unique_together = ['merchant', 'phone']
        ordering = ['-is_recommended', '-sort_order', '-rating', 'id']
        indexes = [
            models.Index(fields=['merchant', 'status', 'work_status']),
            models.Index(fields=['is_recommended', '-sort_order']),
            models.Index(fields=['rating', '-total_orders']),
            # 自动派单候选筛选
            models.Index(fields=['merchant', 'status', 'work_status', '-dispatch_weight']),
            # 商家审核工作台:按商家 + 审核状态查待审核员工
            models.Index(fields=['merchant', 'verification_status']),
        ]

    def __str__(self):
        return f"{self.merchant.name} - {self.name}"

    # ── 密码 ─────────────────────────────────────────
    def set_password(self, raw_password: str):
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    # ── 状态 ─────────────────────────────────────────
    @property
    def is_available(self) -> bool:
        """是否可接单(在职 + 在线)"""
        return (
            self.status == self.Status.ACTIVE and
            self.work_status == self.WorkStatus.ONLINE
        )

    @property
    def can_auto_dispatch(self) -> bool:
        """
        是否可参与系统自动派单
        待审核期间(PENDING)不参与自动派单,商家强制指派不受此限制
        派单逻辑应使用此 property 过滤候选员工,而不是 is_available
        """
        if not self.is_available:
            return False
        if self.verification_status == self.VerificationStatus.PENDING:
            return False
        return True

    @property
    def full_address(self) -> str:
        return f"{self.province}{self.city}{self.district}{self.address}"

    @property
    def is_authenticated(self) -> bool:
        return True

    # ── 实名审核流程 ─────────────────────────────────
    def submit_verification(self, changes: dict):
        """
        员工提交认证信息,合并写入 pending_changes
        - 非白名单字段会被静默忽略(防止越权)
        - 多次部分提交会累积合并到同一份 pending_changes 中
          (例如先提交身份证、再提交住址,两者都会保留待审核)
        - 商家审核(通过/拒绝)后 pending_changes 被清空,员工可重新提交
        """
        allowed = set(self.EMPLOYEE_SUBMITTABLE_FIELDS)
        normalized = {}
        for k, v in changes.items():
            if k not in allowed or v is None:
                continue
            # JSON 存储:date / Decimal 序列化为字符串,审核通过时再 coerce 回原类型
            if isinstance(v, (date, Decimal)):
                normalized[k] = str(v)
            else:
                normalized[k] = v

        if not normalized:
            raise ValueError('提交的字段无任何可更新内容')

        # 合并而非覆盖:保留之前已提交但未审核的字段
        merged = dict(self.pending_changes or {})
        merged.update(normalized)

        self.pending_changes = merged
        self.verification_status = self.VerificationStatus.PENDING
        self.verification_submitted_at = timezone.now()
        self.verification_remark = ''
        self.save(update_fields=[
            'pending_changes', 'verification_status',
            'verification_submitted_at', 'verification_remark', 'updated_at',
        ])

    def approve_verification(self, reviewer: str = ''):
        """商家审核通过:把 pending_changes 应用到正式字段"""
        if self.verification_status != self.VerificationStatus.PENDING:
            raise ValueError('当前不是待审核状态')

        for field_name, value in (self.pending_changes or {}).items():
            if field_name in self.EMPLOYEE_SUBMITTABLE_FIELDS:
                setattr(self, field_name, self._coerce_value(field_name, value))

        self.pending_changes = {}
        self.verification_status = self.VerificationStatus.APPROVED
        self.verified_at = timezone.now()
        self.verified_by = reviewer
        self.verification_remark = ''
        self.save()

    def reject_verification(self, reason: str, reviewer: str = ''):
        """商家审核拒绝:清空 pending_changes,记录原因,员工可重新提交"""
        if self.verification_status != self.VerificationStatus.PENDING:
            raise ValueError('当前不是待审核状态')

        self.pending_changes = {}
        self.verification_status = self.VerificationStatus.REJECTED
        self.verified_at = timezone.now()
        self.verified_by = reviewer
        self.verification_remark = reason
        self.save(update_fields=[
            'pending_changes', 'verification_status',
            'verified_at', 'verified_by', 'verification_remark', 'updated_at',
        ])

    def _coerce_value(self, field_name, value):
        """JSON 反序列化后的字符串值还原为字段类型(date/Decimal)"""
        if value is None or value == '':
            return value
        try:
            field = self._meta.get_field(field_name)
        except Exception:
            return value
        # date 但不是 datetime
        if isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField):
            if isinstance(value, str):
                return date.fromisoformat(value)
        # Decimal
        if isinstance(field, models.DecimalField):
            if not isinstance(value, Decimal):
                return Decimal(str(value))
        return value


class StaffSchedule(models.Model):
    """
    员工按日排班
    优先级低于 rest_dates,高于 work_schedule 周模板
    用于请假、调班等特殊安排
    """

    class Source(models.TextChoices):
        MANUAL = 'manual', '手动创建'
        SYSTEM = 'system', '系统生成'

    staff = models.ForeignKey(
        Staff, on_delete=models.CASCADE,
        related_name='schedules', verbose_name='员工'
    )
    date = models.DateField(db_index=True, verbose_name='日期')
    is_working = models.BooleanField(default=True, verbose_name='是否工作')
    start_time = models.TimeField(null=True, blank=True, verbose_name='开始时间')
    end_time = models.TimeField(null=True, blank=True, verbose_name='结束时间')
    break_start = models.TimeField(null=True, blank=True, verbose_name='休息开始')
    break_end = models.TimeField(null=True, blank=True, verbose_name='休息结束')
    max_orders = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='当日最大接单数',
        help_text='为空时取 Staff.max_concurrent_orders'
    )
    source = models.CharField(
        max_length=20, choices=Source.choices,
        default=Source.MANUAL, verbose_name='来源'
    )
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')

    class Meta:
        db_table = 'staff_schedule'
        verbose_name = '员工排班'
        verbose_name_plural = verbose_name
        unique_together = ['staff', 'date']
        ordering = ['date', 'start_time']

    def __str__(self):
        return f"{self.staff.name} - {self.date}"


class StaffTimeSlot(models.Model):
    """员工已占用时段"""

    class Status(models.TextChoices):
        BOOKED    = 'booked',    '已预约'
        LOCKED    = 'locked',    '已锁定'
        CANCELLED = 'cancelled', '已取消'

    staff = models.ForeignKey(
        Staff, on_delete=models.CASCADE,
        related_name='time_slots', verbose_name='员工'
    )
    service_order = models.ForeignKey(
        'bill.ServiceOrder', on_delete=models.CASCADE,
        related_name='staff_time_slots', verbose_name='关联服务订单'
    )
    date = models.DateField(db_index=True, verbose_name='日期')
    start_time = models.TimeField(verbose_name='开始时间')
    end_time = models.TimeField(verbose_name='结束时间')
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.BOOKED, db_index=True,
        verbose_name='状态'
    )

    class Meta:
        db_table = 'staff_time_slot'
        verbose_name = '员工时间槽'
        verbose_name_plural = verbose_name
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['staff', 'date', 'status']),
            models.Index(fields=['staff', 'date', 'start_time']),
        ]

    def __str__(self):
        return f"{self.staff.name} - {self.date} {self.start_time}-{self.end_time}"

    def lock(self):
        if self.status != self.Status.BOOKED:
            raise ValueError('只有已预约的时段才能锁定')
        self.status = self.Status.LOCKED
        self.save(update_fields=['status'])

    def cancel(self):
        if self.status == self.Status.LOCKED:
            raise ValueError('已锁定的时段不可取消')
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status'])

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.BOOKED, self.Status.LOCKED)