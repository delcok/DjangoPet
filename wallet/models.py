# -*- coding: utf-8 -*-
from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction, IntegrityError
from django.db.models import F, Q
from django.utils import timezone


# ════════════════════════════════════════════════════════════════
#                        公共枚举
# ════════════════════════════════════════════════════════════════

class Currency(models.TextChoices):
    """
    通用币种枚举(用户 + 商户共用)
    🆕 新增 CASH 用于商户现金账户
    """
    POINTS = 'points', '积分'   # 用户用
    GOLD   = 'gold',   '金币'   # 用户 + 商户共用
    CASH   = 'cash',   '现金'   # 商户用


class UserOperatorRole(models.TextChoices):
    SYSTEM = 'system', '系统'
    ADMIN  = 'admin',  '管理员'
    USER   = 'user',   '用户自身'


class MerchantOperatorRole(models.TextChoices):
    SYSTEM   = 'system',   '系统'
    ADMIN    = 'admin',    '管理员'
    MERCHANT = 'merchant', '商家'


# ════════════════════════════════════════════════════════════════
#                        用户钱包(原样,仅清理未用 import)
# ════════════════════════════════════════════════════════════════

class UserWallet(models.Model):
    """用户钱包 —— 积分和金币的余额视图"""

    class Status(models.TextChoices):
        ACTIVE    = 'active',    '正常'
        SUSPENDED = 'suspended', '暂停(只进不出)'
        FROZEN    = 'frozen',    '完全冻结'

    user = models.OneToOneField(
        'user.User', on_delete=models.CASCADE,
        related_name='wallet', verbose_name='用户'
    )

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.ACTIVE, db_index=True, verbose_name='钱包状态'
    )
    status_reason = models.CharField(max_length=200, blank=True, default='', verbose_name='状态变更原因')

    # 积分
    points_balance       = models.IntegerField(default=0, verbose_name='积分余额')
    points_total_earned  = models.PositiveIntegerField(default=0, verbose_name='累计获得积分')
    points_total_spent   = models.PositiveIntegerField(default=0, verbose_name='累计消费积分')
    points_total_expired = models.PositiveIntegerField(default=0, verbose_name='累计过期积分')
    points_frozen        = models.PositiveIntegerField(default=0, verbose_name='冻结积分')

    # 金币
    gold_balance       = models.IntegerField(default=0, verbose_name='金币余额')
    gold_total_earned  = models.PositiveIntegerField(default=0, verbose_name='累计获得金币')
    gold_total_spent   = models.PositiveIntegerField(default=0, verbose_name='累计消费金币')
    gold_total_expired = models.PositiveIntegerField(default=0, verbose_name='累计过期金币')
    gold_frozen        = models.PositiveIntegerField(default=0, verbose_name='冻结金币')

    version = models.PositiveIntegerField(default=0, verbose_name='版本号')
    last_transaction_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='最近流水时间')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_wallets'
        verbose_name = '用户钱包'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-last_transaction_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(points_frozen__gte=0) & Q(gold_frozen__gte=0),
                name='uw_frozen_non_negative',
            ),
            models.CheckConstraint(
                condition=Q(points_frozen__lte=F('points_balance')) &
                          Q(gold_frozen__lte=F('gold_balance')),
                name='uw_frozen_lte_balance',
            ),
        ]

    def __str__(self):
        return f"user={self.user_id} | 积分:{self.points_balance} 金币:{self.gold_balance}"

    @property
    def points_available(self):
        return self.points_balance - self.points_frozen

    @property
    def gold_available(self):
        return self.gold_balance - self.gold_frozen

    @classmethod
    def _validate_action(cls, currency, action, amount):
        """防止「订单奖励 -100」「金币扣除用了积分 action」这类错乱"""
        A = WalletTransaction.Action
        neutral = {A.FREEZE, A.UNFREEZE}

        if action in neutral:
            if amount != 0:
                raise ValueError(f'{action} 必须 amount=0')
            return

        if action == A.REVERSE:
            return

        if amount == 0:
            raise ValueError('非冻结操作 amount 不能为 0')

        gold_income  = {A.GOLD_GRANT}
        gold_expense = {A.GOLD_EXCHANGE, A.GOLD_DEDUCT, A.GOLD_EXPIRED}
        points_income = {
            A.ORDER_REWARD, A.ADMIN_GRANT, A.SIGN_IN, A.INVITE_REWARD,
            A.REFUND_RETURN, A.ACTIVITY_REWARD, A.SYSTEM_GRANT,
        }
        points_expense = {A.ORDER_DEDUCT, A.EXCHANGE, A.EXPIRED, A.ADMIN_DEDUCT}

        if currency == Currency.POINTS:
            if action in gold_income or action in gold_expense:
                raise ValueError(f'积分币种不能用金币 action: {action}')
            if action in points_income and amount <= 0:
                raise ValueError(f'{action} 必须为正数')
            if action in points_expense and amount >= 0:
                raise ValueError(f'{action} 必须为负数')
        elif currency == Currency.GOLD:
            if action in points_income or action in points_expense:
                raise ValueError(f'金币币种不能用积分 action: {action}')
            if action in gold_income and amount <= 0:
                raise ValueError(f'{action} 必须为正数')
            if action in gold_expense and amount >= 0:
                raise ValueError(f'{action} 必须为负数')

    def change_points(self, amount, action, operator_id=None,
                      operator_role='system', related_type='', related_id=None,
                      remark='', idempotent_key=None, batch_no='',
                      expire_at=None, allow_negative=False, operator_ip=None):
        return self._change_balance(
            Currency.POINTS, amount, action,
            allow_negative=allow_negative,
            operator_id=operator_id, operator_role=operator_role,
            operator_ip=operator_ip,
            related_type=related_type, related_id=related_id,
            remark=remark, idempotent_key=idempotent_key,
            batch_no=batch_no, expire_at=expire_at,
        )

    def change_gold(self, amount, action, operator_id=None,
                    operator_role='system', related_type='', related_id=None,
                    remark='', idempotent_key=None, batch_no='',
                    allow_negative=False, operator_ip=None, expire_at=None):
        return self._change_balance(
            Currency.GOLD, amount, action,
            allow_negative=allow_negative,
            operator_id=operator_id, operator_role=operator_role,
            operator_ip=operator_ip,
            related_type=related_type, related_id=related_id,
            remark=remark, idempotent_key=idempotent_key,
            batch_no=batch_no, expire_at=expire_at,
        )

    def _change_balance(self, currency, amount, action,
                        allow_negative=False, idempotent_key=None, **kwargs):
        self._validate_action(currency, action, amount)

        if idempotent_key:
            existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        try:
            with transaction.atomic():
                w = UserWallet.objects.select_for_update().get(pk=self.pk)

                if w.status == self.Status.FROZEN:
                    raise ValueError('钱包已冻结')
                if amount < 0 and w.status == self.Status.SUSPENDED:
                    raise ValueError('钱包已暂停(只进不出)')

                if currency == Currency.POINTS:
                    new_balance = w.points_balance + amount
                    if new_balance < 0 and not allow_negative:
                        raise ValueError(f'积分不足,当前 {w.points_balance} 扣除 {abs(amount)}')
                    w.points_balance = new_balance
                    fields = ['points_balance', 'updated_at', 'last_transaction_at', 'version']
                    if amount > 0:
                        w.points_total_earned += amount
                        fields.append('points_total_earned')
                    else:
                        w.points_total_spent += abs(amount)
                        fields.append('points_total_spent')
                        if action == WalletTransaction.Action.EXPIRED:
                            w.points_total_expired += abs(amount)
                            fields.append('points_total_expired')
                    balance_after = w.points_balance
                else:
                    new_balance = w.gold_balance + amount
                    if new_balance < 0 and not allow_negative:
                        raise ValueError(f'金币不足,当前 {w.gold_balance} 扣除 {abs(amount)}')
                    w.gold_balance = new_balance
                    fields = ['gold_balance', 'updated_at', 'last_transaction_at', 'version']
                    if amount > 0:
                        w.gold_total_earned += amount
                        fields.append('gold_total_earned')
                    else:
                        w.gold_total_spent += abs(amount)
                        fields.append('gold_total_spent')
                        if action == WalletTransaction.Action.GOLD_EXPIRED:
                            w.gold_total_expired += abs(amount)
                            fields.append('gold_total_expired')
                    balance_after = w.gold_balance

                w.last_transaction_at = timezone.now()
                w.version = F('version') + 1
                w.save(update_fields=fields)
                w.refresh_from_db()

                for f in fields:
                    if hasattr(w, f):
                        setattr(self, f, getattr(w, f))

                remaining = amount if (currency == Currency.POINTS and amount > 0) else 0

                tx = WalletTransaction.objects.create(
                    wallet=w, user_id=w.user_id,
                    currency=currency, action=action,
                    amount=amount, balance_after=balance_after,
                    remaining_amount=remaining,
                    idempotent_key=idempotent_key,
                    **kwargs,
                )
                return tx

        except IntegrityError:
            if idempotent_key:
                existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
                if existing:
                    return existing
            raise

    def freeze_amount(self, currency, amount, reason='',
                      operator_id=None, operator_role='system',
                      idempotent_key=None, related_type='', related_id=None):
        if amount <= 0:
            raise ValueError('冻结数量必须大于 0')

        if idempotent_key:
            existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = UserWallet.objects.select_for_update().get(pk=self.pk)

            if currency == Currency.POINTS:
                if w.points_available < amount:
                    raise ValueError(f'可用积分不足:{w.points_available}')
                w.points_frozen += amount
                w.save(update_fields=['points_frozen', 'updated_at'])
                balance_after = w.points_balance
                self.points_frozen = w.points_frozen
            else:
                if w.gold_available < amount:
                    raise ValueError(f'可用金币不足:{w.gold_available}')
                w.gold_frozen += amount
                w.save(update_fields=['gold_frozen', 'updated_at'])
                balance_after = w.gold_balance
                self.gold_frozen = w.gold_frozen

            try:
                return WalletTransaction.objects.create(
                    wallet=w, user_id=w.user_id, currency=currency,
                    action=WalletTransaction.Action.FREEZE,
                    amount=0, balance_after=balance_after, freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or f'冻结 {amount} {currency}',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return WalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise

    def unfreeze_amount(self, currency, amount, reason='',
                        operator_id=None, operator_role='system',
                        idempotent_key=None, related_type='', related_id=None):
        if amount <= 0:
            raise ValueError('解冻数量必须大于 0')

        if idempotent_key:
            existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = UserWallet.objects.select_for_update().get(pk=self.pk)

            if currency == Currency.POINTS:
                if w.points_frozen < amount:
                    raise ValueError(f'冻结积分不足:{w.points_frozen}')
                w.points_frozen -= amount
                w.save(update_fields=['points_frozen', 'updated_at'])
                balance_after = w.points_balance
                self.points_frozen = w.points_frozen
            else:
                if w.gold_frozen < amount:
                    raise ValueError(f'冻结金币不足:{w.gold_frozen}')
                w.gold_frozen -= amount
                w.save(update_fields=['gold_frozen', 'updated_at'])
                balance_after = w.gold_balance
                self.gold_frozen = w.gold_frozen

            try:
                return WalletTransaction.objects.create(
                    wallet=w, user_id=w.user_id, currency=currency,
                    action=WalletTransaction.Action.UNFREEZE,
                    amount=0, balance_after=balance_after, freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or f'解冻 {amount} {currency}',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return WalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise

    def reverse_transaction(self, tx, reason='', operator_id=None,
                            operator_role='admin'):
        if tx.wallet_id != self.pk:
            raise ValueError('流水与钱包不匹配')
        if tx.status != WalletTransaction.Status.NORMAL:
            raise ValueError(f'该流水已是 {tx.get_status_display()} 状态')
        if tx.amount == 0:
            raise ValueError('0 值流水无需撤销')

        idempotent_key = f'reverse_tx_{tx.id}'

        with transaction.atomic():
            tx_locked = WalletTransaction.objects.select_for_update().get(pk=tx.pk)
            if tx_locked.status != WalletTransaction.Status.NORMAL:
                raise ValueError('该流水已被撤销(并发)')

            reverse_tx = self._change_balance(
                currency=tx_locked.currency,
                amount=-tx_locked.amount,
                action=WalletTransaction.Action.REVERSE,
                allow_negative=True,
                operator_id=operator_id,
                operator_role=operator_role,
                remark=reason or f'撤销流水 #{tx_locked.id}',
                related_type='wallet_tx',
                related_id=tx_locked.id,
                idempotent_key=idempotent_key,
            )
            tx_locked.status = WalletTransaction.Status.REVERSED
            tx_locked.reversed_by_tx = reverse_tx
            tx_locked.save(update_fields=['status', 'reversed_by_tx'])
            return reverse_tx

    def spend_points_fifo(self, amount, action=None, allow_untracked_fallback=True, **kwargs):
        """
        按 FIFO 消费积分。

        重要修复:
        1. 原实现先扣 remaining_amount,再调用 change_points;如果后一步失败,明细会先被扣掉。
           现在把 FIFO 明细扣减和余额流水放进同一个事务。
        2. 老数据 / 人工调整可能只有 points_balance,没有对应的 remaining_amount 可扣明细。
           这种情况下,只要 points_available 足够,允许用未追踪余额兜底,避免出现
           “FIFO 扣减失败,缺 N 积分”但用户余额明明够的情况。
        3. 支持 idempotent_key,避免补签接口重试时重复扣 FIFO 明细。
        """
        if amount <= 0:
            raise ValueError('消费数量必须大于 0')
        action = action or WalletTransaction.Action.EXCHANGE

        idempotent_key = kwargs.get('idempotent_key')
        if idempotent_key:
            existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = UserWallet.objects.select_for_update().get(pk=self.pk)
            if w.points_available < amount:
                raise ValueError(f'可用积分不足:{w.points_available}')

            sources = list(
                WalletTransaction.objects.select_for_update().filter(
                    wallet=w, currency=Currency.POINTS,
                    status=WalletTransaction.Status.NORMAL,
                    remaining_amount__gt=0,
                ).order_by(F('expire_at').asc(nulls_last=True), 'created_at')
            )

            left = amount
            for src in sources:
                if left <= 0:
                    break
                deduct = min(src.remaining_amount, left)
                src.remaining_amount -= deduct
                src.save(update_fields=['remaining_amount'])
                left -= deduct

            if left > 0 and not allow_untracked_fallback:
                raise ValueError(f'FIFO 扣减失败,缺 {left} 积分')

            # 余额流水必须和 remaining_amount 扣减处于同一个数据库事务内。
            return self._change_balance(
                Currency.POINTS,
                -amount,
                action=action,
                **kwargs,
            )


# ════════════════════════════════════════════════════════════════
#                        用户钱包流水(原样)
# ════════════════════════════════════════════════════════════════

class WalletTransaction(models.Model):
    class Status(models.TextChoices):
        NORMAL   = 'normal',   '正常'
        REVERSED = 'reversed', '已撤销'

    class Action(models.TextChoices):
        ORDER_REWARD    = 'order_reward',    '订单奖励积分'
        ADMIN_GRANT     = 'admin_grant',     '管理员发放'
        SIGN_IN         = 'sign_in',         '签到奖励'
        INVITE_REWARD   = 'invite_reward',   '邀请奖励'
        REFUND_RETURN   = 'refund_return',   '退款返还积分'
        ACTIVITY_REWARD = 'activity_reward', '活动奖励'
        SYSTEM_GRANT    = 'system_grant',    '系统发放'
        ORDER_DEDUCT = 'order_deduct', '订单抵扣积分'
        EXCHANGE     = 'exchange',     '积分兑换'
        EXPIRED      = 'expired',      '积分过期清零'
        ADMIN_DEDUCT = 'admin_deduct', '管理员扣除'
        GOLD_GRANT    = 'gold_grant',    '金币发放'
        GOLD_EXCHANGE = 'gold_exchange', '金币兑换'
        GOLD_DEDUCT   = 'gold_deduct',   '金币抵扣消费'
        GOLD_EXPIRED  = 'gold_expired',  '金币过期清零'
        FREEZE   = 'freeze',   '冻结'
        UNFREEZE = 'unfreeze', '解冻'
        REVERSE = 'reverse', '撤销反向流水'

    wallet = models.ForeignKey(
        UserWallet, on_delete=models.CASCADE,
        related_name='transactions', verbose_name='钱包'
    )
    user_id = models.PositiveIntegerField(db_index=True, verbose_name='用户ID')

    currency = models.CharField(max_length=10, choices=Currency.choices, verbose_name='币种')
    action   = models.CharField(max_length=30, choices=Action.choices, db_index=True, verbose_name='动作')

    amount        = models.IntegerField(verbose_name='变动数量')
    balance_after = models.IntegerField(verbose_name='变动后余额')

    remaining_amount = models.PositiveIntegerField(default=0, db_index=True, verbose_name='本笔剩余额度')
    freeze_delta     = models.PositiveIntegerField(default=0, verbose_name='冻结变动量')

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.NORMAL, db_index=True, verbose_name='流水状态'
    )
    reversed_by_tx = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT, related_name='reverses',
    )

    operator_id   = models.PositiveIntegerField(null=True, blank=True, db_index=True, verbose_name='操作人ID')
    operator_role = models.CharField(
        max_length=20, choices=UserOperatorRole.choices,
        default=UserOperatorRole.SYSTEM, verbose_name='操作人角色'
    )
    operator_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='操作IP')

    related_type = models.CharField(max_length=30, blank=True, default='', verbose_name='关联对象类型')
    related_id   = models.PositiveIntegerField(null=True, blank=True, verbose_name='关联对象ID')

    batch_no       = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='批次号')
    remark         = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')
    idempotent_key = models.CharField(max_length=64, unique=True, null=True, blank=True, verbose_name='幂等键')
    expire_at      = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')
    created_at     = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'wallet_transactions'
        verbose_name = '钱包流水'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user_id', 'currency', '-created_at']),
            models.Index(fields=['wallet', 'currency', '-created_at']),
            models.Index(fields=['related_type', 'related_id']),
            models.Index(fields=['batch_no']),
            models.Index(fields=['expire_at']),
            models.Index(fields=['status', '-created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(action__in=['freeze', 'unfreeze']) | Q(amount=0),
                name='wt_neutral_action_zero_amount',
            ),
        ]

    def __str__(self):
        return f"[{self.get_action_display()}] {self.amount} {self.get_currency_display()}"


