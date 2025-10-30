from django.contrib import admin
from .models import ServiceModel, PetType, AdditionalService


@admin.register(ServiceModel)
class ServiceModelAdmin(admin.ModelAdmin):
    """基础服务管理"""
    list_display = ('name', 'base_price', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description', 'icon')
    list_editable = ('is_active',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'icon', 'base_price', 'description', 'is_active')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related()


@admin.register(PetType)
class PetTypeAdmin(admin.ModelAdmin):
    """宠物类型管理"""
    list_display = ('name', 'base_price', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'base_price')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'base_price', 'description', 'is_active')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AdditionalService)
class AdditionalServiceAdmin(admin.ModelAdmin):
    """附加服务管理"""
    list_display = ('name', 'price', 'get_applicable_pets_count', 'is_active', 'created_at')
    list_filter = ('is_active', 'applicable_pets', 'created_at')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'price')
    filter_horizontal = ('applicable_pets',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'icon', 'price', 'description', 'is_active')
        }),
        ('适用范围', {
            'fields': ('applicable_pets',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_applicable_pets_count(self, obj):
        """显示适用宠物类型数量"""
        return obj.applicable_pets.count()

    get_applicable_pets_count.short_description = '适用宠物数'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('applicable_pets')


# 自定义admin站点配置
admin.site.site_header = '宠物服务管理系统'
admin.site.site_title = '宠物服务管理'
admin.site.index_title = '欢迎使用宠物服务管理系统'