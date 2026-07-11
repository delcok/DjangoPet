# -*- coding: utf-8 -*-
# pay/admin.py

import json

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import PaymentOrder, PaymentRefund


# ──────────────────────────────────────────────
# 工具：把 JSON / 长文本渲染成可读的 <pre> 块
# ──────────────────────────────────────────────
def _pretty(value):
    if value in (None, '', {}):
        return '—'
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        # callback_raw 有时是 str(dict)，尝试美化，失败就原样显示
        text = str(value)
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return format_html(
        '<pre style="white-space:pre-wrap;word-break:break-all;'
        'max-width:760px;margin:0;font-size:12px;line-height:1.5;">{}</pre>',
        text,
    )


# ══════════════════════════════════════════════
# 支付单
# ══════════════════════════════════════════════
@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        'payment_no',
        'colored_status',      # 带颜色的状态，一眼看成没成
        'channel',
        'order_type',
        'amount',
        'user_id',
        'order_no',
        'paid_at',
        'created_at',
    )
    list_display_links = ('payment_no',)
    list_filter = ('status', 'channel', 'order_type', 'created_at')
    search_fields = (
        'payment_no', 'out_trade_no', 'channel_trade_no',
        'order_no', 'user_id',
    )
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 30

    readonly_fields = (
        'payment_no', 'out_trade_no', 'channel_trade_no',
        'order_type', 'order_no', 'user_id', 'merchant_id',
        'channel', 'amount', 'amount_in_cents', 'colored_status',
        'pay_platform', 'pay_ip',
        'paid_at', 'closed_at', 'expire_at', 'created_at', 'updated_at',
        'pretty_pay_params', 'pretty_callback_raw',
        'related_recharge_info',   # ★ 充值单联动，判断金币到没到账
    )

    fieldsets = (
        ('支付结果', {
            'fields': (
                'colored_status', 'channel', 'order_type',
                'amount', 'amount_in_cents', 'paid_at',
            )
        }),
        ('标识', {
            'fields': (
                'payment_no', 'out_trade_no', 'channel_trade_no',
                'order_no', 'user_id', 'merchant_id',
            )
        }),
        ('★ 关联充值单（金币是否到账）', {
            'fields': ('related_recharge_info',),
            'description': '仅充值订单(order_type=recharge)有值，用于判断金币是否发放成功',
        }),
        ('渠道交互数据（排查用）', {
            'fields': ('pretty_pay_params', 'pretty_callback_raw'),
            'classes': ('collapse',),
        }),
        ('环境 / 时间', {
            'fields': (
                'pay_platform', 'pay_ip',
                'expire_at', 'closed_at', 'created_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='支付状态', ordering='status')
    def colored_status(self, obj):
        color = {
            'paid': '#1a7f37',      # 绿：成功
            'pending': '#9a6700',   # 黄：待支付
            'failed': '#cf222e',    # 红：失败
            'closed': '#57606a',    # 灰：关闭
        }.get(obj.status, '#57606a')
        return format_html(
            '<b style="color:{};">{}</b>',
            color, obj.get_status_display(),
        )

    @admin.display(description='返给前端的支付参数')
    def pretty_pay_params(self, obj):
        return _pretty(obj.pay_params)

    @admin.display(description='回调原始数据')
    def pretty_callback_raw(self, obj):
        return _pretty(obj.callback_raw)

    @admin.display(description='关联充值单 / 金币到账情况')
    def related_recharge_info(self, obj):
        if obj.order_type != 'recharge':
            return '非充值订单'
        try:
            from wallet.models import WalletRecharge
            r = WalletRecharge.objects.filter(recharge_no=obj.order_no).first()
        except Exception as e:
            return format_html('<span style="color:#cf222e;">查询充值单异常: {}</span>', str(e))

        if not r:
            return format_html(
                '<span style="color:#cf222e;">未找到充值单 recharge_no={}</span>',
                obj.order_no,
            )

        paid_ok = getattr(r, 'status', '') in ('paid', 'PAID', getattr(getattr(r, 'Status', None), 'PAID', 'paid'))
        status_color = '#1a7f37' if paid_ok else '#9a6700'
        rows = [
            ('充值单号', getattr(r, 'recharge_no', '—')),
            ('充值单状态', format_html('<b style="color:{};">{}</b>', status_color, getattr(r, 'status', '—'))),
            ('充值金额(元)', getattr(r, 'amount', '—')),
            ('面额金币', getattr(r, 'face_coins', '—')),
            ('加送金币', getattr(r, 'bonus_coins', '—')),
            ('关联活动ID', getattr(r, 'activity_id', None) or '无'),
            ('到账时间', getattr(r, 'paid_at', None) or '—'),
        ]
        html = '<table style="font-size:12px;line-height:1.7;">'
        for k, v in rows:
            html += format_html('<tr><td style="padding-right:16px;color:#57606a;">{}</td><td>{}</td></tr>', k, v)
        html += '</table>'
        return mark_safe(html)


# ══════════════════════════════════════════════
# 退款单
# ══════════════════════════════════════════════
@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = (
        'refund_no',
        'colored_status',
        'refund_amount',
        'reason',
        'order_no',
        'user_id',
        'operator_type',
        'refunded_at',
        'created_at',
    )
    list_display_links = ('refund_no',)
    list_filter = ('status', 'reason', 'operator_type', 'created_at')
    search_fields = (
        'refund_no', 'channel_refund_no', 'order_no', 'user_id',
    )
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 30

    readonly_fields = (
        'refund_no', 'channel_refund_no', 'payment_order',
        'order_no', 'user_id', 'refund_amount', 'refund_amount_in_cents',
        'reason', 'reason_detail', 'colored_status',
        'operator_type', 'operator_id',
        'refunded_at', 'created_at', 'updated_at',
        'pretty_callback_raw',
    )

    fieldsets = (
        ('退款结果', {
            'fields': (
                'colored_status', 'refund_amount', 'refund_amount_in_cents',
                'reason', 'reason_detail', 'refunded_at',
            )
        }),
        ('标识 / 关联', {
            'fields': (
                'refund_no', 'channel_refund_no',
                'payment_order', 'order_no', 'user_id',
            )
        }),
        ('操作人', {
            'fields': ('operator_type', 'operator_id'),
        }),
        ('回调数据（排查用）', {
            'fields': ('pretty_callback_raw',),
            'classes': ('collapse',),
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='退款状态', ordering='status')
    def colored_status(self, obj):
        color = {
            'success': '#1a7f37',
            'pending': '#9a6700',
            'failed': '#cf222e',
        }.get(obj.status, '#57606a')
        return format_html('<b style="color:{};">{}</b>', color, obj.get_status_display())

    @admin.display(description='退款回调原始数据')
    def pretty_callback_raw(self, obj):
        return _pretty(obj.callback_raw)