# ════════════════════════════════════════════════════════════════
#                        钱包状态变更审计(原样)
# ════════════════════════════════════════════════════════════════

class WalletStatusLog(models.Model):
    wallet = models.ForeignKey(
        UserWallet, on_delete=models.CASCADE,
        related_name='status_logs', verbose_name='钱包'
    )
    old_status    = models.CharField(max_length=20)
    new_status    = models.CharField(max_length=20)
    reason        = models.CharField(max_length=200, blank=True, default='')
    operator_id   = models.PositiveIntegerField(null=True, blank=True)
    operator_role = models.CharField(max_length=20, choices=UserOperatorRole.choices, default=UserOperatorRole.ADMIN)
    operator_ip   = models.GenericIPAddressField(null=True, blank=True)
    created_at    = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'user_wallet_status_logs'
        verbose_name = '钱包状态变更日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [models.Index(fields=['wallet', '-created_at'])]

class SignInConfig(models.Model):
    """
    签到奖励配置(全局单例,pk 固定 1)
    管理员改这张表 = 改签到规则,不用发版。UserSignIn 通过 load() 读当前配置。
    """
    SINGLETON_ID = 1

    cycle_rewards = models.JSONField(
        default=list, verbose_name='循环奖励(积分数组)',
        help_text='如 [10,10,10,15,15,20,40],按连签天数循环取值',
    )
    sign_in_expire_days = models.PositiveIntegerField(
        default=0, verbose_name='签到积分有效期(天)',
        help_text='0=永不过期;>0 则 N 天后过期',
    )
    makeup_enabled       = models.BooleanField(default=True, verbose_name='是否开启补签')
    makeup_cost_points   = models.PositiveIntegerField(default=20, verbose_name='补签消耗积分')
    makeup_max_back_days = models.PositiveIntegerField(default=7, verbose_name='最多补签最近N天')

    is_active = models.BooleanField(default=True, verbose_name='签到功能总开关')

    updated_by = models.PositiveIntegerField(null=True, blank=True, verbose_name='最后修改人ID')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sign_in_config'
        verbose_name = '签到配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"签到配置 | 循环{self.cycle_rewards} | 补签{'开' if self.makeup_enabled else '关'}"

    @classmethod
    def load(cls):
        """取单例;不存在则用默认值创建。"""
        obj, _ = cls.objects.get_or_create(
            pk=cls.SINGLETON_ID,
            defaults={
                'cycle_rewards': [10, 10, 10, 15, 15, 20, 40],
                'sign_in_expire_days': 0,
                'makeup_cost_points': 20,
                'makeup_max_back_days': 7,
            },
        )
        return obj

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID   # 强制单例
        super().save(*args, **kwargs)


