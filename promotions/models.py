# -*- coding: utf-8 -*-
# promotions/models.py

from decimal import Decimal, ROUND_DOWN
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# ══════════════════════════════════════════════════════════════
# 1. 活动主表
# ══════════════════════════════════════════════════════════════

class PaymentActivity(models.Model):
    class ActivityType(models.TextChoices):
        ORDER_SPEND = 'order_spend', '订单消费送金币'
        RECHARGE    = 'recharge',    '充值送金币'

    class Status(models.TextChoices):
        DRAFT  = 'draft',  '未上线'
        ACTIVE = 'active', '进行中'
        PAUSED = 'paused', '已暂停'
        ENDED  = 'ended',  '已结束'

    class EnrollmentMode(models.TextChoices):
        ALL    = 'all',    '所有商家自动参加'
        OPT_IN = 'opt_in', '商家需主动报名'
        INVITE = 'invite', '平台邀请商家'

    class RewardType(models.TextChoices):
        FIXED   = 'fixed',   '固定金币'
        PERCENT = 'percent', '按金额百分比'
        TIERED  = 'tiered',  '阶梯规则'

    name          = models.CharField(max_length=100, verbose_name='活动名称')
    description   = models.CharField(max_length=200, blank=True, default='', verbose_name='活动说明')
    activity_type = models.CharField(
        max_length=20, choices=ActivityType.choices, db_index=True, verbose_name='活动类型',
    )

    # ── A) 用户金币奖励 ──────────────────────────────────────
    user_reward_enabled = models.BooleanField(default=True, verbose_name='给用户发金币')
    user_reward_type = models.CharField(
        max_length=20, choices=RewardType.choices,
        default=RewardType.TIERED, verbose_name='用户奖励类型',
    )
    user_reward_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'),
        verbose_name='用户奖励数值',
        help_text='fixed=固定金币数;percent=按金额百分比(0-100)',
    )
    user_reward_tiers = models.JSONField(
        default=list, blank=True, verbose_name='用户阶梯',
        help_text='tiered 时填:[{"threshold":200,"reward_coins":150}, ...]',
    )

    # ── B) 商家金币奖励(仅 ORDER_SPEND 生效) ──────────────
    merchant_reward_enabled = models.BooleanField(default=False, verbose_name='给商家发金币')
    merchant_reward_type = models.CharField(
        max_length=20, choices=RewardType.choices,
        default=RewardType.FIXED, verbose_name='商家奖励类型',
    )
    merchant_reward_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'),
        verbose_name='商家奖励数值',
        help_text='fixed=金币数;percent=百分比(0-100)',
    )
    merchant_reward_tiers = models.JSONField(
        default=list, blank=True, verbose_name='商家阶梯',
        help_text='tiered 时填:[{"threshold":100,"reward_coins":5}, ...]',
    )

    # ── 时间窗口 ──
    start_time = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    end_time   = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')

    # ── 适用范围 ──
    apply_order_types = models.JSONField(
        default=list, blank=True, verbose_name='适用订单类型',
        help_text='["product","service"];空=全部',
    )

    # ── 商家加入方式 ──
    enrollment_mode = models.CharField(
        max_length=20, choices=EnrollmentMode.choices,
        default=EnrollmentMode.OPT_IN, verbose_name='加入方式',
    )
    enrollment_audit = models.BooleanField(
        default=True, verbose_name='报名是否需要审批',
        help_text='仅 OPT_IN 模式下生效。True=需审批,False=报名即生效',
    )

    # ── 限额 ──
    per_user_limit = models.PositiveIntegerField(default=0, verbose_name='每用户领取上限(0=不限)')
    total_budget_coins = models.PositiveBigIntegerField(default=0, verbose_name='活动金币预算(0=不限)')

    # ── 金币抵扣排除(仅 order_spend 有意义) ──
    exclude_coin_deduction = models.BooleanField(
        default=True, verbose_name='金币抵扣订单不参与',
        help_text='True=用户本单使用了金币抵扣时,本单不参与该活动',
    )

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.DRAFT, db_index=True, verbose_name='状态',
    )

    user_granted_count    = models.PositiveBigIntegerField(default=0)
    user_granted_coins    = models.PositiveBigIntegerField(default=0)
    merchant_earned_count = models.PositiveBigIntegerField(default=0)
    merchant_earned_coins = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_activity'
        verbose_name = '支付活动'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['activity_type', 'status']),
            models.Index(fields=['status', 'start_time', 'end_time']),
        ]
        constraints = [
            # 全系统同时最多一个"未结束"的充值活动
            models.UniqueConstraint(
                fields=['activity_type'],
                condition=(
                    models.Q(activity_type='recharge') & ~models.Q(status='ended')
                ),
                name='uniq_alive_recharge_activity',
            ),
        ]

    def __str__(self):
        return f'[{self.get_activity_type_display()}] {self.name}'

    # ─── 业务约束 ───
    def clean(self):
        super().clean()
        if self.activity_type == self.ActivityType.RECHARGE and self.status != self.Status.ENDED:
            qs = PaymentActivity.objects.filter(
                activity_type=self.ActivityType.RECHARGE,
            ).exclude(status=self.Status.ENDED)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({'activity_type': '系统中已存在一个未结束的充值活动'})

        if self.activity_type == self.ActivityType.RECHARGE and self.merchant_reward_enabled:
            raise ValidationError({'merchant_reward_enabled': '充值类活动不支持商家奖励'})

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({'end_time': '结束时间必须晚于开始时间'})

    # ─── 业务方法 ───
    def is_in_period(self):
        now = timezone.now()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True

    def is_runnable(self):
        """
        快速预筛(乐观,不锁)。真正抢配额必须用 try_consume_*_budget。
        """
        if self.status != self.Status.ACTIVE:
            return False
        if not self.is_in_period():
            return False
        if self.total_budget_coins:
            used = (self.user_granted_coins or 0) + (self.merchant_earned_coins or 0)
            if used >= self.total_budget_coins:
                return False
        return True

    def is_merchant_eligible(self, merchant_id):
        if self.activity_type != self.ActivityType.ORDER_SPEND:
            return True
        if self.enrollment_mode == self.EnrollmentMode.ALL:
            return True
        return MerchantActivityEnrollment.objects.filter(
            activity=self, merchant_id=merchant_id,
            status=MerchantActivityEnrollment.Status.ACTIVE,
        ).exists()

    def skip_for_coin_deduction(self, coins_deducted) -> bool:
        """本单是否因使用金币抵扣而不参与本活动。仅 ORDER_SPEND 受此规则约束。"""
        if self.activity_type != self.ActivityType.ORDER_SPEND:
            return False
        if not self.exclude_coin_deduction:
            return False
        return (coins_deducted or 0) > 0

    def supports_order_type(self, order_type):
        if not self.apply_order_types:
            return True
        if not order_type:
            return False
        return order_type in self.apply_order_types

    def user_already_taken(self, user_id):
        return ActivityUserGrant.objects.filter(
            activity=self, user_id=user_id, is_revoked=False,
        ).count()

    def user_can_take_more(self, user_id):
        """预筛,不锁。真正校验放在 _try_grant_user 里的 select_for_update。"""
        if self.per_user_limit <= 0:
            return True
        return self.user_already_taken(user_id) < self.per_user_limit

    # ─── 金币计算 ───
    @staticmethod
    def _match_tier(amount, tiers):
        if not tiers:
            return 0
        amt = Decimal(str(amount))
        sorted_tiers = sorted(
            tiers,
            key=lambda t: Decimal(str(t.get('threshold', 0))),
            reverse=True,
        )
        for t in sorted_tiers:
            if amt >= Decimal(str(t.get('threshold', 0))):
                return int(t.get('reward_coins', 0))
        return 0

    @staticmethod
    def _calc_by_type(reward_type, value, tiers, amount):
        amt = Decimal(str(amount))
        if reward_type == PaymentActivity.RewardType.FIXED:
            return int(Decimal(str(value)))
        if reward_type == PaymentActivity.RewardType.PERCENT:
            coins = amt * Decimal(str(value)) / Decimal('100')
            return int(coins.to_integral_value(rounding=ROUND_DOWN))
        return PaymentActivity._match_tier(amount, tiers)

    def calc_user_reward(self, amount):
        if not self.user_reward_enabled:
            return 0
        return self._calc_by_type(
            self.user_reward_type, self.user_reward_value,
            self.user_reward_tiers, amount,
        )

    def calc_merchant_reward(self, amount):
        if not self.merchant_reward_enabled:
            return 0
        return self._calc_by_type(
            self.merchant_reward_type, self.merchant_reward_value,
            self.merchant_reward_tiers, amount,
        )

    # ════════════════════════════════════════════════════════
    # ★ 配额抢占 —— 用条件 UPDATE,避免并发超支
    # ════════════════════════════════════════════════════════

    def try_consume_user_budget(self, coins: int) -> bool:
        """
        原子地抢用户预算配额。
        - 预算为 0:无限,直接累加;
        - 否则:确保 (user_granted + merchant_earned + coins) <= total_budget
        返回 True 表示抢到,False 表示预算不够(放弃)。
        """
        from django.db.models import F, Q
        if coins <= 0:
            return False

        if self.total_budget_coins <= 0:
            rows = PaymentActivity.objects.filter(pk=self.pk).update(
                user_granted_count=F('user_granted_count') + 1,
                user_granted_coins=F('user_granted_coins') + coins,
            )
            return rows > 0

        rows = (PaymentActivity.objects
                .filter(pk=self.pk)
                .filter(
                    Q(total_budget_coins=0) |
                    Q(user_granted_coins__lte=F('total_budget_coins') -
                                              F('merchant_earned_coins') - coins)
                )
                .update(
                    user_granted_count=F('user_granted_count') + 1,
                    user_granted_coins=F('user_granted_coins') + coins,
                ))
        return rows > 0

    def try_consume_merchant_budget(self, coins: int) -> bool:
        """同上,商家预算抢占"""
        from django.db.models import F, Q
        if coins <= 0:
            return False

        if self.total_budget_coins <= 0:
            rows = PaymentActivity.objects.filter(pk=self.pk).update(
                merchant_earned_count=F('merchant_earned_count') + 1,
                merchant_earned_coins=F('merchant_earned_coins') + coins,
            )
            return rows > 0

        rows = (PaymentActivity.objects
                .filter(pk=self.pk)
                .filter(
                    Q(total_budget_coins=0) |
                    Q(merchant_earned_coins__lte=F('total_budget_coins') -
                                                 F('user_granted_coins') - coins)
                )
                .update(
                    merchant_earned_count=F('merchant_earned_count') + 1,
                    merchant_earned_coins=F('merchant_earned_coins') + coins,
                ))
        return rows > 0

    def refund_user_budget(self, coins: int):
        """退款撤销时归还用户预算"""
        from django.db.models import F, Case, When, Value, IntegerField
        if coins <= 0:
            return
        PaymentActivity.objects.filter(pk=self.pk).update(
            user_granted_count=Case(
                When(user_granted_count__gte=1, then=F('user_granted_count') - 1),
                default=Value(0),
                output_field=IntegerField(),
            ),
            user_granted_coins=Case(
                When(user_granted_coins__gte=coins, then=F('user_granted_coins') - coins),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )

    def refund_merchant_budget(self, coins: int):
        from django.db.models import F, Case, When, Value, IntegerField
        if coins <= 0:
            return
        PaymentActivity.objects.filter(pk=self.pk).update(
            merchant_earned_count=Case(
                When(merchant_earned_count__gte=1, then=F('merchant_earned_count') - 1),
                default=Value(0),
                output_field=IntegerField(),
            ),
            merchant_earned_coins=Case(
                When(merchant_earned_coins__gte=coins, then=F('merchant_earned_coins') - coins),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )


# ══════════════════════════════════════════════════════════════
# 2. 商家报名记录
# ══════════════════════════════════════════════════════════════

class MerchantActivityEnrollment(models.Model):
    class Status(models.TextChoices):
        PENDING  = 'pending',  '待审批'
        ACTIVE   = 'active',   '已加入'
        REJECTED = 'rejected', '已拒绝'
        QUIT     = 'quit',     '已退出'

    activity = models.ForeignKey(
        PaymentActivity, on_delete=models.CASCADE,
        related_name='enrollments', verbose_name='活动',
    )
    merchant = models.ForeignKey(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='activity_enrollments', verbose_name='商家',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True, verbose_name='状态',
    )
    apply_remark    = models.CharField(max_length=200, blank=True, default='')
    audit_remark    = models.CharField(max_length=200, blank=True, default='')
    audited_by_id   = models.PositiveIntegerField(null=True, blank=True)
    audited_at      = models.DateTimeField(null=True, blank=True)

    user_granted_count    = models.PositiveIntegerField(default=0)
    user_granted_coins    = models.PositiveBigIntegerField(default=0)
    merchant_earned_coins = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_activity_enrollment'
        verbose_name = '商家活动报名'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['activity', 'merchant'], name='uniq_activity_merchant',
            ),
        ]
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['activity', 'status']),
        ]


