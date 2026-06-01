# -*- coding: utf-8 -*-
# promotions/admin.py

import logging

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    PaymentActivity,
    MerchantActivityEnrollment,
    ActivityUserGrant,
    ActivityMerchantEarn,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 1. 支付活动
# ══════════════════════════════════════════════════════════════

@admin.register(PaymentActivity)
class PaymentActivityAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'name',
        'activity_type_badge',
        'status_badge',
        'reward_summary',
        'enrollment_summary',
        'period_summary',
        'usage_progress',
        'created_at',
    ]
    list_filter = [
        'activity_type',
        'status',
        'enrollment_mode',
        'enrollment_audit',
        'user_reward_enabled',
        'user_reward_type',
        'merchant_reward_enabled',
        'merchant_reward_type',
    ]
    search_fields = ['name', 'description']
    list_per_page = 30
    ordering = ['-created_at']
    readonly_fields = [
        'user_granted_count', 'user_granted_coins',
        'merchant_earned_count', 'merchant_earned_coins',
        'created_at', 'updated_at',
        'is_runnable_now',
        'budget_used_display',
    ]
    actions = ['action_publish', 'action_pause', 'action_resume', 'action_end']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'activity_type', 'status', 'is_runnable_now'),
        }),
        ('用户金币奖励', {
            'fields': (
                'user_reward_enabled',
                'user_reward_type',
                'user_reward_value',
                'user_reward_tiers',
            ),
            'description': (
                'fixed=固定金币;percent=订单金额百分比(0-100);tiered=阶梯。<br>'
                '阶梯格式:[{"threshold": 100, "reward_coins": 50}, ...]'
            ),
        }),
        ('商家金币奖励', {
            'fields': (
                'merchant_reward_enabled',
                'merchant_reward_type',
                'merchant_reward_value',
                'merchant_reward_tiers',
            ),
            'description': (
                'fixed=每单固定;percent=订单金额百分比;tiered=阶梯。<br>'
                '注:充值类活动不支持商家奖励。'
            ),
        }),
        ('时间窗口', {
            'fields': ('start_time', 'end_time'),
        }),
        ('适用范围', {
            'fields': ('apply_order_types',),
            'description': '可选值:["product", "service"];空数组=全部生效',
        }),
        ('参与规则', {
            'fields': (
                'enrollment_mode',
                'enrollment_audit',
                'per_user_limit',
                'total_budget_coins',
            ),
        }),
        ('统计(只读)', {
            'fields': (
                'user_granted_count', 'user_granted_coins',
                'merchant_earned_count', 'merchant_earned_coins',
                'budget_used_display',
            ),
            'classes': ('collapse',),
        }),
        ('时间(只读)', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ─── 列表展示 ───
    @admin.display(description='类型', ordering='activity_type')
    def activity_type_badge(self, obj):
        colors = {
            'order_spend': '#52c41a',
            'recharge':    '#fa8c16',
        }
        emojis = {
            'order_spend': '🎁',
            'recharge':    '💰',
        }
        c = colors.get(obj.activity_type, '#999')
        e = emojis.get(obj.activity_type, '')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:12px;">{} {}</span>',
            c, e, obj.get_activity_type_display(),
        )

    @admin.display(description='状态', ordering='status')
    def status_badge(self, obj):
        styles = {
            'draft':  ('草稿',   '#8c8c8c'),
            'active': ('进行中', '#52c41a'),
            'paused': ('已暂停', '#faad14'),
            'ended':  ('已结束', '#f5222d'),
        }
        text, color = styles.get(obj.status, (obj.status, '#999'))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 12px;'
            'border-radius:10px;font-size:12px;font-weight:600;">{}</span>',
            color, text,
        )

    @admin.display(description='奖励规则')
    def reward_summary(self, obj):
        parts = []

        # 用户奖励
        if obj.user_reward_enabled:
            t = obj.user_reward_type
            if t == PaymentActivity.RewardType.FIXED:
                parts.append(f'👤 每单送 {int(obj.user_reward_value)}🪙')
            elif t == PaymentActivity.RewardType.PERCENT:
                parts.append(f'👤 订单 {obj.user_reward_value}%')
            elif t == PaymentActivity.RewardType.TIERED:
                tiers = obj.user_reward_tiers or []
                if len(tiers) == 1:
                    one = tiers[0]
                    parts.append(
                        f"👤 满{one.get('threshold')}送{one.get('reward_coins')}🪙"
                    )
                elif len(tiers) > 1:
                    parts.append(f'👤 {len(tiers)} 档阶梯')

        # 商家奖励
        if obj.merchant_reward_enabled:
            t = obj.merchant_reward_type
            if t == PaymentActivity.RewardType.FIXED:
                parts.append(f'🏪 每单送 {int(obj.merchant_reward_value)}🪙')
            elif t == PaymentActivity.RewardType.PERCENT:
                parts.append(f'🏪 订单 {obj.merchant_reward_value}%')
            elif t == PaymentActivity.RewardType.TIERED:
                parts.append(f'🏪 阶梯 {len(obj.merchant_reward_tiers or [])} 档')

        return mark_safe('<br>'.join(parts)) if parts else '—'

    @admin.display(description='参与方式')
    def enrollment_summary(self, obj):
        mode_text = obj.get_enrollment_mode_display()
        if obj.enrollment_mode == PaymentActivity.EnrollmentMode.OPT_IN:
            audit_text = '需审批' if obj.enrollment_audit else '免审批'
            audit_color = '#fa8c16' if obj.enrollment_audit else '#52c41a'
            return format_html(
                '{} <span style="color:{};font-size:11px;">[{}]</span>',
                mode_text, audit_color, audit_text,
            )
        return mode_text

    @admin.display(description='活动期')
    def period_summary(self, obj):
        s = obj.start_time.strftime('%m-%d') if obj.start_time else '即时'
        e = obj.end_time.strftime('%m-%d') if obj.end_time else '永久'
        in_period = obj.is_in_period()
        color = '#52c41a' if in_period else '#bfbfbf'
        return format_html(
            '<span style="color:{};">{} ~ {}</span>',
            color, s, e,
        )

    @admin.display(description='预算/已用')
    def usage_progress(self, obj):
        used_user = obj.user_granted_coins or 0
        used_merchant = obj.merchant_earned_coins or 0
        total_used = used_user + used_merchant
        budget = obj.total_budget_coins or 0

        if budget > 0:
            pct = min(100, int(total_used * 100 / budget))
            color = '#52c41a' if pct < 70 else '#faad14' if pct < 95 else '#f5222d'
            return format_html(
                '<div style="width:120px;background:#f0f0f0;border-radius:4px;'
                'overflow:hidden;height:18px;position:relative;">'
                '<div style="width:{}%;background:{};height:100%;"></div>'
                '<span style="position:absolute;top:0;left:50%;transform:translateX(-50%);'
                'font-size:11px;line-height:18px;color:#000;">{}/{}</span>'
                '</div>',
                pct, color, total_used, budget,
            )
        return format_html(
            '<span style="color:#8c8c8c;">已发 {}🪙 / 不限</span>',
            total_used,
        )

    @admin.display(description='当前是否生效', boolean=True)
    def is_runnable_now(self, obj):
        return obj.is_runnable()

    @admin.display(description='预算使用详情')
    def budget_used_display(self, obj):
        used_user = obj.user_granted_coins or 0
        used_merchant = obj.merchant_earned_coins or 0
        total_used = used_user + used_merchant
        budget = obj.total_budget_coins or 0
        if budget <= 0:
            return f'已发 {total_used}🪙 (无预算上限)'
        pct = round(total_used * 100 / budget, 1) if budget else 0
        return (
            f'用户已发 {used_user}🪙 + 商家已发 {used_merchant}🪙 '
            f'= {total_used}🪙 / {budget}🪙 ({pct}%)'
        )

    # ─── 批量操作 ───
    @admin.action(description='✅ 上线选中活动(草稿/暂停 → 进行中)')
    def action_publish(self, request, queryset):
        n = queryset.filter(
            status__in=[PaymentActivity.Status.DRAFT, PaymentActivity.Status.PAUSED],
        ).update(status=PaymentActivity.Status.ACTIVE)
        self.message_user(request, f'已上线 {n} 个活动', messages.SUCCESS)

    @admin.action(description='⏸ 暂停选中活动')
    def action_pause(self, request, queryset):
        n = queryset.filter(
            status=PaymentActivity.Status.ACTIVE,
        ).update(status=PaymentActivity.Status.PAUSED)
        self.message_user(request, f'已暂停 {n} 个活动', messages.WARNING)

    @admin.action(description='▶ 恢复选中活动(暂停 → 进行中)')
    def action_resume(self, request, queryset):
        n = queryset.filter(
            status=PaymentActivity.Status.PAUSED,
        ).update(status=PaymentActivity.Status.ACTIVE)
        self.message_user(request, f'已恢复 {n} 个活动', messages.SUCCESS)

    @admin.action(description='🛑 结束选中活动(不可逆)')
    def action_end(self, request, queryset):
        n = queryset.exclude(
            status=PaymentActivity.Status.ENDED,
        ).update(status=PaymentActivity.Status.ENDED)
        self.message_user(request, f'已结束 {n} 个活动', messages.ERROR)