class UserSignIn(models.Model):
    """用户每日签到 / 补签记录(规则配置见 SignInConfig)"""

    user = models.ForeignKey(
        'user.User', on_delete=models.CASCADE,
        related_name='sign_ins', verbose_name='用户',
    )
    sign_date       = models.DateField(verbose_name='签到日期(本地时区)')
    reward_points   = models.PositiveIntegerField(default=0, verbose_name='本次获得积分')
    continuous_days = models.PositiveIntegerField(default=1, verbose_name='连续签到天数(快照)')

    is_makeup   = models.BooleanField(default=False, verbose_name='是否补签')
    makeup_cost = models.PositiveIntegerField(default=0, verbose_name='补签消耗积分')

    transaction = models.ForeignKey(
        'WalletTransaction', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
        verbose_name='关联积分流水',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='记录时间')

    class Meta:
        db_table = 'user_sign_in'
        verbose_name = '用户签到记录'
        verbose_name_plural = verbose_name
        ordering = ['-sign_date']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'sign_date'],
                name='uniq_user_sign_in_per_day',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-sign_date']),
            models.Index(fields=['sign_date']),        # 🆕 统计按天聚合用
        ]

    def __str__(self):
        flag = '补签' if self.is_makeup else '签到'
        return f"user={self.user_id} | {self.sign_date} | {flag} +{self.reward_points}"

    # ════════════════════ 奖励 & 连签计算 ════════════════════

    @classmethod
    def reward_for_streak(cls, streak, cfg=None):
        """
        根据连续签到天数取奖励。

        产品规则: 配置多少档就最多递增到多少档；超过最后一档后，持续使用最后一档，
        不再按周期取模。示例 [10,10,10,15,15,20,40]:
        第 1~7 天按数组，第 8 天及以后都给 40。
        """
        cfg = cfg or SignInConfig.load()
        rewards = cfg.cycle_rewards or [10]
        if streak <= 0:
            return int(rewards[0])
        idx = min(int(streak), len(rewards)) - 1
        return int(rewards[idx])

    @classmethod
    def calc_current_streak(cls, user, today=None):
        """从今天(或昨天)向前数连续签到天数,对补签鲁棒。"""
        today = today or timezone.localdate()
        dates = set(
            cls.objects.filter(user=user, sign_date__lte=today)
            .values_list('sign_date', flat=True)
        )
        if today in dates:
            cursor = today
        elif (today - timedelta(days=1)) in dates:
            cursor = today - timedelta(days=1)
        else:
            return 0
        streak = 0
        while cursor in dates:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    @classmethod
    def next_reward(cls, user, today=None, cfg=None):
        today = today or timezone.localdate()
        cfg = cfg or SignInConfig.load()
        return cls.reward_for_streak(cls.calc_current_streak(user, today) + 1, cfg)

    @classmethod
    def longest_streak(cls, user):
        dates = sorted(cls.objects.filter(user=user).values_list('sign_date', flat=True))
        if not dates:
            return 0
        longest = run = 1
        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] + timedelta(days=1):
                run += 1
            elif dates[i] == dates[i - 1]:
                continue
            else:
                run = 1
            longest = max(longest, run)
        return longest

    @classmethod
    def _continuous_segment_bounds(cls, user, anchor_date):
        """返回包含 anchor_date 的连续签到段 [start, end]。调用前应确保 anchor 已有记录。"""
        dates = set(
            cls.objects.filter(user=user).values_list('sign_date', flat=True)
        )
        if anchor_date not in dates:
            return anchor_date, anchor_date

        start = anchor_date
        while (start - timedelta(days=1)) in dates:
            start -= timedelta(days=1)

        end = anchor_date
        while (end + timedelta(days=1)) in dates:
            end += timedelta(days=1)

        return start, end

    @classmethod
    def _sync_segment_rewards(cls, user, anchor_date, cfg=None, operator_ip=None, reason='makeup'):
        """
        重算一个连续签到段内所有记录的 continuous_days 和应得奖励。

        为什么需要这一步:
        - 补签会把断开的日期桥接起来，后面的已签日期也应该进入更长连续天数。
        - 用户可能先补近日期，再补远日期；奖励必须和最终连续段一致，而不能受补签顺序影响。
        - 已经发过的奖励不倒扣；如果新规则下应得更多，只补发差额。
        """
        cfg = cfg or SignInConfig.load()
        start, end = cls._continuous_segment_bounds(user, anchor_date)
        records = list(
            cls.objects.select_for_update()
            .filter(user=user, sign_date__gte=start, sign_date__lte=end)
            .order_by('sign_date')
        )

        wallet = None
        total_reward_delta = 0
        repriced_count = 0
        anchor_record = None

        for index, record in enumerate(records, start=1):
            expected_streak = index
            expected_reward = cls.reward_for_streak(expected_streak, cfg)
            reward_delta = max(0, expected_reward - int(record.reward_points or 0))

            update_fields = []
            if record.continuous_days != expected_streak:
                record.continuous_days = expected_streak
                update_fields.append('continuous_days')

            if reward_delta > 0:
                wallet = wallet or UserWallet.objects.get_or_create(user=user)[0]
                expire_at = (
                    timezone.now() + timedelta(days=cfg.sign_in_expire_days)
                    if cfg.sign_in_expire_days > 0 else None
                )
                tx = wallet.change_points(
                    amount=reward_delta,
                    action=WalletTransaction.Action.SIGN_IN,
                    operator_ip=operator_ip,
                    related_type='sign_in_makeup' if record.is_makeup else 'sign_in',
                    related_id=record.id,
                    remark=(
                        f'连续签到奖励校准 {record.sign_date.isoformat()} '
                        f'第{expected_streak}天 +{reward_delta}积分'
                    ),
                    idempotent_key=(
                        f'signin_reward_sync_{user.id}_'
                        f'{record.sign_date.isoformat()}_{expected_reward}'
                    ),
                    expire_at=expire_at,
                )
                record.reward_points = int(record.reward_points or 0) + reward_delta
                update_fields.append('reward_points')
                if not record.transaction_id:
                    record.transaction = tx
                    update_fields.append('transaction')
                total_reward_delta += reward_delta
                repriced_count += 1

            if update_fields:
                record.save(update_fields=update_fields)

            if record.sign_date == anchor_date:
                anchor_record = record

        return {
            'start': start,
            'end': end,
            'record': anchor_record,
            'total_reward_delta': total_reward_delta,
            'repriced_count': repriced_count,
            'segment_days': len(records),
        }

    # ════════════════════ 签到 ════════════════════

    @classmethod
    def do_sign_in(cls, user, operator_ip=None, reward_override=None):
        """执行签到,返回 (record, created)。"""
        today = timezone.localdate()
        cfg = SignInConfig.load()
        if not cfg.is_active:
            raise ValueError('签到功能已关闭')

        with transaction.atomic():
            record, created = cls.objects.get_or_create(
                user=user, sign_date=today,
                defaults={'reward_points': 0, 'continuous_days': 1, 'is_makeup': False},
            )
            if not created:
                return record, False

            # 默认按最终连续段重算奖励；这样如果之前有补签记录，今天会自然拿到对应档位。
            if reward_override is None:
                sync_result = cls._sync_segment_rewards(
                    user, today, cfg=cfg, operator_ip=operator_ip, reason='sign_in'
                )
                record = sync_result['record'] or record
            else:
                streak = cls.calc_current_streak(user, today)
                reward = int(reward_override)
                tx = None
                if reward > 0:
                    wallet, _ = UserWallet.objects.get_or_create(user=user)
                    expire_at = (
                        timezone.now() + timedelta(days=cfg.sign_in_expire_days)
                        if cfg.sign_in_expire_days > 0 else None
                    )
                    tx = wallet.change_points(
                        amount=reward,
                        action=WalletTransaction.Action.SIGN_IN,
                        operator_ip=operator_ip,
                        related_type='sign_in', related_id=record.id,
                        remark=f'每日签到 第{streak}天 +{reward}积分',
                        idempotent_key=f'signin_{user.id}_{today.isoformat()}',
                        expire_at=expire_at,
                    )
                record.reward_points = reward
                record.continuous_days = streak
                if tx:
                    record.transaction = tx
                record.save(update_fields=['reward_points', 'continuous_days', 'transaction'])

        return record, True

    # ════════════════════ 补签 ════════════════════

    @classmethod
    def do_makeup(cls, user, target_date, operator_ip=None, cost=None):
        """
        补签过去日期。

        规则:
        1. 先扣补签成本，成本不能由本次补签奖励抵扣。
        2. 创建补签记录后，重算该日期所在的完整连续签到段。
        3. 补签奖励按补签后形成的连续天数计算；超过配置最后一天后持续用最后一档。
        4. 如果补签桥接了后续已签日期，后续日期应得奖励变高时只补发差额，不倒扣。
        """
        today = timezone.localdate()
        cfg = SignInConfig.load()
        if not cfg.is_active:
            raise ValueError('签到功能已关闭')
        if not cfg.makeup_enabled:
            raise ValueError('补签功能未开启')

        cost = int(cost) if cost is not None else cfg.makeup_cost_points

        if target_date >= today:
            raise ValueError('只能补签过去的日期')
        if target_date < today - timedelta(days=cfg.makeup_max_back_days):
            raise ValueError(f'最多补签最近 {cfg.makeup_max_back_days} 天内')

        try:
            with transaction.atomic():
                if cls.objects.filter(user=user, sign_date=target_date).exists():
                    raise ValueError('该日期已签到,无需补签')

                wallet, _ = UserWallet.objects.get_or_create(user=user)

                if cost > 0:
                    if wallet.points_available < cost:
                        raise ValueError(f'积分不足,补签需要 {cost} 积分')
                    wallet.spend_points_fifo(
                        cost,
                        action=WalletTransaction.Action.EXCHANGE,
                        operator_ip=operator_ip,
                        related_type='sign_in_makeup',
                        remark=f'补签 {target_date.isoformat()} 消耗 {cost} 积分',
                        idempotent_key=f'makeup_cost_{user.id}_{target_date.isoformat()}',
                    )

                record = cls.objects.create(
                    user=user,
                    sign_date=target_date,
                    reward_points=0,
                    continuous_days=1,
                    is_makeup=True,
                    makeup_cost=cost,
                )

                sync_result = cls._sync_segment_rewards(
                    user, target_date, cfg=cfg, operator_ip=operator_ip, reason='makeup'
                )
                record = sync_result['record'] or record

                # 给 view 层使用的瞬时字段，不入库。
                record._makeup_target_reward = int(record.reward_points or 0)
                record._makeup_total_reward = int(sync_result['total_reward_delta'] or 0)
                record._makeup_net_delta = record._makeup_total_reward - cost
                record._makeup_repriced_count = int(sync_result['repriced_count'] or 0)
                record._makeup_segment_days = int(sync_result['segment_days'] or 0)
        except IntegrityError:
            raise ValueError('该日期正在补签或已签到,请勿重复操作')

        return record

