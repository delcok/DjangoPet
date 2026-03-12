# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import Prize, UserPrize, UserPrizeLog


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'prize_type', 'status', 'need_address',
        'need_appointment', 'sort', 'start_time', 'end_time', 'created_at'
    )
    list_filter = ('prize_type', 'status', 'need_address', 'need_appointment')
    search_fields = ('name', 'title', 'content', 'redeem_contact', 'redeem_phone')
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 20

    fieldsets = (
        ('基础信息', {
            'fields': ('name', 'prize_type', 'title', 'subtitle', 'content', 'cover')
        }),
        ('兑奖信息', {
            'fields': ('redeem_instruction', 'redeem_contact', 'redeem_phone', 'redeem_address')
        }),
        ('领取规则', {
            'fields': ('valid_days', 'start_time', 'end_time', 'need_address', 'need_appointment')
        }),
        ('状态信息', {
            'fields': ('sort', 'status')
        }),
        ('审计信息', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            try:
                obj.created_by_id = request.user.id
            except Exception:
                pass
        try:
            obj.updated_by_id = request.user.id
        except Exception:
            pass
        super().save_model(request, obj, form, change)


@admin.register(UserPrize)
class UserPrizeAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'prize_snapshot_name', 'prize_snapshot_type',
        'status', 'exchange_code', 'issued_by', 'handled_by',
        'issued_at', 'valid_end_time'
    )
    list_filter = ('status', 'prize_snapshot_type', 'source', 'issued_at')
    search_fields = ('exchange_code', 'user__phone', 'user__username', 'prize_snapshot_name')
    readonly_fields = (
        'exchange_code', 'issued_at', 'read_at', 'claimed_at', 'redeemed_at',
        'created_at', 'updated_at'
    )
    list_per_page = 20


@admin.register(UserPrizeLog)
class UserPrizeLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_prize', 'action', 'operator_staff',
        'old_status', 'new_status', 'note', 'created_at'
    )
    list_filter = ('action', 'created_at')
    search_fields = ('user_prize__exchange_code', 'note')
    readonly_fields = ('created_at',)
    list_per_page = 20
