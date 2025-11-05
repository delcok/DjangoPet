# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Delock (Modified by ChatGPT)

from django.contrib import admin, messages
from .models import ServiceModel, PetType, AdditionalService


# ======================== 宠物类型管理 ========================

@admin.register(PetType)
class PetTypeAdmin(admin.ModelAdmin):
    """宠物类型管理"""
    list_display = [
        'name', 'base_price', 'sort_order', 'is_active',
        'get_services_count', 'get_additional_services_count', 'created_at'
    ]
    list_editable = ['sort_order', 'is_active', 'base_price']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['sort_order', 'name']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'base_price', 'description', 'sort_order', 'is_active'),
            'description': '设置宠物类型的基本信息与状态。'
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_services_count(self, obj):
        """显示关联的基础服务数量"""
        return obj.get_services_count()
    get_services_count.short_description = '基础服务数'

    def get_additional_services_count(self, obj):
        """显示关联的附加服务数量"""
        return obj.get_additional_services_count()
    get_additional_services_count.short_description = '附加服务数'

    def delete_model(self, request, obj):
        """
        在后台删除宠物类型时，添加提示信息并安全解除关联。
        """
        obj_name = obj.name
        super().delete_model(request, obj)
        self.message_user(
            request,
            f"宠物类型“{obj_name}”已删除，相关服务已自动解除关联（未被删除）。",
            level=messages.WARNING
        )


# ======================== 基础服务管理 ========================

@admin.register(ServiceModel)
class ServiceModelAdmin(admin.ModelAdmin):
    """基础服务管理"""
    list_display = [
        'name', 'base_price', 'sort_order', 'is_active',
        'get_applicable_pets_display', 'created_at'
    ]
    list_editable = ['sort_order', 'is_active']
    list_filter = ['is_active', 'applicable_pets', 'created_at']
    search_fields = ['name', 'description', 'icon']
    filter_horizontal = ['applicable_pets']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['sort_order', '-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'icon', 'base_price', 'description', 'sort_order', 'is_active'),
            'description': '基础服务定义及价格设置。'
        }),
        ('适用范围', {
            'fields': ('applicable_pets',),
            'description': '留空表示适用于所有宠物类型。'
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        """优化查询性能"""
        return super().get_queryset(request).prefetch_related('applicable_pets')

    def get_applicable_pets_display(self, obj):
        """显示适用宠物类型"""
        return obj.get_applicable_pets_display()
    get_applicable_pets_display.short_description = '适用宠物类型'


# ======================== 附加服务管理 ========================

@admin.register(AdditionalService)
class AdditionalServiceAdmin(admin.ModelAdmin):
    """附加服务管理"""
    list_display = [
        'name', 'price', 'sort_order', 'is_active',
        'get_applicable_pets_count', 'get_applicable_pets_display', 'created_at'
    ]
    list_editable = ['sort_order', 'is_active', 'price']
    list_filter = ['is_active', 'applicable_pets', 'created_at']
    search_fields = ['name', 'description']
    filter_horizontal = ['applicable_pets']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['sort_order', '-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'icon', 'price', 'description', 'sort_order', 'is_active'),
            'description': '定义附加服务的详细信息。'
        }),
        ('适用范围', {
            'fields': ('applicable_pets',),
            'description': '留空表示适用于所有宠物类型。'
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_applicable_pets_count(self, obj):
        """显示适用宠物类型数量"""
        count = obj.applicable_pets.count()
        return count if count > 0 else '全部类型'
    get_applicable_pets_count.short_description = '适用宠物数'

    def get_applicable_pets_display(self, obj):
        """显示适用宠物类型"""
        return obj.get_applicable_pets_display()
    get_applicable_pets_display.short_description = '适用宠物类型'

    def get_queryset(self, request):
        """优化查询性能"""
        return super().get_queryset(request).prefetch_related('applicable_pets')


# ======================== Admin 界面配置 ========================

admin.site.site_header = '宠物服务管理系统'
admin.site.site_title = '宠物服务管理后台'
admin.site.index_title = '欢迎使用宠物服务管理系统'