# ════════════════════════════════════════════════════════════════
#                        积分规则(原样)
# ════════════════════════════════════════════════════════════════

class PointsRule(models.Model):
    class Trigger(models.TextChoices):
        ORDER_COMPLETE = 'order_complete', '订单完成'
        FIRST_ORDER    = 'first_order',    '首单奖励'
        REVIEW         = 'review',         '评价奖励'
        SHARE          = 'share',          '分享奖励'
        SIGN_IN        = 'sign_in',        '每日签到'
        INVITE         = 'invite',         '邀请注册'
        CUSTOM         = 'custom',         '自定义'

    class CalcType(models.TextChoices):
        FIXED   = 'fixed',   '固定值'
        PERCENT = 'percent', '按订单金额百分比'
        TIERED  = 'tiered',  '阶梯规则'

    name        = models.CharField(max_length=50, verbose_name='规则名称')
    merchant_id = models.PositiveIntegerField(null=True, blank=True, db_index=True, verbose_name='商家ID')
    trigger     = models.CharField(max_length=30, choices=Trigger.choices, verbose_name='触发条件')
    calc_type   = models.CharField(max_length=20, choices=CalcType.choices, default=CalcType.FIXED)
    value       = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='数值')
    rule_config = models.JSONField(null=True, blank=True)

    max_points_per_tx = models.PositiveIntegerField(default=0, verbose_name='单笔上限')
    daily_cap         = models.PositiveIntegerField(default=0, verbose_name='每日上限')
    expire_days       = models.PositiveIntegerField(default=0, verbose_name='有效期天数')

    is_active = models.BooleanField(default=True)
    priority  = models.PositiveSmallIntegerField(default=0)

    start_at = models.DateTimeField(null=True, blank=True)
    end_at   = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        'user.User', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='created_points_rules',
    )
    updated_by = models.ForeignKey(
        'user.User', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='updated_points_rules',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'points_rules'
        verbose_name = '积分规则'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['merchant_id', 'trigger', 'is_active'])]

    def __str__(self):
        scope = f"商家{self.merchant_id}" if self.merchant_id else "全局"
        return f"[{scope}] {self.name}"