# ══════════════════════════════════════════════════════════════
# 2. 商家报名记录
# ══════════════════════════════════════════════════════════════

@admin.register(MerchantActivityEnrollment)
class MerchantActivityEnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'merchant_link',
        'activity_link',
        'status_badge',
        'apply_remark_short',
        'audit_remark_short',
        'earned_summary',
        'audited_at',
        'created_at',
    ]
    list_filter = ['status', 'activity__activity_type']
    search_fields = ['merchant__name', 'activity__name', 'apply_remark', 'audit_remark']
    list_per_page = 30
    ordering = ['-created_at']
    readonly_fields = [
        'activity', 'merchant',
        'user_granted_count', 'user_granted_coins',
        'merchant_earned_coins',
        'audited_by_id', 'audited_at',
        'created_at', 'updated_at',
    ]
    actions = ['action_approve', 'action_reject']
    autocomplete_fields = []  # 如果你的 MerchantAdmin 有 search_fields,可以加 ['merchant']

    fieldsets = (
        ('关联', {
            'fields': ('activity', 'merchant'),
        }),
        ('状态', {
            'fields': ('status', 'apply_remark', 'audit_remark'),
        }),
        ('审核(只读)', {
            'fields': ('audited_by_id', 'audited_at'),
        }),
        ('统计(只读)', {
            'fields': (
                'user_granted_count', 'user_granted_coins', 'merchant_earned_coins',
            ),
        }),
        ('时间(只读)', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('activity', 'merchant')

    @admin.display(description='商家')
    def merchant_link(self, obj):
        if not obj.merchant_id:
            return '—'
        name = obj.merchant.name if obj.merchant else f'#{obj.merchant_id}'
        try:
            url = reverse('admin:merchants_merchant_change', args=[obj.merchant_id])
            return format_html('<a href="{}" target="_blank">{}</a>', url, name)
        except Exception:
            return name

    @admin.display(description='活动')
    def activity_link(self, obj):
        if not obj.activity_id:
            return '—'
        name = obj.activity.name if obj.activity else f'#{obj.activity_id}'
        url = reverse('admin:promotions_paymentactivity_change', args=[obj.activity_id])
        return format_html('<a href="{}" target="_blank">{}</a>', url, name)

    @admin.display(description='状态', ordering='status')
    def status_badge(self, obj):
        styles = {
            'pending':  ('待审批', '#faad14'),
            'active':   ('已加入', '#52c41a'),
            'rejected': ('已拒绝', '#f5222d'),
            'quit':     ('已退出', '#8c8c8c'),
        }
        text, color = styles.get(obj.status, (obj.status, '#999'))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 12px;'
            'border-radius:10px;font-size:12px;">{}</span>',
            color, text,
        )

    @admin.display(description='申请说明')
    def apply_remark_short(self, obj):
        if not obj.apply_remark:
            return '—'
        return obj.apply_remark[:30] + ('...' if len(obj.apply_remark) > 30 else '')

    @admin.display(description='审核备注')
    def audit_remark_short(self, obj):
        if not obj.audit_remark:
            return '—'
        return obj.audit_remark[:30] + ('...' if len(obj.audit_remark) > 30 else '')

    @admin.display(description='已得收益')
    def earned_summary(self, obj):
        return format_html(
            '<span style="color:#fa8c16;font-weight:600;">{}🪙</span>'
            '<span style="color:#8c8c8c;font-size:11px;"> · 用户领{}次</span>',
            obj.merchant_earned_coins or 0,
            obj.user_granted_count or 0,
        )

    @admin.action(description='✅ 通过选中报名')
    def action_approve(self, request, queryset):
        n = 0
        for enr in queryset.filter(status=MerchantActivityEnrollment.Status.PENDING):
            enr.status = MerchantActivityEnrollment.Status.ACTIVE
            enr.audit_remark = enr.audit_remark or '管理员批量通过'
            enr.audited_by_id = request.user.id
            enr.audited_at = timezone.now()
            enr.save(update_fields=[
                'status', 'audit_remark', 'audited_by_id', 'audited_at', 'updated_at',
            ])
            n += 1
        self.message_user(request, f'已通过 {n} 个报名', messages.SUCCESS)

    @admin.action(description='❌ 拒绝选中报名')
    def action_reject(self, request, queryset):
        n = 0
        for enr in queryset.filter(status=MerchantActivityEnrollment.Status.PENDING):
            enr.status = MerchantActivityEnrollment.Status.REJECTED
            enr.audit_remark = enr.audit_remark or '管理员批量拒绝'
            enr.audited_by_id = request.user.id
            enr.audited_at = timezone.now()
            enr.save(update_fields=[
                'status', 'audit_remark', 'audited_by_id', 'audited_at', 'updated_at',
            ])
            n += 1
        self.message_user(request, f'已拒绝 {n} 个报名', messages.WARNING)


# ══════════════════════════════════════════════════════════════
# 3. 用户活动领取记录
# ══════════════════════════════════════════════════════════════

@admin.register(ActivityUserGrant)
class ActivityUserGrantAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'activity_link',
        'user_id',
        'merchant_id',
        'order_or_payment',
        'trigger_amount_display',
        'reward_coins_display',
        'revoke_status',
        'created_at',
    ]
    list_filter = [
        'is_revoked',
        'activity__activity_type',
        'activity',
    ]
    search_fields = ['payment_no', 'order_no', 'user_id', 'merchant_id']
    list_per_page = 50
    ordering = ['-created_at']
    readonly_fields = [
        'activity', 'user_id', 'merchant_id',
        'payment_no', 'order_no',
        'trigger_amount', 'reward_coins',
        'is_revoked', 'revoked_at',
        'created_at',
    ]
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('activity')

    @admin.display(description='活动')
    def activity_link(self, obj):
        if not obj.activity_id:
            return '—'
        name = obj.activity.name if obj.activity else f'#{obj.activity_id}'
        url = reverse('admin:promotions_paymentactivity_change', args=[obj.activity_id])
        return format_html('<a href="{}" target="_blank">{}</a>', url, name)

    @admin.display(description='单据')
    def order_or_payment(self, obj):
        if obj.order_no:
            return format_html(
                '<span style="font-family:monospace;font-size:11px;">订单 {}</span>',
                obj.order_no,
            )
        return format_html(
            '<span style="font-family:monospace;font-size:11px;">付款 {}</span>',
            obj.payment_no,
        )

    @admin.display(description='触发金额', ordering='trigger_amount')
    def trigger_amount_display(self, obj):
        return format_html('¥ <b>{}</b>', obj.trigger_amount)

    @admin.display(description='获得金币', ordering='reward_coins')
    def reward_coins_display(self, obj):
        if obj.is_revoked:
            return format_html(
                '<span style="color:#f5222d;text-decoration:line-through;">+{}🪙</span>',
                obj.reward_coins,
            )
        return format_html(
            '<span style="color:#fa8c16;font-weight:600;font-size:14px;">+{}🪙</span>',
            obj.reward_coins,
        )

    @admin.display(description='状态')
    def revoke_status(self, obj):
        # ★ 纯静态 HTML 用 mark_safe,不用 format_html(Django 6.0 严格校验)
        if obj.is_revoked:
            return mark_safe(
                '<span style="background:#f5222d;color:#fff;padding:2px 10px;'
                'border-radius:10px;font-size:11px;">已撤销</span>'
            )
        return mark_safe(
            '<span style="background:#52c41a;color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:11px;">已发放</span>'
        )
