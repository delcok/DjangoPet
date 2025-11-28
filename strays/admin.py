# -*- coding: utf-8 -*-
# strays/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count
from .models import (
    StrayAnimal,
    StrayAnimalInteraction,
    StrayAnimalFavorite,
    StrayAnimalReport
)


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
        'favorite_count',
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
        'favorite_count',
        'created_at',
        'updated_at',
        'favorite_users_display',
        'recent_interactions_display',
    )
    date_hierarchy = 'created_at'
    ordering = ('-last_seen_date', '-created_at')
    list_per_page = 20
    actions = ['mark_as_rescued', 'mark_as_adopted', 'deactivate_animals']

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
                'favorite_count',
            )
        }),
        ('收藏与互动', {
            'fields': (
                'favorite_users_display',
                'recent_interactions_display',
            ),
            'classes': ('collapse',),
        }),
    )

    def favorite_users_display(self, obj):
        """显示收藏该动物的用户列表"""
        favorites = obj.favorited_by.select_related('user')[:10]
        if favorites:
            users = [f'<a href="/admin/user/user/{fav.user.id}/change/">{fav.user.username}</a>'
                    for fav in favorites]
            result = ', '.join(users)
            if obj.favorite_count > 10:
                result += f' ... (共{obj.favorite_count}人)'
            return format_html(result)
        return '暂无收藏'
    favorite_users_display.short_description = '收藏用户'

    def recent_interactions_display(self, obj):
        """显示最近的互动记录"""
        interactions = obj.interactions.select_related('user')[:5]
        if interactions:
            items = []
            for inter in interactions:
                items.append(
                    f'<div style="margin: 5px 0;">'
                    f'<strong>{inter.get_interaction_type_display()}</strong> - '
                    f'{inter.user.username}: {inter.content[:50] if inter.content else "无内容"}'
                    f'<span style="color: #999;"> ({inter.created_at.strftime("%Y-%m-%d %H:%M")})</span>'
                    f'</div>'
                )
            return format_html(''.join(items))
        return '暂无互动'
    recent_interactions_display.short_description = '最近互动'

    def mark_as_rescued(self, request, queryset):
        """批量标记为已救助"""
        updated = queryset.update(status='rescued')
        self.message_user(request, f'成功标记 {updated} 只动物为已救助')
    mark_as_rescued.short_description = '标记为已救助'

    def mark_as_adopted(self, request, queryset):
        """批量标记为已领养"""
        updated = queryset.update(status='adopted')
        self.message_user(request, f'成功标记 {updated} 只动物为已领养')
    mark_as_adopted.short_description = '标记为已领养'

    def deactivate_animals(self, request, queryset):
        """批量停用"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'成功停用 {updated} 只动物')
    deactivate_animals.short_description = '停用选中的动物'


@admin.register(StrayAnimalInteraction)
class StrayAnimalInteractionAdmin(admin.ModelAdmin):
    """流浪动物互动记录后台管理"""

    list_display = (
        'id',
        'animal_link',
        'user_link',
        'interaction_type',
        'content_preview',
        'has_location',
        'has_image',
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

    fieldsets = (
        ('基本信息', {
            'fields': ('animal', 'user', 'interaction_type')
        }),
        ('内容', {
            'fields': ('content', 'image_url')
        }),
        ('位置信息', {
            'fields': ('latitude', 'longitude'),
            'classes': ('collapse',)
        }),
        ('时间', {
            'fields': ('created_at',)
        }),
    )

    readonly_fields = ('created_at',)

    def animal_link(self, obj):
        """动物链接"""
        url = f'/admin/strays/strayanimal/{obj.animal.id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.animal.nickname or f'动物#{obj.animal.id}')
    animal_link.short_description = '动物'

    def user_link(self, obj):
        """用户链接"""
        url = f'/admin/user/user/{obj.user.id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = '用户'

    def content_preview(self, obj):
        """内容预览"""
        if obj.content:
            preview = obj.content[:50]
            if len(obj.content) > 50:
                preview += '...'
            return preview
        return '-'
    content_preview.short_description = '内容'

    def has_location(self, obj):
        """是否有位置信息"""
        if obj.latitude and obj.longitude:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: #ccc;">-</span>')
    has_location.short_description = '位置'

    def has_image(self, obj):
        """是否有图片"""
        if obj.image_url:
            return format_html('<a href="{}" target="_blank">查看</a>', obj.image_url)
        return format_html('<span style="color: #ccc;">-</span>')
    has_image.short_description = '图片'


@admin.register(StrayAnimalFavorite)
class StrayAnimalFavoriteAdmin(admin.ModelAdmin):
    """收藏记录后台管理"""

    list_display = (
        'id',
        'user_link',
        'animal_link',
        'animal_status',
        'created_at',
    )
    list_filter = (
        'animal__status',
        'animal__animal_type',
        'created_at',
    )
    search_fields = (
        'user__username',
        'animal__nickname',
        'animal__distinctive_features',
    )
    raw_id_fields = ('user', 'animal')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 20
    readonly_fields = ('created_at',)

    def user_link(self, obj):
        """用户链接"""
        url = f'/admin/user/user/{obj.user.id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = '用户'

    def animal_link(self, obj):
        """动物链接"""
        url = f'/admin/strays/strayanimal/{obj.animal.id}/change/'
        nickname = obj.animal.nickname or f'动物#{obj.animal.id}'
        animal_type = obj.animal.get_animal_type_display()
        return format_html('<a href="{}">{} ({})</a>', url, nickname, animal_type)
    animal_link.short_description = '动物'

    def animal_status(self, obj):
        """动物状态"""
        status_colors = {
            'active': 'green',
            'missing': 'orange',
            'rescued': 'blue',
            'adopted': 'purple',
        }
        color = status_colors.get(obj.animal.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.animal.get_status_display()
        )
    animal_status.short_description = '动物状态'

    def get_queryset(self, request):
        """优化查询"""
        qs = super().get_queryset(request)
        return qs.select_related('user', 'animal')


@admin.register(StrayAnimalReport)
class StrayAnimalReportAdmin(admin.ModelAdmin):
    """举报记录后台管理"""

    list_display = (
        'id',
        'reporter_link',
        'target_display',
        'report_type_display',
        'status_display',
        'handler_link',
        'created_at',
        'handled_at',
    )
    list_filter = (
        'report_type',
        'status',
        'created_at',
        'handled_at',
    )
    search_fields = (
        'reporter__username',
        'reason',
        'handler_note',
        'animal__nickname',
    )
    raw_id_fields = ('reporter', 'animal', 'interaction', 'handler')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 20
    actions = ['mark_as_processing', 'mark_as_resolved', 'mark_as_rejected']

    fieldsets = (
        ('举报信息', {
            'fields': (
                'reporter',
                'report_type',
                'reason',
                'animal',
                'interaction',
            )
        }),
        ('处理信息', {
            'fields': (
                'status',
                'handler',
                'handler_note',
                'handled_at',
            )
        }),
        ('时间信息', {
            'fields': ('created_at',)
        }),
    )

    readonly_fields = ('created_at',)

    def reporter_link(self, obj):
        """举报人链接"""
        url = f'/admin/user/user/{obj.reporter.id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.reporter.username)
    reporter_link.short_description = '举报人'

    def target_display(self, obj):
        """举报目标"""
        if obj.animal:
            url = f'/admin/strays/strayanimal/{obj.animal.id}/change/'
            nickname = obj.animal.nickname or f'动物#{obj.animal.id}'
            return format_html('<a href="{}">动物: {}</a>', url, nickname)
        elif obj.interaction:
            url = f'/admin/strays/strayanimalinteraction/{obj.interaction.id}/change/'
            return format_html('<a href="{}">互动 #{}</a>', url, obj.interaction.id)
        return '-'
    target_display.short_description = '举报目标'

    def report_type_display(self, obj):
        """举报类型"""
        type_colors = {
            'fake_info': '#ff6b6b',
            'inappropriate': '#ee5a6f',
            'spam': '#ff922b',
            'abuse': '#d63031',
            'duplicate': '#74b9ff',
            'other': '#95afc0',
        }
        color = type_colors.get(obj.report_type, '#95afc0')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.get_report_type_display()
        )
    report_type_display.short_description = '举报类型'

    def status_display(self, obj):
        """处理状态"""
        status_config = {
            'pending': ('#ffeaa7', '#fdcb6e', '待处理'),
            'processing': ('#74b9ff', '#0984e3', '处理中'),
            'resolved': ('#55efc4', '#00b894', '已处理'),
            'rejected': ('#dfe6e9', '#636e72', '已驳回'),
        }
        bg_color, text_color, text = status_config.get(
            obj.status,
            ('#dfe6e9', '#636e72', obj.get_status_display())
        )
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; '
            'border-radius: 3px; font-weight: bold; font-size: 11px;">{}</span>',
            bg_color,
            text_color,
            text
        )
    status_display.short_description = '状态'

    def handler_link(self, obj):
        """处理人链接"""
        if obj.handler:
            url = f'/admin/user/user/{obj.handler.id}/change/'
            return format_html('<a href="{}">{}</a>', url, obj.handler.username)
        return format_html('<span style="color: #999;">未处理</span>')
    handler_link.short_description = '处理人'

    def mark_as_processing(self, request, queryset):
        """标记为处理中"""
        from django.utils import timezone
        updated = queryset.filter(status='pending').update(
            status='processing',
            handler_id=request.user.id,  # 修改这里：使用 handler_id
            handled_at=timezone.now()
        )
        self.message_user(request, f'成功标记 {updated} 条举报为处理中')
    mark_as_processing.short_description = '标记为处理中'

    def mark_as_resolved(self, request, queryset):
        """标记为已处理"""
        from django.utils import timezone
        updated = queryset.filter(status__in=['pending', 'processing']).update(
            status='resolved',
            handler_id=request.user.id,  # 修改这里：使用 handler_id
            handled_at=timezone.now()
        )
        self.message_user(request, f'成功标记 {updated} 条举报为已处理')
    mark_as_resolved.short_description = '标记为已处理'

    def mark_as_rejected(self, request, queryset):
        """标记为已驳回"""
        from django.utils import timezone
        updated = queryset.filter(status__in=['pending', 'processing']).update(
            status='rejected',
            handler_id=request.user.id,  # 修改这里：使用 handler_id
            handled_at=timezone.now()
        )
        self.message_user(request, f'成功标记 {updated} 条举报为已驳回')
    mark_as_rejected.short_description = '标记为已驳回'

    def get_queryset(self, request):
        """优化查询"""
        qs = super().get_queryset(request)
        return qs.select_related('reporter', 'animal', 'interaction', 'handler')

    def save_model(self, request, obj, form, change):
        """保存时自动设置处理人和处理时间"""
        if change and 'status' in form.changed_data:
            if obj.status in ['processing', 'resolved', 'rejected'] and not obj.handler:
                obj.handler = request.user
                if not obj.handled_at:
                    from django.utils import timezone
                    obj.handled_at = timezone.now()
        super().save_model(request, obj, form, change)