# ════════════════════════════════════════════════════════════════
#                        商户钱包(🆕 增加金币 + 🔧 优化)
# ════════════════════════════════════════════════════════════════

class MerchantWallet(models.Model):
    """
    商户钱包 —— 同时持有现金账户和金币账户

    现金:Decimal(2 位小数),用于订单收入 / 提现
    金币:Integer,用于平台营销活动、推广位购买、活动激励等
    """

    class Status(models.TextChoices):
        ACTIVE    = 'active',    '正常'
        SUSPENDED = 'suspended', '暂停提现'
        FROZEN    = 'frozen',    '完全冻结'

    merchant = models.OneToOneField(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='wallet', verbose_name='商家'
    )

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.ACTIVE, db_index=True
    )
    status_reason = models.CharField(max_length=200, blank=True, default='')

    # ─────── 现金账户(原有)───────
    balance            = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='可用余额')
    frozen_amount      = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='冻结金额')
    pending_settlement = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='待结算')

    total_income       = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_commission   = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_refunded     = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_withdrawn    = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_withdraw_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # ─────── 🆕 金币账户(新增)───────
    gold_balance       = models.IntegerField(default=0, verbose_name='金币余额')
    gold_frozen        = models.PositiveIntegerField(default=0, verbose_name='冻结金币')
    gold_total_earned  = models.PositiveIntegerField(default=0, verbose_name='累计获得金币')
    gold_total_spent   = models.PositiveIntegerField(default=0, verbose_name='累计消费金币')
    gold_total_expired = models.PositiveIntegerField(default=0, verbose_name='累计过期金币')

    pay_password = models.CharField(max_length=128, blank=True, default='')

    version = models.PositiveIntegerField(default=0)
    last_transaction_at = models.DateTimeField(null=True, blank=True, db_index=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'merchant_wallet'
        verbose_name = '商户钱包'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['status'])]
        constraints = [
            # 🔧 把金币的非负检查也加进来
            models.CheckConstraint(
                condition=Q(balance__gte=0) &
                          Q(frozen_amount__gte=0) &
                          Q(pending_settlement__gte=0) &
                          Q(gold_balance__gte=0) &
                          Q(gold_frozen__gte=0),
                name='mw_balances_non_negative',
            ),
            # 🔧 冻结额必须 ≤ 余额(现金 + 金币)
            models.CheckConstraint(
                condition=Q(frozen_amount__lte=F('balance')) &
                          Q(gold_frozen__lte=F('gold_balance')),
                name='mw_frozen_lte_balance',
            ),
        ]

    def __str__(self):
        return (f"merchant={self.merchant_id} | "
                f"现金:{self.balance}(待结算:{self.pending_settlement}) | "
                f"金币:{self.gold_balance}")

    @property
    def available_balance(self):
        """可用现金 = 可用余额 - 冻结"""
        return self.balance - self.frozen_amount

    @property
    def gold_available(self):
        """🆕 可用金币"""
        return self.gold_balance - self.gold_frozen

    # ════════════════════════════════════════════════════════════
    # 🆕 action × currency 校验
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _validate_action(cls, currency, action, amount):
        """防止「现金账户写了金币 action」「佣金扣除写正数」等错乱"""
        A = MerchantWalletTransaction.Action
        neutral = {A.FREEZE, A.UNFREEZE, A.REVERSE}

        if action in neutral:
            return
        if amount == 0:
            raise ValueError('非中性操作 amount 不能为 0')

        cash_income = {
            A.ORDER_INCOME, A.SETTLE, A.REFUND_REVOKE,
            A.ADJUSTMENT_ADD, A.PENDING_IN,
        }
        cash_expense = {
            A.COMMISSION_DEDUCT, A.REFUND_DEDUCT,
            A.WITHDRAW_SUCCESS, A.WITHDRAW_FEE,
            A.ADJUSTMENT_SUB, A.PENDING_DEDUCT,
        }
        gold_income = {
            A.GOLD_GRANT, A.GOLD_REWARD, A.GOLD_PROMOTION, A.GOLD_ADJUST_ADD,
        }
        gold_expense = {
            A.GOLD_SPEND, A.GOLD_DEDUCT, A.GOLD_EXPIRED, A.GOLD_ADJUST_SUB,
        }

        if currency == Currency.CASH:
            if action in gold_income or action in gold_expense:
                raise ValueError(f'现金账户不能用金币 action: {action}')
            if action in cash_income and amount <= 0:
                raise ValueError(f'{action} 必须为正数')
            if action in cash_expense and amount >= 0:
                raise ValueError(f'{action} 必须为负数')
        elif currency == Currency.GOLD:
            if action in cash_income or action in cash_expense:
                raise ValueError(f'金币账户不能用现金 action: {action}')
            if action in gold_income and amount <= 0:
                raise ValueError(f'{action} 必须为正数')
            if action in gold_expense and amount >= 0:
                raise ValueError(f'{action} 必须为负数')

    # ════════════════════════════════════════════════════════════
    # 现金账户:可用余额变动(🔧 加入 version 递增)
    # ════════════════════════════════════════════════════════════

    def change_balance(self, amount, action, operator_id=None,
                       operator_role='system', related_order_no='',
                       related_type='', related_id=None,
                       remark='', idempotent_key=None,
                       batch_no='', operator_ip=None,
                       allow_negative=False):
        """
        现金可用余额变动

        ⚠️ 注意:CheckConstraint 强制 balance >= 0,
        即使 allow_negative=True 也会被 DB 拒绝。如确需负余额场景,
        请先去掉 mw_balances_non_negative 约束。
        """
        amount = Decimal(str(amount))
        self._validate_action(Currency.CASH, action, amount)
        A = MerchantWalletTransaction.Action

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        try:
            with transaction.atomic():
                w = MerchantWallet.objects.select_for_update().get(pk=self.pk)

                if amount < 0 and w.status == self.Status.FROZEN:
                    raise ValueError('钱包已冻结,无法扣款')

                new_balance = w.balance + amount
                if new_balance < 0 and not allow_negative:
                    raise ValueError(f'余额不足,当前 {w.balance} 扣除 {abs(amount)}')

                w.balance = new_balance
                # 🔧 加入 version 递增
                fields = ['balance', 'updated_at', 'last_transaction_at', 'version']

                if action in {A.ADJUSTMENT_ADD, A.REFUND_REVOKE} and amount > 0:
                    w.total_income += amount
                    fields.append('total_income')
                if action == A.COMMISSION_DEDUCT:
                    w.total_commission += abs(amount)
                    fields.append('total_commission')
                if action == A.REFUND_DEDUCT:
                    w.total_refunded += abs(amount)
                    fields.append('total_refunded')
                if action == A.WITHDRAW_SUCCESS:
                    w.total_withdrawn += abs(amount)
                    fields.append('total_withdrawn')
                if action == A.WITHDRAW_FEE:
                    w.total_withdraw_fee += abs(amount)
                    fields.append('total_withdraw_fee')

                w.last_transaction_at = timezone.now()
                w.version = F('version') + 1
                w.save(update_fields=fields)
                w.refresh_from_db()

                for f in fields:
                    if hasattr(w, f):
                        setattr(self, f, getattr(w, f))

                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.CASH,
                    action=action, amount=amount,
                    balance_after=w.balance,
                    operator_id=operator_id, operator_role=operator_role,
                    related_order_no=related_order_no,
                    related_type=related_type, related_id=related_id,
                    remark=remark, idempotent_key=idempotent_key,
                    batch_no=batch_no, operator_ip=operator_ip,
                )
        except IntegrityError:
            if idempotent_key:
                existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
                if existing:
                    return existing
            raise

    # ════════════════════════════════════════════════════════════
    # 现金账户:待结算变动(原样,加 currency=CASH)
    # ════════════════════════════════════════════════════════════

    def change_pending(self, amount, action, operator_id=None,
                       operator_role='system', related_order_no='',
                       related_type='', related_id=None,
                       remark='', idempotent_key=None,
                       batch_no='', operator_ip=None):
        amount = Decimal(str(amount))
        self._validate_action(Currency.CASH, action, amount)

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        try:
            with transaction.atomic():
                w = MerchantWallet.objects.select_for_update().get(pk=self.pk)

                if w.status == self.Status.FROZEN:
                    raise ValueError('钱包已冻结')

                new_pending = w.pending_settlement + amount
                if new_pending < 0:
                    raise ValueError(f'待结算金额不足:{w.pending_settlement}')

                w.pending_settlement = new_pending
                w.save(update_fields=['pending_settlement', 'updated_at'])
                self.pending_settlement = w.pending_settlement

                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.CASH,
                    action=action, amount=amount,
                    balance_after=w.balance, pending_after=w.pending_settlement,
                    operator_id=operator_id, operator_role=operator_role,
                    related_order_no=related_order_no,
                    related_type=related_type, related_id=related_id,
                    remark=remark, idempotent_key=idempotent_key,
                    batch_no=batch_no, operator_ip=operator_ip,
                )
        except IntegrityError:
            if idempotent_key:
                existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
                if existing:
                    return existing
            raise

    def settle_pending(self, amount, operator_id=None,
                       operator_role='system', related_order_no='',
                       related_type='', related_id=None,
                       remark='', idempotent_key=None, batch_no=''):
        """待结算转可用:pending -amount,balance +amount,total_income +amount"""
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError('结算金额必须大于 0')

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        try:
            with transaction.atomic():
                w = MerchantWallet.objects.select_for_update().get(pk=self.pk)

                if w.status == self.Status.FROZEN:
                    raise ValueError('钱包已冻结,无法结算')

                if w.pending_settlement < amount:
                    raise ValueError(f'待结算金额不足:{w.pending_settlement}')

                w.pending_settlement -= amount
                w.balance += amount
                w.total_income += amount
                w.last_transaction_at = timezone.now()
                w.version = F('version') + 1
                w.save(update_fields=[
                    'pending_settlement', 'balance', 'total_income',
                    'last_transaction_at', 'updated_at', 'version',
                ])
                w.refresh_from_db()

                for f in ('pending_settlement', 'balance', 'total_income', 'version'):
                    setattr(self, f, getattr(w, f))

                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.CASH,
                    action=MerchantWalletTransaction.Action.SETTLE,
                    amount=amount, balance_after=w.balance,
                    pending_after=w.pending_settlement,
                    operator_id=operator_id, operator_role=operator_role,
                    related_order_no=related_order_no,
                    related_type=related_type, related_id=related_id,
                    remark=remark or f'待结算转可用 ¥{amount}',
                    idempotent_key=idempotent_key,
                    batch_no=batch_no,
                )
        except IntegrityError:
            if idempotent_key:
                existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
                if existing:
                    return existing
            raise

    # ════════════════════════════════════════════════════════════
    # 🆕 金币账户:余额变动
    # ════════════════════════════════════════════════════════════

    def change_gold(self, amount, action, operator_id=None,
                    operator_role='system', related_type='', related_id=None,
                    related_order_no='', remark='', idempotent_key=None,
                    batch_no='', operator_ip=None, allow_negative=False):
        """
        商户金币变动(整数)

        正数 = 收入(GOLD_GRANT / GOLD_REWARD / GOLD_PROMOTION / GOLD_ADJUST_ADD)
        负数 = 支出(GOLD_SPEND / GOLD_DEDUCT / GOLD_EXPIRED / GOLD_ADJUST_SUB)
        """
        amount = int(amount)
        self._validate_action(Currency.GOLD, action, amount)
        A = MerchantWalletTransaction.Action

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        try:
            with transaction.atomic():
                w = MerchantWallet.objects.select_for_update().get(pk=self.pk)

                if w.status == self.Status.FROZEN:
                    raise ValueError('钱包已冻结')
                if amount < 0 and w.status == self.Status.SUSPENDED:
                    raise ValueError('钱包已暂停(只进不出)')

                new_balance = w.gold_balance + amount
                if new_balance < 0 and not allow_negative:
                    raise ValueError(f'金币不足,当前 {w.gold_balance} 扣除 {abs(amount)}')

                w.gold_balance = new_balance
                fields = ['gold_balance', 'updated_at', 'last_transaction_at', 'version']

                if amount > 0:
                    w.gold_total_earned += amount
                    fields.append('gold_total_earned')
                else:
                    w.gold_total_spent += abs(amount)
                    fields.append('gold_total_spent')
                    if action == A.GOLD_EXPIRED:
                        w.gold_total_expired += abs(amount)
                        fields.append('gold_total_expired')

                w.last_transaction_at = timezone.now()
                w.version = F('version') + 1
                w.save(update_fields=fields)
                w.refresh_from_db()

                for f in fields:
                    if hasattr(w, f):
                        setattr(self, f, getattr(w, f))

                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.GOLD,
                    action=action,
                    amount=Decimal(amount),  # 用 Decimal(int) 存储,精度无损
                    balance_after=Decimal(w.gold_balance),
                    operator_id=operator_id, operator_role=operator_role,
                    related_order_no=related_order_no,
                    related_type=related_type, related_id=related_id,
                    remark=remark, idempotent_key=idempotent_key,
                    batch_no=batch_no, operator_ip=operator_ip,
                )
        except IntegrityError:
            if idempotent_key:
                existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
                if existing:
                    return existing
            raise

    # ════════════════════════════════════════════════════════════
    # 现金冻结 / 解冻(原样,加 currency=CASH)
    # ════════════════════════════════════════════════════════════

    def freeze(self, amount, reason='', operator_id=None,
               operator_role='system', idempotent_key=None,
               related_type='', related_id=None):
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError('冻结金额必须大于 0')

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = MerchantWallet.objects.select_for_update().get(pk=self.pk)
            if w.available_balance < amount:
                raise ValueError(f'可用余额不足:{w.available_balance}')

            w.frozen_amount += amount
            w.save(update_fields=['frozen_amount', 'updated_at'])
            self.frozen_amount = w.frozen_amount

            try:
                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.CASH,
                    action=MerchantWalletTransaction.Action.FREEZE,
                    amount=Decimal('0'), balance_after=w.balance, freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or '资金冻结',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return MerchantWalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise

    def unfreeze(self, amount, reason='', operator_id=None,
                 operator_role='system', idempotent_key=None,
                 related_type='', related_id=None):
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError('解冻金额必须大于 0')

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = MerchantWallet.objects.select_for_update().get(pk=self.pk)
            if w.frozen_amount < amount:
                raise ValueError(f'冻结金额不足:{w.frozen_amount}')

            w.frozen_amount -= amount
            w.save(update_fields=['frozen_amount', 'updated_at'])
            self.frozen_amount = w.frozen_amount

            try:
                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.CASH,
                    action=MerchantWalletTransaction.Action.UNFREEZE,
                    amount=Decimal('0'), balance_after=w.balance, freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or '资金解冻',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return MerchantWalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise

    # ════════════════════════════════════════════════════════════
    # 🆕 金币冻结 / 解冻
    # ════════════════════════════════════════════════════════════

    def freeze_gold(self, amount, reason='', operator_id=None,
                    operator_role='system', idempotent_key=None,
                    related_type='', related_id=None):
        amount = int(amount)
        if amount <= 0:
            raise ValueError('冻结金币必须大于 0')

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = MerchantWallet.objects.select_for_update().get(pk=self.pk)
            if w.gold_available < amount:
                raise ValueError(f'可用金币不足:{w.gold_available}')

            w.gold_frozen += amount
            w.save(update_fields=['gold_frozen', 'updated_at'])
            self.gold_frozen = w.gold_frozen

            try:
                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.GOLD,
                    action=MerchantWalletTransaction.Action.FREEZE,
                    amount=Decimal('0'),
                    balance_after=Decimal(w.gold_balance),
                    freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or f'金币冻结 {amount}',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return MerchantWalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise

    def unfreeze_gold(self, amount, reason='', operator_id=None,
                      operator_role='system', idempotent_key=None,
                      related_type='', related_id=None):
        amount = int(amount)
        if amount <= 0:
            raise ValueError('解冻金币必须大于 0')

        if idempotent_key:
            existing = MerchantWalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
            if existing:
                return existing

        with transaction.atomic():
            w = MerchantWallet.objects.select_for_update().get(pk=self.pk)
            if w.gold_frozen < amount:
                raise ValueError(f'冻结金币不足:{w.gold_frozen}')

            w.gold_frozen -= amount
            w.save(update_fields=['gold_frozen', 'updated_at'])
            self.gold_frozen = w.gold_frozen

            try:
                return MerchantWalletTransaction.objects.create(
                    wallet=w, merchant_id=w.merchant_id,
                    currency=Currency.GOLD,
                    action=MerchantWalletTransaction.Action.UNFREEZE,
                    amount=Decimal('0'),
                    balance_after=Decimal(w.gold_balance),
                    freeze_delta=amount,
                    operator_id=operator_id, operator_role=operator_role,
                    related_type=related_type, related_id=related_id,
                    remark=reason or f'金币解冻 {amount}',
                    idempotent_key=idempotent_key,
                )
            except IntegrityError:
                if idempotent_key:
                    return MerchantWalletTransaction.objects.get(idempotent_key=idempotent_key)
                raise


