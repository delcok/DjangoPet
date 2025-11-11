# -*- coding: utf-8 -*-
# strays/admin.py

from django.contrib import admin
from .models import StrayAnimal, StrayAnimalInteraction


@admin.register(StrayAnimal)
class StrayAnimalAdmin(admin.ModelAdmin):
    """流浪动物后台管理"""

    list_display = (
        'id',
        'animal_type',
        'nickname',
        'gender',
        'size',
        'health_status',
        'status',
        'province',
        'city',
        'district',
        'last_seen_date',
        'view_count',
        'interaction_count',
        'is_active',
        'created_at',
    )
    list_filter = (
        'animal_type',
        'gender',
        'size',
        'health_status',
        'status',
        'is_active',
        'province',
        'city',
        'district',
        'last_seen_date',
        'created_at',
    )
    search_fields = (
        'nickname',
        'breed',
        'distinctive_features',
        'behavior_notes',
        'detail_address',
        'reporter__username',
    )
    readonly_fields = (
        'view_count',
        'interaction_count',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'created_at'
    ordering = ('-last_seen_date', '-created_at')
    list_per_page = 20

    fieldsets = (
        ('基础信息', {
            'fields': (
                'reporter',
                'animal_type',
                'nickname',
                'breed',
                'primary_color',
                'secondary_color',
                'size',
                'gender',
                'estimated_age',
                'distinctive_features',
                'behavior_notes',
                'health_status',
                'is_friendly',
                'status',
            )
        }),
        ('位置信息', {
            'fields': (
                'province',
                'city',
                'district',
                'detail_address',
                'latitude',
                'longitude',
                'location_tips',
            )
        }),
        ('时间与状态', {
            'fields': (
                'first_seen_date',
                'last_seen_date',
                'is_active',
                'created_at',
                'updated_at',
            )
        }),
        ('图片与统计', {
            'fields': (
                'main_image_url',
                'image_urls',
                'view_count',
                'interaction_count',
            )
        }),
    )


@admin.register(StrayAnimalInteraction)
class StrayAnimalInteractionAdmin(admin.ModelAdmin):
    """流浪动物互动记录后台管理"""

    list_display = (
        'id',
        'animal',
        'user',
        'interaction_type',
        'content',
        'latitude',
        'longitude',
        'created_at',
    )
    list_filter = (
        'interaction_type',
        'created_at',
    )
    search_fields = (
        'animal__nickname',
        'animal__distinctive_features',
        'user__username',
        'content',
    )
    raw_id_fields = ('animal', 'user')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 20