# ══════════════════════════════════════════════════════════════
# 4. 商家入金记录(四态)
# ══════════════════════════════════════════════════════════════

@admin.register(ActivityMerchantEarn)
class ActivityMerchantEarnAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'activity_link',
        'merchant_link',
        'order_no_short',
        'order_type',
        'trigger_amount_display',
        'earned_coins_display',
        'frozen_status_badge',
        'unfrozen_at',
        'created_at',
    ]
    list_filter = [
        'frozen_status',
        'is_revoked',
        'order_type',
        'activity',
    ]
    search_fields = ['order_no', 'merchant__name', 'activity__name']
    list_per_page = 50
    ordering = ['-created_at']
    readonly_fields = [
        'activity', 'merchant',
        'order_no', 'order_type',
        'trigger_amount', 'earned_coins',
        'frozen_status', 'unfrozen_at',
        'is_revoked', 'revoked_at',
        'created_at',
    ]
    date_hierarchy = 'created_at'
    actions = [
        'action_retry_revoke',
        'action_mark_revoked_manually',
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('activity', 'merchant')

    @admin.display(description='活动')
    def activity_link(self, obj):
        if not obj.activity_id:
            return '—'
        name = obj.activity.name if obj.activity else f'#{obj.activity_id}'
        url = reverse('admin:promotions_paymentactivity_change', args=[obj.activity_id])
        return format_html('<a href="{}" target="_blank">{}</a>', url, name)

    @admin.display(description='商家')
    def merchant_link(self, obj):
        if not obj.merchant_id:
            return '—'
        name = obj.merchant.name if obj.merchant else f'#{obj.merchant_id}'
        try:
            url = reverse('admin:merchants_merchant_change', args=[obj.merchant_id])
            return format_html('<a href="{}" target="_blank">{}</a>', url, name)
        except Exception:
            return name

    @admin.display(description='订单号')
    def order_no_short(self, obj):
        if not obj.order_no:
            return '—'
        return format_html(
            '<span style="font-family:monospace;font-size:11px;">{}</span>',
            obj.order_no[:16] + ('...' if len(obj.order_no) > 16 else ''),
        )

    @admin.display(description='触发金额', ordering='trigger_amount')
    def trigger_amount_display(self, obj):
        return format_html('¥ <b>{}</b>', obj.trigger_amount)

    @admin.display(description='获得金币', ordering='earned_coins')
    def earned_coins_display(self, obj):
        status = obj.frozen_status
        if status == ActivityMerchantEarn.FrozenStatus.FROZEN:
            return format_html(
                '<span style="color:#bfbfbf;font-weight:600;">+{}🪙 (冻结)</span>',
                obj.earned_coins,
            )
        if status == ActivityMerchantEarn.FrozenStatus.REVOKED:
            return format_html(
                '<span style="color:#f5222d;text-decoration:line-through;">+{}🪙</span>',
                obj.earned_coins,
            )
        if status == ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING:
            return format_html(
                '<span style="color:#cf1322;font-weight:600;">+{}🪙 ⚠</span>',
                obj.earned_coins,
            )
        # UNFROZEN
        return format_html(
            '<span style="color:#fa8c16;font-weight:600;font-size:14px;">+{}🪙</span>',
            obj.earned_coins,
        )

    @admin.display(description='冻结状态', ordering='frozen_status')
    def frozen_status_badge(self, obj):
        styles = {
            ActivityMerchantEarn.FrozenStatus.FROZEN:
                ('🔒 冻结中', '#faad14'),
            ActivityMerchantEarn.FrozenStatus.UNFROZEN:
                ('✅ 已到账', '#52c41a'),
            ActivityMerchantEarn.FrozenStatus.REVOKED:
                ('⛔ 已撤销', '#f5222d'),
            ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING:
                ('⚠ 撤销待人工', '#cf1322'),
        }
        text, color = styles.get(obj.frozen_status, (obj.frozen_status, '#999'))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:11px;font-weight:600;">{}</span>',
            color, text,
        )

    # ─── 批量操作:撤销挂起的运营处理 ───
    @admin.action(description='🔄 重试撤销(对 REVOKE_PENDING 重新扣商家金币)')
    def action_retry_revoke(self, request, queryset):
        """
        对 REVOKE_PENDING 的记录重试一次扣回。
        如果商家金币足够 → 扣回 + 标记 REVOKED;
        如果还是不够 → 状态保持 REVOKE_PENDING,告警。
        """
        from django.db import transaction
        from wallet.models import MerchantWallet, MerchantWalletTransaction
        from promotions.models import PaymentActivity

        ok, fail = 0, 0
        for earn in queryset.filter(
            frozen_status=ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING,
        ):
            mw = MerchantWallet.objects.filter(merchant_id=earn.merchant_id).first()
            if not mw:
                fail += 1
                continue
            try:
                with transaction.atomic():
                    mw.change_gold(
                        amount=-earn.earned_coins,
                        action=MerchantWalletTransaction.Action.GOLD_DEDUCT,
                        operator_id=request.user.id,
                        operator_role='admin',
                        related_order_no=earn.order_no,
                        related_type='payment_activity_revoke',
                        related_id=earn.activity_id,
                        remark=f'管理员重试撤销 earn_id={earn.id}',
                        idempotent_key=f'amerch_revoke_retry_{earn.id}_{request.user.id}',
                    )
                    earn.frozen_status = ActivityMerchantEarn.FrozenStatus.REVOKED
                    earn.is_revoked = True
                    earn.revoked_at = timezone.now()
                    earn.save(update_fields=[
                        'frozen_status', 'is_revoked', 'revoked_at',
                    ])
                    try:
                        act = PaymentActivity.objects.get(pk=earn.activity_id)
                        act.refund_merchant_budget(earn.earned_coins)
                    except PaymentActivity.DoesNotExist:
                        pass
                ok += 1
            except Exception:
                logger.exception('重试撤销失败 earn_id=%s', earn.id)
                fail += 1

        if ok:
            self.message_user(request, f'已成功撤销 {ok} 条', messages.SUCCESS)
        if fail:
            self.message_user(
                request,
                f'{fail} 条撤销失败(商家金币不足或钱包异常,保留 REVOKE_PENDING)',
                messages.ERROR,
            )

    @admin.action(description='🖋 标记为已撤销(仅改状态,不扣钱包,慎用)')
    def action_mark_revoked_manually(self, request, queryset):
        """
        最后兜底:确认线下已收回 / 不再追回,直接把 REVOKE_PENDING 标成 REVOKED。
        不动钱包余额。仅供对账完毕后使用。
        """
        n = queryset.filter(
            frozen_status=ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING,
        ).update(
            frozen_status=ActivityMerchantEarn.FrozenStatus.REVOKED,
            is_revoked=True,
            revoked_at=timezone.now(),
        )
        self.message_user(
            request,
            f'已强制标记 {n} 条为已撤销(钱包未变动)',
            messages.WARNING,
        )