# ════════════════════════════════════════════════════════════════
#                        商户钱包流水(🆕 加 currency 字段 + 金币 actions)
# ════════════════════════════════════════════════════════════════

class MerchantWalletTransaction(models.Model):
    class Status(models.TextChoices):
        NORMAL   = 'normal',   '正常'
        REVERSED = 'reversed', '已撤销'

    class Action(models.TextChoices):
        # ── 现金:收入 ──
        ORDER_INCOME   = 'order_income',   '订单入账(待结算)'
        SETTLE         = 'settle',         '待结算转可用'
        REFUND_REVOKE  = 'refund_revoke',  '退款撤回返还'
        ADJUSTMENT_ADD = 'adjustment_add', '人工调增'
        PENDING_IN     = 'pending_in',     '订单进入待结算'

        # ── 现金:支出 ──
        COMMISSION_DEDUCT = 'commission_deduct', '平台佣金扣除'
        REFUND_DEDUCT     = 'refund_deduct',     '退款扣回'
        WITHDRAW_SUCCESS  = 'withdraw_success',  '提现成功扣款'
        WITHDRAW_FEE      = 'withdraw_fee',      '提现手续费'
        ADJUSTMENT_SUB    = 'adjustment_sub',    '人工调减'
        PENDING_DEDUCT    = 'pending_deduct',    '退款扣减待结算'

        # ── 🆕 金币:收入 ──
        GOLD_GRANT      = 'gold_grant',      '金币发放'
        GOLD_REWARD     = 'gold_reward',     '金币奖励(任务/活动达成)'
        GOLD_PROMOTION  = 'gold_promotion',  '营销活动获得金币'
        GOLD_ADJUST_ADD = 'gold_adjust_add', '金币人工调增'

        # ── 🆕 金币:支出 ──
        GOLD_SPEND      = 'gold_spend',      '金币消费(购买推广位等)'
        GOLD_DEDUCT     = 'gold_deduct',     '金币扣除'
        GOLD_EXPIRED    = 'gold_expired',    '金币过期清零'
        GOLD_ADJUST_SUB = 'gold_adjust_sub', '金币人工调减'

        # ── 中性 ──
        FREEZE   = 'freeze',   '冻结'
        UNFREEZE = 'unfreeze', '解冻'
        REVERSE  = 'reverse',  '撤销反向流水'

    wallet = models.ForeignKey(
        MerchantWallet, on_delete=models.CASCADE,
        related_name='transactions'
    )
    merchant_id = models.PositiveIntegerField(db_index=True)

    # 🆕 币种 —— 区分现金 / 金币流水
    currency = models.CharField(
        max_length=10, choices=Currency.choices,
        default=Currency.CASH, db_index=True, verbose_name='币种'
    )

    action        = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    amount        = models.DecimalField(max_digits=16, decimal_places=2)
    balance_after = models.DecimalField(max_digits=16, decimal_places=2)
    pending_after = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    freeze_delta  = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.NORMAL, db_index=True)
    reversed_by_tx = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT, related_name='reverses',
    )

    operator_id   = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    operator_role = models.CharField(max_length=20, choices=MerchantOperatorRole.choices,
                                     default=MerchantOperatorRole.SYSTEM)
    operator_ip   = models.GenericIPAddressField(null=True, blank=True)

    related_order_no = models.CharField(max_length=64, blank=True, default='', db_index=True)
    related_type     = models.CharField(max_length=30, blank=True, default='')
    related_id       = models.PositiveIntegerField(null=True, blank=True)

    batch_no       = models.CharField(max_length=64, blank=True, default='', db_index=True)
    remark         = models.CharField(max_length=200, blank=True, default='')
    idempotent_key = models.CharField(max_length=64, unique=True, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'merchant_wallet_transactions'
        verbose_name = '商户钱包流水'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant_id', 'currency', '-created_at']),  # 🔧 加 currency 复合索引
            models.Index(fields=['wallet', 'currency', 'action', '-created_at']),
            models.Index(fields=['related_order_no']),
            models.Index(fields=['related_type', 'related_id']),
            models.Index(fields=['batch_no']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        sign = '+' if self.amount > 0 else ''
        cur = self.get_currency_display()
        return f"[{cur}|{self.get_action_display()}] {sign}{self.amount}"


# ════════════════════════════════════════════════════════════════
#                        提现申请(原样)
# ════════════════════════════════════════════════════════════════

class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING    = 'pending',    '待审核'
        CANCELLED  = 'cancelled',  '用户取消'
        APPROVED   = 'approved',   '审核通过'
        PROCESSING = 'processing', '打款中'
        SUCCESS    = 'success',    '已到账'
        REJECTED   = 'rejected',   '审核拒绝'
        FAILED     = 'failed',     '打款失败'

    class PaymentChannel(models.TextChoices):
        BANK   = 'bank',   '银行代付'
        ALIPAY = 'alipay', '支付宝代付'
        WECHAT = 'wechat', '微信代付'
        MANUAL = 'manual', '线下打款'

    class RiskLevel(models.TextChoices):
        LOW    = 'low',    '低'
        MEDIUM = 'medium', '中'
        HIGH   = 'high',   '高'

    wallet = models.ForeignKey(
        MerchantWallet, on_delete=models.CASCADE,
        related_name='withdrawal_requests'
    )
    merchant = models.ForeignKey(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='withdrawal_requests'
    )

    applicant_id   = models.PositiveIntegerField(null=True, blank=True, db_index=True, verbose_name='申请人ID')
    applicant_name = models.CharField(max_length=50, blank=True, default='', verbose_name='申请人姓名')

    withdraw_no   = models.CharField(max_length=64, unique=True, db_index=True)
    amount        = models.DecimalField(max_digits=14, decimal_places=2)
    fee           = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='平台手续费')
    channel_fee   = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='通道手续费')
    actual_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    balance_snapshot   = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    available_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    bank_name         = models.CharField(max_length=100, blank=True, default='')
    bank_account_name = models.CharField(max_length=50, blank=True, default='')
    bank_account_no   = models.CharField(max_length=30, blank=True, default='')
    alipay_account    = models.CharField(max_length=100, blank=True, default='')
    wechat_openid     = models.CharField(max_length=100, blank=True, default='')

    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    state_version = models.PositiveIntegerField(default=0, verbose_name='状态版本号')

    reviewed_by   = models.PositiveIntegerField(null=True, blank=True)
    reviewer_name = models.CharField(max_length=50, blank=True, default='')
    reviewed_at   = models.DateTimeField(null=True, blank=True)
    approved_at   = models.DateTimeField(null=True, blank=True)
    rejected_at   = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True, default='')

    payment_channel  = models.CharField(max_length=20, choices=PaymentChannel.choices,
                                        blank=True, default='')
    transfer_no      = models.CharField(max_length=128, blank=True, default='')
    transferred_at   = models.DateTimeField(null=True, blank=True)
    completed_at     = models.DateTimeField(null=True, blank=True)
    fail_reason      = models.CharField(max_length=200, blank=True, default='')
    channel_response = models.JSONField(null=True, blank=True)

    retry_count   = models.PositiveSmallIntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)

    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices,
                                  default=RiskLevel.LOW)
    risk_tags  = models.JSONField(null=True, blank=True)

    remark       = models.CharField(max_length=200, blank=True, default='')
    admin_remark = models.CharField(max_length=200, blank=True, default='')
    ip_address   = models.GenericIPAddressField(null=True, blank=True)
    batch_no     = models.CharField(max_length=64, blank=True, default='', db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_withdrawal_requests'
        verbose_name = '商户提现申请'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant', 'status', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['risk_level', 'status']),
            models.Index(fields=['batch_no']),
            models.Index(fields=['applicant_id', '-created_at']),
        ]

    def __str__(self):
        return f"{self.withdraw_no} | ¥{self.amount} | {self.get_status_display()}"

    def cancel(self, operator_id=None, reason=''):
        if self.status != self.Status.PENDING:
            raise ValueError(f'当前 {self.get_status_display()} 不允许取消')
        self.status = self.Status.CANCELLED
        self.state_version += 1
        # 🔧 拼接 remark 时截断,避免超过 max_length=200
        new_part = reason or '用户取消'
        merged = (self.remark + ' | ' if self.remark else '') + new_part
        self.remark = merged[:200]
        self.save(update_fields=['status', 'state_version', 'remark', 'updated_at'])

    def approve(self, reviewer_id, reviewer_name='', admin_remark=''):
        if self.status != self.Status.PENDING:
            raise ValueError(f'当前 {self.get_status_display()} 不允许审核')

        with transaction.atomic():
            now = timezone.now()
            self.status = self.Status.APPROVED
            self.state_version += 1
            self.reviewed_by = reviewer_id
            self.reviewer_name = reviewer_name
            self.reviewed_at = now
            self.approved_at = now
            if admin_remark:
                self.admin_remark = admin_remark
            self.save(update_fields=[
                'status', 'state_version', 'reviewed_by', 'reviewer_name',
                'reviewed_at', 'approved_at', 'admin_remark', 'updated_at',
            ])
            self.wallet.freeze(
                amount=self.amount,
                reason=f'提现冻结 {self.withdraw_no}',
                operator_id=reviewer_id,
                operator_role='admin',
                related_type='withdrawal', related_id=self.pk,
                idempotent_key=f'wd_freeze_{self.withdraw_no}',
            )

    def reject(self, reviewer_id, reason='', reviewer_name='', admin_remark=''):
        if self.status != self.Status.PENDING:
            raise ValueError(f'当前 {self.get_status_display()} 不允许拒绝')

        now = timezone.now()
        self.status = self.Status.REJECTED
        self.state_version += 1
        self.reviewed_by = reviewer_id
        self.reviewer_name = reviewer_name
        self.reviewed_at = now
        self.rejected_at = now
        self.reject_reason = reason
        if admin_remark:
            self.admin_remark = admin_remark
        self.save(update_fields=[
            'status', 'state_version', 'reviewed_by', 'reviewer_name',
            'reviewed_at', 'rejected_at', 'reject_reason',
            'admin_remark', 'updated_at',
        ])

    def mark_processing(self, payment_channel=''):
        if self.status != self.Status.APPROVED:
            raise ValueError(f'当前 {self.get_status_display()} 不允许发起打款')
        self.status = self.Status.PROCESSING
        self.state_version += 1
        if payment_channel:
            self.payment_channel = payment_channel
        self.save(update_fields=['status', 'state_version', 'payment_channel', 'updated_at'])

    def mark_success(self, transfer_no='', channel_response=None):
        if self.status != self.Status.PROCESSING:
            raise ValueError(f'当前 {self.get_status_display()} 不允许标记成功')

        now = timezone.now()
        A = MerchantWalletTransaction.Action

        with transaction.atomic():
            self.wallet.unfreeze(
                amount=self.amount,
                reason=f'提现完成解冻 {self.withdraw_no}',
                related_type='withdrawal', related_id=self.pk,
                idempotent_key=f'wd_unfreeze_{self.withdraw_no}',
            )
            self.wallet.change_balance(
                amount=-self.amount,
                action=A.WITHDRAW_SUCCESS,
                related_type='withdrawal', related_id=self.pk,
                remark=f'提现到账 {self.withdraw_no}',
                idempotent_key=f'wd_deduct_{self.withdraw_no}',
            )
            self.status = self.Status.SUCCESS
            self.state_version += 1
            self.transfer_no = transfer_no
            self.transferred_at = now
            self.completed_at = now
            if channel_response is not None:
                self.channel_response = channel_response
            self.save(update_fields=[
                'status', 'state_version', 'transfer_no', 'transferred_at',
                'completed_at', 'channel_response', 'updated_at',
            ])

    def mark_failed(self, reason='', channel_response=None):
        if self.status != self.Status.PROCESSING:
            raise ValueError(f'当前 {self.get_status_display()} 不允许标记失败')

        with transaction.atomic():
            self.wallet.unfreeze(
                amount=self.amount,
                reason=f'提现失败解冻 {self.withdraw_no}',
                related_type='withdrawal', related_id=self.pk,
                idempotent_key=f'wd_fail_unfreeze_{self.withdraw_no}_{self.retry_count}',
            )
            self.status = self.Status.FAILED
            self.state_version += 1
            self.fail_reason = reason
            if channel_response is not None:
                self.channel_response = channel_response
            self.save(update_fields=[
                'status', 'state_version', 'fail_reason',
                'channel_response', 'updated_at',
            ])

    def retry(self, operator_id=None):
        if self.status != self.Status.FAILED:
            raise ValueError(f'当前 {self.get_status_display()} 不允许重试')

        with transaction.atomic():
            self.status = self.Status.APPROVED
            self.state_version += 1
            self.retry_count += 1
            self.last_retry_at = timezone.now()
            self.fail_reason = ''
            self.save(update_fields=[
                'status', 'state_version', 'retry_count',
                'last_retry_at', 'fail_reason', 'updated_at',
            ])
            self.wallet.freeze(
                amount=self.amount,
                reason=f'提现重试冻结 {self.withdraw_no} #{self.retry_count}',
                operator_id=operator_id,
                operator_role='admin',
                related_type='withdrawal', related_id=self.pk,
                idempotent_key=f'wd_retry_freeze_{self.withdraw_no}_{self.retry_count}',
            )


