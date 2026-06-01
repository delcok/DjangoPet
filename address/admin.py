# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 17:09
# @Author  : Delock

from django.contrib import admin
from django.utils.html import format_html
from django.db import transaction

from .models import UserAddress


@admin.register(UserAddress)
class UserAddressAdmin(admin.ModelAdmin):
    """用户收货地址管理"""

    # ══════ 列表页 ══════
    list_display = [
        'id',
        'user_info',
        'receiver_name',
        'receiver_phone',
        'address_type_badge',
        'short_address_display',
        'tag_badge',
        'is_default_badge',
        'has_coordinate',
        'updated_at',
    ]
    list_display_links = ['id', 'receiver_name']
    list_filter = [
        'address_type',
        'is_default',
        'tag',
        'province',
        'city',
        'district',
        'created_at',
    ]
    search_fields = [
        'receiver_name',
        'receiver_phone',
        'community',
        'building',
        'street',
        'detail_address',
        'user__phone',
        'user__nickname',
    ]
    list_select_related = ['user']
    list_per_page = 30
    ordering = ['-updated_at']
    date_hierarchy = 'created_at'
    autocomplete_fields = ['user']

    # ══════ 详情页 ══════
    readonly_fields = [
        'detail_address',
        'full_address_display',
        'short_address_display',
        'service_address_display',
        'created_at',
        'updated_at',
    ]
    fieldsets = (
        ('用户与收货人', {
            'fields': (
                'user',
                ('receiver_name', 'receiver_phone'),
            ),
        }),
        ('地址类型', {
            'fields': ('address_type',),
            'description': '社区模式：填写小区/楼栋/单元/门牌号；街道模式：填写街道地址/门牌号',
        }),
        ('省市区', {
            'classes': ('collapse',),
            'fields': (('province', 'city', 'district'),),
            'description': '当前可不填，全国化扩展后启用',
        }),
        ('社区模式字段', {
            'fields': (
                'community',
                ('building', 'unit', 'room'),
            ),
        }),
        ('街道模式字段', {
            'fields': (
                'street',
                'house_number',
            ),
        }),
        ('地址展示（自动拼接）', {
            'classes': ('collapse',),
            'fields': (
                'detail_address',
                'full_address_display',
                'short_address_display',
                'service_address_display',
            ),
        }),
        ('坐标', {
            'classes': ('collapse',),
            'fields': (('longitude', 'latitude'),),
        }),
        ('其他', {
            'fields': (
                'access_instructions',
                ('is_default', 'tag'),
            ),
        }),
        ('时间戳', {
            'classes': ('collapse',),
            'fields': (('created_at', 'updated_at'),),
        }),
    )

    actions = ['action_set_as_default', 'action_unset_default']

    # ══════════════════════════════════════════════════════════
    # 列表展示方法
    # ══════════════════════════════════════════════════════════

    @admin.display(description='用户', ordering='user__id')
    def user_info(self, obj):
        if not obj.user_id:
            return '-'
        nickname = getattr(obj.user, 'nickname', '') or ''
        phone = getattr(obj.user, 'phone', '') or ''
        label = nickname or phone or f'#{obj.user_id}'
        return format_html(
            '<span title="{}">{} <small style="color:#999;">#{}</small></span>',
            phone, label, obj.user_id,
        )

    @admin.display(description='类型', ordering='address_type')
    def address_type_badge(self, obj):
        color_map = {
            UserAddress.AddressType.COMMUNITY: '#1890ff',
            UserAddress.AddressType.STREET: '#52c41a',
        }
        color = color_map.get(obj.address_type, '#999')
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
            'background:{};color:#fff;font-size:12px;">{}</span>',
            color, obj.get_address_type_display(),
        )

    @admin.display(description='地址')
    def short_address_display(self, obj):
        text = obj.short_address or obj.detail_address or '-'
        # 列表页限长，避免一行被撑爆
        return text if len(text) <= 40 else text[:40] + '…'

    @admin.display(description='完整地址')
    def full_address_display(self, obj):
        return obj.full_address or '-'

    @admin.display(description='上门服务地址')
    def service_address_display(self, obj):
        return obj.service_address or '-'

    @admin.display(description='标签', ordering='tag')
    def tag_badge(self, obj):
        if not obj.tag:
            return '-'
        return format_html(
            '<span style="display:inline-block;padding:1px 6px;border:1px solid #d9d9d9;'
            'border-radius:4px;font-size:12px;color:#666;">{}</span>',
            obj.tag,
        )

    @admin.display(description='默认', boolean=True, ordering='is_default')
    def is_default_badge(self, obj):
        return obj.is_default

    @admin.display(description='坐标', boolean=True)
    def has_coordinate(self, obj):
        return obj.longitude is not None and obj.latitude is not None

    # ══════════════════════════════════════════════════════════
    # 批量操作
    # ══════════════════════════════════════════════════════════

    @admin.action(description='设为该用户的默认地址（仅当选中1条时生效）')
    def action_set_as_default(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                '请仅选择 1 条地址进行此操作',
                level='warning',
            )
            return
        address = queryset.first()
        with transaction.atomic():
            UserAddress.objects.filter(
                user=address.user, is_default=True
            ).exclude(pk=address.pk).update(is_default=False)
            address.is_default = True
            address.save(update_fields=['is_default', 'updated_at'])
        self.message_user(
            request,
            f'已将「{address.receiver_name} - {address.short_address}」设为默认地址',
        )

    @admin.action(description='取消默认地址标记')
    def action_unset_default(self, request, queryset):
        updated = queryset.filter(is_default=True).update(is_default=False)
        self.message_user(request, f'已取消 {updated} 条默认地址')

    # ══════════════════════════════════════════════════════════
    # 保存逻辑（保证默认地址唯一）
    # ══════════════════════════════════════════════════════════

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if obj.is_default:
                UserAddress.objects.filter(
                    user=obj.user, is_default=True
                ).exclude(pk=obj.pk).update(is_default=False)