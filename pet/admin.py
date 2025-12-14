from django.contrib import admin
from django.utils.html import format_html
from .models import PetCategory, Pet, PetDiary, PetServiceRecord


@admin.register(PetCategory)
class PetCategoryAdmin(admin.ModelAdmin):
    """宠物分类管理"""
    list_display = [
        'id', 'name', 'icon_preview', 'sort_order',
        'is_active', 'pet_count', 'created_at'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    ordering = ['sort_order', 'id']
    list_editable = ['sort_order', 'is_active']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'icon', 'sort_order')
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def icon_preview(self, obj):
        """图标预览"""
        if obj.icon:
            return format_html(
                '<img src="{}" width="40" height="40" style="border-radius: 4px;"/>',
                obj.icon
            )
        return '-'

    icon_preview.short_description = '图标预览'

    def pet_count(self, obj):
        """该分类下的宠物数量"""
        return obj.pets.filter(is_deleted=False).count()

    pet_count.short_description = '宠物数量'


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    """宠物管理"""
    list_display = [
        'id', 'name', 'avatar_preview', 'owner_link', 'category',
        'breed', 'gender_display', 'age_display', 'weight',
        'is_deleted', 'created_at'
    ]
    list_filter = [
        'category', 'gender', 'is_deleted',
        'created_at', 'birth_date'
    ]
    search_fields = [
        'name', 'breed', 'owner__username',
        'owner__email', 'color'
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('基本信息', {
            'fields': (
                'owner', 'category', 'name', 'breed',
                'birth_date', 'gender', 'weight', 'color'
            )
        }),
        ('外观', {
            'fields': ('avatar',)
        }),
        ('详细信息', {
            'fields': (
                'personality', 'health_status',
                'vaccination_record', 'special_notes'
            ),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('is_deleted',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    autocomplete_fields = ['owner', 'category']

    def avatar_preview(self, obj):
        """头像预览"""
        if obj.avatar:
            return format_html(
                '<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;"/>',
                obj.avatar
            )
        return '-'

    avatar_preview.short_description = '头像'

    def owner_link(self, obj):
        """主人链接"""
        from django.urls import reverse
        url = reverse('admin:user_user_change', args=[obj.owner.id])
        return format_html('<a href="{}">{}</a>', url, obj.owner.username)

    owner_link.short_description = '主人'

    def gender_display(self, obj):
        """性别显示"""
        return obj.get_gender_display()

    gender_display.short_description = '性别'

    def age_display(self, obj):
        """年龄显示"""
        if obj.age_months is None:
            return '-'
        years = obj.age_years
        months = obj.age_months % 12
        if years > 0:
            return f"{years}岁{months}个月" if months > 0 else f"{years}岁"
        return f"{months}个月"

    age_display.short_description = '年龄'

    actions = ['mark_as_deleted', 'mark_as_active']

    def mark_as_deleted(self, request, queryset):
        """批量软删除"""
        updated = queryset.update(is_deleted=True)
        self.message_user(request, f'成功标记 {updated} 只宠物为已删除')

    mark_as_deleted.short_description = '标记为已删除'

    def mark_as_active(self, request, queryset):
        """批量恢复"""
        updated = queryset.update(is_deleted=False)
        self.message_user(request, f'成功恢复 {updated} 只宠物')

    mark_as_active.short_description = '恢复宠物'


@admin.register(PetDiary)
class PetDiaryAdmin(admin.ModelAdmin):
    """宠物日记管理"""
    list_display = [
        'id', 'title', 'pet_link', 'author_link',
        'diary_type_display', 'diary_date',
        'has_images', 'has_videos', 'created_at'
    ]
    list_filter = [
        'diary_type', 'diary_date',
        'created_at', 'pet__category'
    ]
    search_fields = [
        'title', 'content', 'pet__name',
        'author__username'
    ]
    ordering = ['-diary_date', '-created_at']
    date_hierarchy = 'diary_date'

    fieldsets = (
        ('基本信息', {
            'fields': ('pet', 'author', 'diary_type', 'diary_date')
        }),
        ('内容', {
            'fields': ('title', 'content')
        }),
        ('媒体', {
            'fields': ('images', 'videos'),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    autocomplete_fields = ['pet', 'author']

    def pet_link(self, obj):
        """宠物链接"""
        from django.urls import reverse
        url = reverse('admin:pet_pet_change', args=[obj.pet.id])
        return format_html('<a href="{}">{}</a>', url, obj.pet.name)

    pet_link.short_description = '宠物'

    def author_link(self, obj):
        """作者链接"""
        from django.urls import reverse
        url = reverse('admin:user_user_change', args=[obj.author.id])
        return format_html('<a href="{}">{}</a>', url, obj.author.username)

    author_link.short_description = '记录人'

    def diary_type_display(self, obj):
        """日记类型显示"""
        colors = {
            'daily': '#52c41a',
            'service': '#1890ff'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.diary_type, '#000'),
            obj.get_diary_type_display()
        )

    diary_type_display.short_description = '类型'

    def has_images(self, obj):
        """是否有图片"""
        has = bool(obj.images and len(obj.images) > 0)
        return format_html(
            '<span style="color: {};">{}</span>',
            '#52c41a' if has else '#d9d9d9',
            '✓' if has else '✗'
        )

    has_images.short_description = '图片'

    def has_videos(self, obj):
        """是否有视频"""
        has = bool(obj.videos and len(obj.videos) > 0)
        return format_html(
            '<span style="color: {};">{}</span>',
            '#52c41a' if has else '#d9d9d9',
            '✓' if has else '✗'
        )

    has_videos.short_description = '视频'


@admin.register(PetServiceRecord)
class PetServiceRecordAdmin(admin.ModelAdmin):
    """宠物服务记录管理"""
    list_display = [
        'id', 'order_link', 'pet_display', 'provider_display',
        'service_date', 'actual_duration_display',
        'rating_display', 'has_feedback', 'created_at'
    ]
    list_filter = [
        'rating', 'actual_start_time',
        'created_at'
    ]
    search_fields = [
        'related_order__id',
        'related_order__user__username',
        'service_summary'
    ]
    ordering = ['-actual_start_time']
    date_hierarchy = 'actual_start_time'

    fieldsets = (
        ('关联信息', {
            'fields': ('related_order', 'related_diary')
        }),
        ('服务时间', {
            'fields': (
                'actual_start_time', 'actual_end_time',
                'actual_duration'
            )
        }),
        ('宠物状况', {
            'fields': (
                'pet_condition_before', 'pet_condition_after',
                'pet_behavior_notes'
            )
        }),
        ('服务结果', {
            'fields': (
                'service_summary', 'professional_recommendations',
                'next_service_suggestion'
            )
        }),
        ('媒体记录', {
            'fields': (
                'before_images', 'after_images', 'process_videos'
            ),
            'classes': ('collapse',)
        }),
        ('客户反馈', {
            'fields': ('customer_feedback', 'rating')
        }),
        ('其他', {
            'fields': ('special_notes',),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at', 'actual_duration']

    autocomplete_fields = ['related_order', 'related_diary']

    def order_link(self, obj):
        """订单链接"""
        from django.urls import reverse
        url = reverse('admin:bill_serviceorder_change', args=[obj.related_order.id])
        return format_html(
            '<a href="{}">订单#{}</a>',
            url, obj.related_order.id
        )

    order_link.short_description = '关联订单'

    def pet_display(self, obj):
        """宠物显示"""
        pet = obj.pet
        if pet:
            from django.urls import reverse
            url = reverse('admin:pet_pet_change', args=[pet.id])
            return format_html('<a href="{}">{}</a>', url, pet.name)
        return '-'

    pet_display.short_description = '宠物'

    def provider_display(self, obj):
        """服务提供者显示"""
        provider = obj.service_provider
        if provider:
            from django.urls import reverse
            url = reverse('admin:user_user_change', args=[provider.id])
            return format_html('<a href="{}">{}</a>', url, provider.username)
        return '-'

    provider_display.short_description = '服务提供者'

    def service_date(self, obj):
        """服务日期"""
        if obj.actual_start_time:
            return obj.actual_start_time.strftime('%Y-%m-%d')
        return '-'

    service_date.short_description = '服务日期'

    def actual_duration_display(self, obj):
        """时长显示"""
        if obj.actual_duration:
            hours = obj.actual_duration // 60
            minutes = obj.actual_duration % 60
            if hours > 0:
                return f"{hours}小时{minutes}分钟"
            return f"{minutes}分钟"
        return '-'

    actual_duration_display.short_description = '实际时长'

    def rating_display(self, obj):
        """评分显示"""
        if obj.rating:
            stars = '⭐' * obj.rating
            return format_html('<span title="{}/5">{}</span>', obj.rating, stars)
        return format_html('<span style="color: #d9d9d9;">未评分</span>')

    rating_display.short_description = '评分'

    def has_feedback(self, obj):
        """是否有反馈"""
        has = bool(obj.customer_feedback)
        return format_html(
            '<span style="color: {};">{}</span>',
            '#52c41a' if has else '#d9d9d9',
            '✓' if has else '✗'
        )

    has_feedback.short_description = '客户反馈'