# ════════════════════════════════════════════════════════════════
#                        结算配置(原样)
# ════════════════════════════════════════════════════════════════

class MerchantSettlementConfig(models.Model):
    class SettlementCycle(models.TextChoices):
        T1  = 'T+1',  'T+1(次日结算)'
        T7  = 'T+7',  'T+7(每周结算)'
        T15 = 'T+15', 'T+15(半月结算)'
        T30 = 'T+30', 'T+30(月结)'

    merchant = models.OneToOneField(
        'merchants.Merchant', on_delete=models.CASCADE,
        related_name='settlement_config'
    )

    settlement_cycle           = models.CharField(max_length=10, choices=SettlementCycle.choices,
                                                  default=SettlementCycle.T1)
    min_withdraw_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=100)
    max_withdraw_per_day       = models.DecimalField(max_digits=14, decimal_places=2, default=50000)
    max_withdraw_times_per_day = models.PositiveSmallIntegerField(default=3)
    withdraw_fee_rate          = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    withdraw_fee_fixed         = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    auto_withdraw              = models.BooleanField(default=False)
    auto_withdraw_threshold    = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_settlement_config'
        verbose_name = '商户结算配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"merchant={self.merchant_id} | {self.get_settlement_cycle_display()}"

    def calc_withdraw_fee(self, amount):
        amount = Decimal(str(amount))
        fee = amount * self.withdraw_fee_rate + self.withdraw_fee_fixed
        return fee.quantize(Decimal('0.01'))