# ══════════════════════════════════════════════════════════════
# 3. 用户领取记录
# ══════════════════════════════════════════════════════════════

class ActivityUserGrant(models.Model):
    activity = models.ForeignKey(
        PaymentActivity, on_delete=models.CASCADE,
        related_name='user_grants',
    )
    user_id = models.PositiveIntegerField(db_index=True)
    merchant_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    payment_no = models.CharField(max_length=32, db_index=True)
    order_no = models.CharField(max_length=32, blank=True, default='')
    trigger_amount = models.DecimalField(max_digits=10, decimal_places=2)
    reward_coins = models.PositiveIntegerField()

    is_revoked = models.BooleanField(default=False, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_user_grant'
        verbose_name = '用户活动领取记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['activity', 'payment_no'],
                name='uniq_user_grant_activity_payment',
            ),
        ]
        indexes = [
            models.Index(
                fields=['activity', 'user_id', 'is_revoked'],
                name='aug_act_user_revoke_idx',
            ),
        ]


# ══════════════════════════════════════════════════════════════
# 4. 商家入金记录(四态:冻结/解冻/已撤销/撤销挂起)
# ══════════════════════════════════════════════════════════════

class ActivityMerchantEarn(models.Model):
    class FrozenStatus(models.TextChoices):
        FROZEN          = 'frozen',          '已发未解冻'
        UNFROZEN        = 'unfrozen',        '已解冻可用'
        REVOKED         = 'revoked',         '退款已撤销'
        REVOKE_PENDING  = 'revoke_pending',  '撤销失败待人工'

    activity = models.ForeignKey(
        PaymentActivity, on_delete=models.CASCADE,
        related_name='merchant_earns',
    )
    merchant = models.ForeignKey(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='activity_earns',
    )
    order_no = models.CharField(max_length=32, db_index=True)
    order_type = models.CharField(
        max_length=10, choices=[('product', '商品'), ('service', '服务')],
    )
    trigger_amount = models.DecimalField(max_digits=10, decimal_places=2)
    earned_coins = models.PositiveIntegerField()

    frozen_status = models.CharField(
        max_length=20, choices=FrozenStatus.choices,
        default=FrozenStatus.FROZEN, db_index=True,
    )
    unfrozen_at = models.DateTimeField(null=True, blank=True)

    is_revoked = models.BooleanField(default=False, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_merchant_earn'
        verbose_name = '商家活动入金记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['activity', 'order_no'],
                name='uniq_merchant_earn_activity_order',
            ),
        ]
        indexes = [
            models.Index(fields=['merchant', '-created_at']),
            models.Index(fields=['frozen_status', '-created_at']),
            models.Index(fields=['order_no', 'frozen_status']),
        ]