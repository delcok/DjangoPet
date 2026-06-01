# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import Campaign, CouponTemplate, UserCoupon, RedemptionLog


@admin.register(CouponTemplate)
class CouponTemplateAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'coupon_type', 'face_value', 'is_active', 'created_at']
    list_filter = ['coupon_type', 'is_active', 'validity_type']
    search_fields = ['name']


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'status', 'start_time', 'end_time',
                    'claimed_count', 'total_quota']
    list_filter = ['status']
    search_fields = ['name', 'wx_scene']
    readonly_fields = ['claimed_count', 'wx_scene']


@admin.register(UserCoupon)
class UserCouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'snapshot_name', 'user', 'status',
                    'claimed_at', 'used_at', 'redeemed_by']
    list_filter = ['status']
    search_fields = ['code', 'user__nickname', 'user__phone']
    readonly_fields = ['code', 'claimed_at']


@admin.register(RedemptionLog)
class RedemptionLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_coupon', 'action', 'operator', 'amount', 'created_at']
    list_filter = ['action']
    search_fields = ['user_coupon__code']
    readonly_fields = [f.name for f in RedemptionLog._meta.fields]