class WalletRecharge(models.Model):
    """
    用户充值订单。
    流程:
      1. 用户发起充值 → 创建 WalletRecharge(status=pending)+ PaymentOrder
      2. 微信支付成功 → 钩子调 UserWallet.change_gold() 入面额金币
      3. 同钩子识别活动 → ActivityUserGrant + 入加送金币
    """
    class Status(models.TextChoices):
        PENDING = 'pending', '待支付'
        PAID    = 'paid',    '已到账'
        FAILED  = 'failed',  '失败'
        CLOSED  = 'closed',  '已关闭'

    recharge_no = models.CharField(max_length=32, unique=True, verbose_name='充值单号')
    user = models.ForeignKey(
        'user.User', on_delete=models.CASCADE,
        related_name='recharges', verbose_name='用户',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='充值金额(元)')

    # 面额金币:1元=1金币(平台规则,可在 SystemConfig 配置 coin_per_yuan)
    face_coins  = models.PositiveIntegerField(verbose_name='面额对应金币')
    # 活动加送:由钩子根据匹配的活动写入
    bonus_coins = models.PositiveIntegerField(default=0, verbose_name='活动加送金币')
    activity_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='触发的活动ID',
    )

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_recharge'
        verbose_name = '钱包充值'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.recharge_no} ¥{self.amount}'

    def save(self, *args, **kwargs):
        if not self.recharge_no:
            import time, uuid
            ts = int(time.time() * 1000)
            rand = uuid.uuid4().hex[:6].upper()
            self.recharge_no = f'RC{ts}{rand}'
        super().save(*args, **kwargs)