# -*- coding: utf-8 -*-
# @Time    : 2026/6/24 15:04
# @Author  : Delock


import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum, Q, F
from django.db.models.functions import TruncDate
from django.utils import timezone

logger = logging.getLogger(__name__)


def _f(v):
    """Decimal / None → float, 方便 JSON 序列化"""
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return v


class DashboardStats:
    """汇总各模块统计指标; collect() 产出可直接落 Redis 的 dict。"""

    def __init__(self, now=None):
        self.now = now or timezone.now()
        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)
        self.week_start = self.today - timedelta(days=self.today.weekday())  # 本周一
        self.month_start = self.today.replace(day=1)

    # ───────────────────────── 入口 ─────────────────────────
    def collect(self) -> dict:
        return {
            'generated_at': self.now.isoformat(),
            'date': self.today.isoformat(),
            'users': self._safe(self.user_stats),
            'merchants': self._safe(self.merchant_stats),
            'catalog': self._safe(self.catalog_stats),
            'orders': self._safe(self.order_stats),
            'revenue': self._safe(self.revenue_stats),
            'recharge': self._safe(self.recharge_stats),
            'wallet': self._safe(self.wallet_stats),
            'marketing': self._safe(self.marketing_stats),
            'todos': self._safe(self.pending_action_stats),
            'trend_30d': self._safe(lambda: self.trend_stats(30)),
        }

    def _safe(self, fn):
        """单板块出错不拖垮整个面板。"""
        try:
            return fn()
        except Exception as e:
            logger.exception('dashboard 板块计算失败: %s', getattr(fn, '__name__', fn))
            return {'error': str(e)}

    # ───────────────────────── 用户 ─────────────────────────
    def user_stats(self) -> dict:
        from user.models import User
        qs = User.objects.all()
        active_since = self.today - timedelta(days=6)  # 近 7 天
        by_channel = list(
            qs.values('register_channel')
              .annotate(count=Count('id'))
              .order_by('-count')
        )
        return {
            'total': qs.count(),
            'today_new': qs.filter(created_at__date=self.today).count(),
            'yesterday_new': qs.filter(created_at__date=self.yesterday).count(),
            'week_new': qs.filter(created_at__date__gte=self.week_start).count(),
            'month_new': qs.filter(created_at__date__gte=self.month_start).count(),
            'vip': qs.filter(is_vip=True).count(),
            'verified': qs.filter(is_verified=True).count(),
            'active_7d': qs.filter(last_active_at__date__gte=active_since).count(),
            'banned': qs.filter(is_banned=True).count(),
            'by_channel': by_channel,
        }

    # ───────────────────────── 商家 ─────────────────────────
    def merchant_stats(self) -> dict:
        from merchants.models import Merchant, MerchantCategory
        qs = Merchant.objects.all()
        by_status = {
            row['status']: row['count']
            for row in qs.values('status').annotate(count=Count('id'))
        }
        top_categories = list(
            MerchantCategory.objects
            .annotate(merchant_count=Count('merchants'))
            .values('id', 'name', 'merchant_count')
            .order_by('-merchant_count')[:10]
        )
        return {
            'total': qs.count(),
            'today_new': qs.filter(created_at__date=self.today).count(),
            'month_new': qs.filter(created_at__date__gte=self.month_start).count(),
            'active': by_status.get(Merchant.Status.ACTIVE, 0),
            'pending': by_status.get(Merchant.Status.PENDING, 0),
            'suspended': by_status.get(Merchant.Status.SUSPENDED, 0),
            'closed': by_status.get(Merchant.Status.CLOSED, 0),
            'open_now': qs.filter(is_open=True, status=Merchant.Status.ACTIVE).count(),
            'by_status': by_status,
            'top_categories': top_categories,
        }

    # ───────────────────────── 商品 / 服务 目录 ─────────────────────────
    def catalog_stats(self) -> dict:
        from product.models import Goods, GoodsSku
        from services.models import Service

        goods = Goods.objects.all()
        goods_by_status = {
            row['status']: row['count']
            for row in goods.values('status').annotate(count=Count('id'))
        }
        # 库存预警: 启用中且 0 < 库存 <= 预警值; 售罄: 库存=0
        low_stock = GoodsSku.objects.filter(
            is_active=True, stock__gt=0, stock__lte=F('stock_warning')
        ).count()
        out_of_stock = GoodsSku.objects.filter(is_active=True, stock=0).count()

        svc = Service.objects.all()
        svc_by_status = {
            row['status']: row['count']
            for row in svc.values('status').annotate(count=Count('id'))
        }
        svc_by_type = {
            row['service_type']: row['count']
            for row in svc.values('service_type').annotate(count=Count('id'))
        }

        return {
            'goods': {
                'total': goods.count(),
                'on_sale': goods_by_status.get('on_sale', 0),
                'off_sale': goods_by_status.get('off_sale', 0),
                'sold_out': goods_by_status.get('sold_out', 0),
                'draft': goods_by_status.get('draft', 0),
                'low_stock_skus': low_stock,
                'out_of_stock_skus': out_of_stock,
                'by_status': goods_by_status,
            },
            'service': {
                'total': svc.count(),
                'active': svc_by_status.get('active', 0),
                'inactive': svc_by_status.get('inactive', 0),
                'draft': svc_by_status.get('draft', 0),
                'by_status': svc_by_status,
                'by_type': svc_by_type,
            },
        }

    # ───────────────────────── 订单 ─────────────────────────
    def order_stats(self) -> dict:
        from bill.models import ProductOrder, ServiceOrder

        def base(model):
            qs = model.objects.all()
            by_status = {
                row['status']: row['count']
                for row in qs.values('status').annotate(count=Count('id'))
            }
            return {
                'total': qs.count(),
                'today': qs.filter(created_at__date=self.today).count(),
                'yesterday': qs.filter(created_at__date=self.yesterday).count(),
                'week': qs.filter(created_at__date__gte=self.week_start).count(),
                'month': qs.filter(created_at__date__gte=self.month_start).count(),
                'by_status': by_status,
            }

        product = base(ProductOrder)
        service = base(ServiceOrder)
        # 服务订单额外按 service_type 拆分(walk_in / appointment / on_demand / scheduled)
        service['by_type'] = {
            row['service_type']: row['count']
            for row in ServiceOrder.objects.values('service_type').annotate(count=Count('id'))
        }

        return {
            'product': product,
            'service': service,
            'summary': {
                'total': product['total'] + service['total'],
                'today': product['today'] + service['today'],
                'week': product['week'] + service['week'],
                'month': product['month'] + service['month'],
            },
        }

    # ───────────────────────── 营收 / GMV ─────────────────────────
    def revenue_stats(self) -> dict:
        from bill.models import ProductOrder, ServiceOrder

        def rev(model):
            paid = model.objects.filter(paid_at__isnull=False)
            refunded = model.objects.filter(status='refunded')
            gmv_total = _f(paid.aggregate(s=Sum('pay_amount'))['s'])
            paid_total = paid.count()
            return {
                'gmv_total': gmv_total,
                'gmv_today': _f(paid.filter(paid_at__date=self.today)
                                    .aggregate(s=Sum('pay_amount'))['s']),
                'gmv_yesterday': _f(paid.filter(paid_at__date=self.yesterday)
                                        .aggregate(s=Sum('pay_amount'))['s']),
                'gmv_month': _f(paid.filter(paid_at__date__gte=self.month_start)
                                    .aggregate(s=Sum('pay_amount'))['s']),
                'paid_orders_total': paid_total,
                'paid_orders_today': paid.filter(paid_at__date=self.today).count(),
                'aov': round(gmv_total / paid_total, 2) if paid_total else 0.0,  # 客单价
                'refunded_orders': refunded.count(),
                # 注: 用整笔 pay_amount 估算, 不含部分退款(订单表无单独退款额字段)
                'refunded_amount': _f(refunded.aggregate(s=Sum('pay_amount'))['s']),
            }

        p = rev(ProductOrder)
        s = rev(ServiceOrder)
        total_gmv = p['gmv_total'] + s['gmv_total']
        total_paid = p['paid_orders_total'] + s['paid_orders_total']
        return {
            'product': p,
            'service': s,
            'summary': {
                'gmv_total': total_gmv,
                'gmv_today': p['gmv_today'] + s['gmv_today'],
                'gmv_yesterday': p['gmv_yesterday'] + s['gmv_yesterday'],
                'gmv_month': p['gmv_month'] + s['gmv_month'],
                'paid_orders_total': total_paid,
                'aov': round(total_gmv / total_paid, 2) if total_paid else 0.0,
                'refunded_amount': p['refunded_amount'] + s['refunded_amount'],
            },
        }

    # ───────────────────────── 充值(金币) ─────────────────────────
    def recharge_stats(self) -> dict:
        from wallet.models import WalletRecharge
        paid = WalletRecharge.objects.filter(status='paid')
        return {
            'paid_amount_total': _f(paid.aggregate(s=Sum('amount'))['s']),
            'paid_amount_today': _f(paid.filter(paid_at__date=self.today)
                                        .aggregate(s=Sum('amount'))['s']),
            'paid_amount_month': _f(paid.filter(paid_at__date__gte=self.month_start)
                                        .aggregate(s=Sum('amount'))['s']),
            'paid_count_today': paid.filter(paid_at__date=self.today).count(),
            'bonus_gold_total': int(paid.aggregate(s=Sum('bonus_coins'))['s'] or 0),
        }

    # ───────────────────────── 钱包 / 提现 ─────────────────────────
    def wallet_stats(self) -> dict:
        from wallet.models import MerchantWallet, WithdrawalRequest, UserWallet

        mw = MerchantWallet.objects.aggregate(
            balance=Sum('balance'),
            pending=Sum('pending_settlement'),
            frozen=Sum('frozen_amount'),
            gold=Sum('gold_balance'),
        )
        wd = WithdrawalRequest.objects.all()
        wd_pending = wd.filter(status=WithdrawalRequest.Status.PENDING)
        uw = UserWallet.objects.aggregate(
            points=Sum('points_balance'),
            gold=Sum('gold_balance'),
        )
        return {
            'merchant': {
                'balance_total': _f(mw['balance']),
                'pending_settlement_total': _f(mw['pending']),
                'frozen_total': _f(mw['frozen']),
                'gold_total': int(mw['gold'] or 0),
            },
            'withdrawal': {
                'pending_count': wd_pending.count(),
                'pending_amount': _f(wd_pending.aggregate(s=Sum('amount'))['s']),
                'today_count': wd.filter(created_at__date=self.today).count(),
            },
            'user': {
                'points_total': int(uw['points'] or 0),
                'gold_total': int(uw['gold'] or 0),
            },
        }

    # ───────────────────────── 营销 / 优惠券 ─────────────────────────
    def marketing_stats(self) -> dict:
        from campaigns.models import Campaign, UserCoupon

        coupon_by_status = {
            row['status']: row['count']
            for row in UserCoupon.objects.values('status').annotate(count=Count('id'))
        }
        campaigns = Campaign.objects.all()
        return {
            'campaign': {
                'total': campaigns.count(),
                'active': campaigns.filter(status='active').count(),
                'claimed_total': campaigns.aggregate(s=Sum('claimed_count'))['s'] or 0,
            },
            'coupon': {
                'total': sum(coupon_by_status.values()),
                'unused': coupon_by_status.get('unused', 0),
                'used': coupon_by_status.get('used', 0),
                'expired': coupon_by_status.get('expired', 0),
                'by_status': coupon_by_status,
            },
        }

    # ───────────────────────── 待处理事项(管理员待办) ─────────────────────────
    def pending_action_stats(self) -> dict:
        from merchants.models import Merchant
        from user.models import UserProfileAudit
        from bill.models import ProductOrder, ServiceOrder
        from wallet.models import WithdrawalRequest

        wd_pending = WithdrawalRequest.objects.filter(
            status=WithdrawalRequest.Status.PENDING
        )
        return {
            'merchant_pending_review': Merchant.objects.filter(
                status=Merchant.Status.PENDING).count(),
            'withdrawal_pending': wd_pending.count(),
            'withdrawal_pending_amount': _f(wd_pending.aggregate(s=Sum('amount'))['s']),
            'profile_audit_pending': UserProfileAudit.objects.filter(
                status='pending').count(),
            'product_pending_shipment': ProductOrder.objects.filter(
                status='pending_shipment').count(),
            'service_pending_assignment': ServiceOrder.objects.filter(
                status__in=['pending_assignment', 'pending_accept']).count(),
            'order_refunding': (
                ProductOrder.objects.filter(status='refunding').count()
                + ServiceOrder.objects.filter(status='refunding').count()
            ),
        }

    # ───────────────────────── 趋势 (近 N 天) ─────────────────────────
    def trend_stats(self, days=30) -> list:
        """按「下单日期」聚合每日订单数与 GMV(GMV 只累计已支付订单的 pay_amount)。"""
        from bill.models import ProductOrder, ServiceOrder
        start = self.today - timedelta(days=days - 1)

        def series(model):
            rows = (
                model.objects
                .filter(created_at__date__gte=start)
                .annotate(d=TruncDate('created_at'))
                .values('d')
                .annotate(
                    cnt=Count('id'),
                    gmv=Sum('pay_amount', filter=Q(paid_at__isnull=False)),
                )
            )
            return {r['d']: r for r in rows}

        p, s = series(ProductOrder), series(ServiceOrder)
        out = []
        for i in range(days):
            d = start + timedelta(days=i)
            pr, sr = p.get(d, {}), s.get(d, {})
            out.append({
                'date': d.isoformat(),
                'product_orders': pr.get('cnt', 0),
                'service_orders': sr.get('cnt', 0),
                'orders': pr.get('cnt', 0) + sr.get('cnt', 0),
                'gmv': _f(pr.get('gmv')) + _f(sr.get('gmv')),
            })
        return out


# ════════════════════════════════════════════════════════════════
# 写 Redis 的辅助(Celery 任务 / 命令行 / 接口回填 共用)
# ════════════════════════════════════════════════════════════════

# 比 24h 略长: 万一某天没刷新, 旧数据仍可读到(但最终会过期)
DASHBOARD_TTL = 60 * 60 * 26


def refresh_dashboard_cache() -> dict:
    """聚合 + 写 Redis, 返回聚合结果。"""
    import json
    from utils.cache import get_redis_connection, CacheKey

    data = DashboardStats().collect()
    conn = get_redis_connection()
    conn.setex(
        CacheKey.DASHBOARD_OVERVIEW,
        DASHBOARD_TTL,
        json.dumps(data, ensure_ascii=False, default=str),
    )
    return data