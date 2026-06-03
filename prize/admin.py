from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Prize, UserPrize, UserPrizeLog


class UserPrizeLogInline(admin.TabularInline):
    model = UserPrizeLog
    extra = 0
    readonly_fields = [
        'action', 'operator_type', 'operator_name',
        'old_status', 'new_status', 'note', 'created_at'
    ]
    fields = [
        'action', 'operator_type', 'operator_name',
        'old_status', 'new_status', 'note', 'created_at'
    ]
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'owner_type', 'merchant_link',
        'prize_type', 'status_badge', 'sort',
        'need_address', 'need_appointment', 'valid_days',
        'created_at'
    ]
    list_filter = [
        'owner_type', 'prize_type', 'status',
        'need_address', 'need_appointment',
        'created_at'
    ]
    search_fields = [
        'name', 'title', 'subtitle', 'content',
        'merchant__name', 'redeem_contact', 'redeem_phone'
    ]
    ordering = ['-id']
    list_editable = ['sort', 'need_address', 'need_appointment']
    autocomplete_fields = [
        'merchant',
        'created_by_manager', 'updated_by_manager',
        'created_by_merchant', 'updated_by_merchant'
    ]
    readonly_fields = ['created_at', 'updated_at', 'cover_preview']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('归属信息', {
            'fields': ('owner_type', 'merchant')
        }),
        ('奖品基础信息', {
            'fields': (
                'name', 'prize_type', 'title', 'subtitle',
                'content', 'cover', 'cover_preview'
            )
        }),
        ('兑奖信息', {
            'fields': (
                'redeem_instruction', 'redeem_contact',
                'redeem_phone', 'redeem_address'
            )
        }),
        ('领取限制', {
            'fields': (
                'valid_days', 'start_time', 'end_time',
                'need_address', 'need_appointment'
            )
        }),
        ('状态与排序', {
            'fields': ('sort', 'status')
        }),
        ('创建/更新人', {
            'fields': (
                'created_by_manager', 'updated_by_manager',
                'created_by_merchant', 'updated_by_merchant'
            ),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['make_active', 'make_disabled', 'make_draft']

    def merchant_link(self, obj):
        if not obj.merchant_id:
            return '-'
        url = reverse('admin:merchants_merchant_change', args=[obj.merchant_id])
        return format_html('<a href="{}">{}</a>', url, obj.merchant)

    merchant_link.short_description = '所属商户'

    def cover_preview(self, obj):
        if obj.cover:
            return format_html(
                '<img src="{}" width="80" height="80" style="border-radius:6px;object-fit:cover;" />',
                obj.cover
            )
        return '-'

    cover_preview.short_description = '封面预览'

    def status_badge(self, obj):
        colors = {
            'draft': '#999',
            'active': '#52c41a',
            'disabled': '#f5222d',
        }
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            colors.get(obj.status, '#333'),
            obj.get_status_display()
        )

    status_badge.short_description = '状态'

    def make_active(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f'成功启用 {updated} 个奖品模板')

    make_active.short_description = '批量启用'

    def make_disabled(self, request, queryset):
        updated = queryset.update(status='disabled')
        self.message_user(request, f'成功停用 {updated} 个奖品模板')

    make_disabled.short_description = '批量停用'

    def make_draft(self, request, queryset):
        updated = queryset.update(status='draft')
        self.message_user(request, f'成功设为草稿 {updated} 个奖品模板')

    make_draft.short_description = '批量设为草稿'


@admin.register(UserPrize)
class UserPrizeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_link', 'prize_link', 'merchant_link',
        'prize_snapshot_name', 'source', 'status_badge',
        'exchange_code', 'can_claim_display',
        'valid_end_time', 'issued_at'
    ]
    list_filter = [
        'status', 'source', 'prize_snapshot_type',
        'need_address', 'need_appointment',
        'merchant', 'issued_at', 'valid_end_time'
    ]
    search_fields = [
        'user__username', 'user__email',
        'prize__name', 'prize_snapshot_name',
        'title', 'exchange_code', 'batch_no',
        'contact_name', 'contact_phone',
        'receiver_name_snapshot', 'receiver_phone_snapshot'
    ]
    ordering = ['-id']
    date_hierarchy = 'issued_at'
    autocomplete_fields = [
        'user', 'prize', 'merchant', 'address',
        'issued_by_manager', 'handled_by_manager',
        'issued_by_merchant', 'handled_by_merchant'
    ]
    readonly_fields = [
        'exchange_code', 'created_at', 'updated_at',
        'is_expired_display', 'can_claim_display',
        'cover_preview'
    ]
    inlines = [UserPrizeLogInline]

    fieldsets = (
        ('用户与奖品', {
            'fields': ('user', 'prize', 'merchant')
        }),
        ('奖品快照', {
            'fields': (
                'prize_snapshot_name', 'prize_snapshot_type',
                'title', 'subtitle', 'content',
                'cover', 'cover_preview'
            )
        }),
        ('兑奖说明快照', {
            'fields': (
                'redeem_instruction', 'redeem_contact',
                'redeem_phone', 'redeem_address'
            ),
            'classes': ('collapse',)
        }),
        ('状态与来源', {
            'fields': (
                'source', 'batch_no', 'exchange_code',
                'status', 'admin_remark'
            )
        }),
        ('有效期与时间节点', {
            'fields': (
                'issued_at', 'valid_start_time', 'valid_end_time',
                'read_at', 'claimed_at', 'redeemed_at',
                'is_expired_display', 'can_claim_display'
            )
        }),
        ('兑奖需求', {
            'fields': ('need_address', 'need_appointment')
        }),
        ('用户填写信息', {
            'fields': (
                'contact_name', 'contact_phone',
                'user_remark', 'address'
            )
        }),
        ('收货地址快照', {
            'fields': (
                'receiver_name_snapshot', 'receiver_phone_snapshot',
                'province_snapshot', 'city_snapshot',
                'district_snapshot', 'detail_address_snapshot'
            ),
            'classes': ('collapse',)
        }),
        ('处理人', {
            'fields': (
                'issued_by_manager', 'handled_by_manager',
                'issued_by_merchant', 'handled_by_merchant'
            ),
            'classes': ('collapse',)
        }),
        ('系统时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'mark_processing', 'mark_redeemed',
        'mark_rejected', 'mark_cancelled',
        'mark_expired_if_needed'
    ]

    def user_link(self, obj):
        if not obj.user_id:
            return '-'
        url = reverse('admin:user_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user)

    user_link.short_description = '中奖用户'

    def prize_link(self, obj):
        if not obj.prize_id:
            return '-'
        url = reverse('admin:prize_prize_change', args=[obj.prize_id])
        return format_html('<a href="{}">{}</a>', url, obj.prize)

    prize_link.short_description = '奖品模板'

    def merchant_link(self, obj):
        if not obj.merchant_id:
            return '-'
        url = reverse('admin:merchants_merchant_change', args=[obj.merchant_id])
        return format_html('<a href="{}">{}</a>', url, obj.merchant)

    merchant_link.short_description = '所属商户'

    def cover_preview(self, obj):
        if obj.cover:
            return format_html(
                '<img src="{}" width="80" height="80" style="border-radius:6px;object-fit:cover;" />',
                obj.cover
            )
        return '-'

    cover_preview.short_description = '封面预览'

    def status_badge(self, obj):
        colors = {
            'pending': '#faad14',
            'claimed': '#1890ff',
            'processing': '#722ed1',
            'redeemed': '#52c41a',
            'expired': '#999',
            'cancelled': '#999',
            'rejected': '#f5222d',
        }
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            colors.get(obj.status, '#333'),
            obj.get_status_display()
        )

    status_badge.short_description = '状态'

    def is_expired_display(self, obj):
        return '是' if obj.is_expired else '否'

    is_expired_display.short_description = '是否过期'

    def can_claim_display(self, obj):
        return '是' if obj.can_claim else '否'

    can_claim_display.short_description = '是否可领取'

    def _create_log(self, obj, action, old_status, new_status, request, note='后台批量操作'):
        UserPrizeLog.objects.create(
            user_prize=obj,
            action=action,
            operator_type='manager',
            operator_name=str(request.user),
            old_status=old_status,
            new_status=new_status,
            note=note
        )

    def _change_status(self, request, queryset, new_status, action, time_field=None):
        count = 0
        for obj in queryset:
            old_status = obj.status
            obj.status = new_status

            update_fields = ['status', 'updated_at']
            if time_field and not getattr(obj, time_field):
                setattr(obj, time_field, timezone.now())
                update_fields.append(time_field)

            obj.save(update_fields=update_fields)
            self._create_log(obj, action, old_status, new_status, request)
            count += 1

        self.message_user(request, f'成功处理 {count} 条中奖记录')

    def mark_processing(self, request, queryset):
        self._change_status(request, queryset, 'processing', 'process')

    mark_processing.short_description = '标记为处理中'

    def mark_redeemed(self, request, queryset):
        self._change_status(request, queryset, 'redeemed', 'redeem', 'redeemed_at')

    mark_redeemed.short_description = '标记为已兑奖'

    def mark_rejected(self, request, queryset):
        self._change_status(request, queryset, 'rejected', 'reject')

    mark_rejected.short_description = '标记为已驳回'

    def mark_cancelled(self, request, queryset):
        self._change_status(request, queryset, 'cancelled', 'cancel')

    mark_cancelled.short_description = '标记为已作废'

    def mark_expired_if_needed(self, request, queryset):
        count = 0
        for obj in queryset:
            if obj.mark_expired_if_needed():
                count += 1
        self.message_user(request, f'成功自动过期 {count} 条中奖记录')

    mark_expired_if_needed.short_description = '检查并标记过期'


@admin.register(UserPrizeLog)
class UserPrizeLogAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_prize_link', 'action', 'operator_type',
        'operator_name', 'old_status', 'new_status', 'created_at'
    ]
    list_filter = ['action', 'operator_type', 'created_at']
    search_fields = [
        'user_prize__exchange_code',
        'user_prize__prize_snapshot_name',
        'operator_name', 'note'
    ]
    ordering = ['-id']
    date_hierarchy = 'created_at'
    autocomplete_fields = ['user_prize', 'operator_manager', 'operator_merchant']
    readonly_fields = ['created_at']

    fieldsets = (
        ('关联记录', {
            'fields': ('user_prize',)
        }),
        ('操作信息', {
            'fields': (
                'action', 'operator_type', 'operator_name',
                'operator_manager', 'operator_merchant'
            )
        }),
        ('状态变化', {
            'fields': ('old_status', 'new_status', 'note')
        }),
        ('时间信息', {
            'fields': ('created_at',)
        }),
    )

    def user_prize_link(self, obj):
        if not obj.user_prize_id:
            return '-'
        url = reverse('admin:prize_userprize_change', args=[obj.user_prize_id])
        return format_html('<a href="{}">中奖记录#{}</a>', url, obj.user_prize_id)

    user_prize_link.short_description = '用户奖品记录'