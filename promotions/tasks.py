# -*- coding: utf-8 -*-
# @Time    : 2026/5/20 16:26
# @Author  : Delock

"""
活动相关异步任务。
关键路径(发金币)走同步,这里只负责"可以晚一点"的事:
  - 周期巡检:到期下线、超预算暂停
  - 慢操作:订单完成解冻商家金币、退款撤销发放
"""

import logging
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    PaymentActivity, ActivityUserGrant, ActivityMerchantEarn,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 1) 巡检:到期活动自动下线
# ─────────────────────────────────────────────────────────────

@shared_task(name='promotions.expire_activities')
def expire_activities():
    n = PaymentActivity.objects.filter(
        status=PaymentActivity.Status.ACTIVE,
        end_time__lt=timezone.now(),
    ).update(status=PaymentActivity.Status.ENDED)
    if n:
        logger.info('expire_activities: %s 个活动已下线', n)
    return n


# ─────────────────────────────────────────────────────────────
# 2) 巡检:预算耗尽自动暂停
# ─────────────────────────────────────────────────────────────

@shared_task(name='promotions.auto_pause_over_budget')
def auto_pause_over_budget():
    n = (
        PaymentActivity.objects
        .filter(
            status=PaymentActivity.Status.ACTIVE,
            total_budget_coins__gt=0,
        )
        .filter(
            user_granted_coins__gte=
                F('total_budget_coins') - F('merchant_earned_coins'),
        )
        .update(status=PaymentActivity.Status.PAUSED)
    )
    if n:
        logger.info('auto_pause_over_budget: %s 个活动超预算被暂停', n)
    return n


# ─────────────────────────────────────────────────────────────
# 3) 订单完成 → 解冻商家活动金币
#    在 bill.ServiceOrder.complete_service() 或商品订单完成处调:
#       unfreeze_merchant_earns.delay(order_no)
# ─────────────────────────────────────────────────────────────

@shared_task(name='promotions.unfreeze_merchant_earns', bind=True,
             max_retries=3, default_retry_delay=30)
def unfreeze_merchant_earns(self, order_no):
    from wallet.models import MerchantWallet

    earns = ActivityMerchantEarn.objects.filter(
        order_no=order_no,
        frozen_status=ActivityMerchantEarn.FrozenStatus.FROZEN,
    )
    for e in earns:
        try:
            with transaction.atomic():
                e_locked = (
                    ActivityMerchantEarn.objects
                    .select_for_update()
                    .get(pk=e.pk)
                )
                if e_locked.frozen_status != ActivityMerchantEarn.FrozenStatus.FROZEN:
                    continue
                mw = MerchantWallet.objects.get(merchant_id=e_locked.merchant_id)
                mw.unfreeze_gold(
                    amount=e_locked.earned_coins,
                    reason=f'订单{order_no}完成,活动金币解冻',
                    related_type='activity_merchant_earn',
                    related_id=e_locked.id,
                    idempotent_key=f'act_merch_unfreeze_{e_locked.id}',
                )
                e_locked.frozen_status = ActivityMerchantEarn.FrozenStatus.UNFROZEN
                e_locked.unfrozen_at = timezone.now()
                e_locked.save(update_fields=['frozen_status', 'unfrozen_at'])
        except Exception as exc:
            logger.exception('解冻活动金币失败 earn_id=%s', e.id)
            raise self.retry(exc=exc)


# ─────────────────────────────────────────────────────────────
# 4) 退款撤销
#    在 payment.services.handle_refund_success() 里调:
#       revoke_on_refund.delay(payment_no=..., order_no=...)
# ─────────────────────────────────────────────────────────────

@shared_task(name='promotions.revoke_on_refund', bind=True,
             max_retries=3, default_retry_delay=30)
def revoke_on_refund(self, payment_no, order_no=''):
    from wallet.models import (
        UserWallet, MerchantWallet,
        WalletTransaction, MerchantWalletTransaction,
    )

    # ── ① 撤销用户领取 ──
    grants = ActivityUserGrant.objects.filter(
        payment_no=payment_no, is_revoked=False,
    )
    for g in grants:
        try:
            with transaction.atomic():
                gl = ActivityUserGrant.objects.select_for_update().get(pk=g.pk)
                if gl.is_revoked:
                    continue
                uw = UserWallet.objects.get(user_id=gl.user_id)
                uw.change_gold(
                    amount=-gl.reward_coins,
                    action=WalletTransaction.Action.GOLD_DEDUCT,
                    related_type='activity_user_grant',
                    related_id=gl.id,
                    remark=f'退款撤销活动金币',
                    idempotent_key=f'revoke_user_{gl.id}',
                    allow_negative=True,   # 已花完允许扣到负
                )
                gl.is_revoked = True
                gl.revoked_at = timezone.now()
                gl.save(update_fields=['is_revoked', 'revoked_at'])
                PaymentActivity.objects.filter(pk=gl.activity_id).update(
                    user_granted_coins=F('user_granted_coins') - gl.reward_coins,
                )
        except Exception as exc:
            logger.exception('撤销用户领取失败 grant_id=%s', g.id)
            raise self.retry(exc=exc)

    # ── ② 撤销商家入金 —— 优先扣冻结 ──
    if not order_no:
        return
    earns = ActivityMerchantEarn.objects.filter(
        order_no=order_no, is_revoked=False,
    )
    for e in earns:
        try:
            with transaction.atomic():
                el = ActivityMerchantEarn.objects.select_for_update().get(pk=e.pk)
                if el.is_revoked:
                    continue
                mw = MerchantWallet.objects.get(merchant_id=el.merchant_id)

                # 冻结的优先解冻,再扣金币
                if el.frozen_status == ActivityMerchantEarn.FrozenStatus.FROZEN:
                    mw.unfreeze_gold(
                        amount=el.earned_coins,
                        reason=f'订单{order_no}退款,先解冻再扣',
                        related_type='activity_merchant_earn',
                        related_id=el.id,
                        idempotent_key=f'refund_unfreeze_{el.id}',
                    )
                mw.change_gold(
                    amount=-el.earned_coins,
                    action=MerchantWalletTransaction.Action.GOLD_DEDUCT,
                    related_type='activity_merchant_earn',
                    related_id=el.id,
                    related_order_no=order_no,
                    remark=f'订单{order_no}退款撤销活动金币',
                    idempotent_key=f'refund_deduct_merch_{el.id}',
                    allow_negative=True,
                )
                el.frozen_status = ActivityMerchantEarn.FrozenStatus.REVOKED
                el.is_revoked = True
                el.revoked_at = timezone.now()
                el.save(update_fields=['frozen_status', 'is_revoked', 'revoked_at'])
                PaymentActivity.objects.filter(pk=el.activity_id).update(
                    merchant_earned_coins=F('merchant_earned_coins') - el.earned_coins,
                )
        except Exception as exc:
            logger.exception('撤销商家入金失败 earn_id=%s', e.id)
            raise self.retry(exc=exc)