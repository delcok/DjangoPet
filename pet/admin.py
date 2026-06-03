from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import PetCategory, PetBreed, Pet, PetDiary, PetServiceRecord


@admin.register(PetCategory)
class PetCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'code', 'icon_preview', 'sort_order',
        'is_active', 'breed_count', 'pet_count', 'created_at'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'description']
    ordering = ['sort_order', 'id']
    list_editable = ['sort_order', 'is_active']
    readonly_fields = ['created_at', 'updated_at', 'icon_preview']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'icon', 'icon_preview', 'description', 'sort_order')
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def icon_preview(self, obj):
        if obj.icon:
            return format_html(
                '<img src="{}" width="40" height="40" style="border-radius:4px;object-fit:cover;" />',
                obj.icon
            )
        return '-'

    icon_preview.short_description = '图标预览'

    def breed_count(self, obj):
        return obj.breeds.count()

    breed_count.short_description = '品种数量'

    def pet_count(self, obj):
        return obj.pets.filter(is_deleted=False).count()

    pet_count.short_description = '宠物数量'


@admin.register(PetBreed)
class PetBreedAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'category', 'size', 'is_common',
        'sort_order', 'is_active', 'created_at'
    ]
    list_filter = ['category', 'size', 'is_common', 'is_active', 'created_at']
    search_fields = ['name', 'alias', 'category__name', 'category__code']
    ordering = ['-is_common', 'sort_order', 'id']
    list_editable = ['is_common', 'sort_order', 'is_active']
    autocomplete_fields = ['category']
    readonly_fields = ['created_at', 'updated_at', 'icon_preview']

    fieldsets = (
        ('基本信息', {
            'fields': ('category', 'name', 'alias', 'size')
        }),
        ('展示信息', {
            'fields': ('icon', 'icon_preview', 'is_common', 'sort_order', 'is_active')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def icon_preview(self, obj):
        if obj.icon:
            return format_html(
                '<img src="{}" width="40" height="40" style="border-radius:4px;object-fit:cover;" />',
                obj.icon
            )
        return '-'

    icon_preview.short_description = '品种图标'


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'avatar_preview', 'owner_link', 'category',
        'breed_display_admin', 'gender_display', 'age_display',
        'weight', 'is_deleted', 'created_at'
    ]
    list_filter = [
        'category', 'breed', 'gender', 'adoption_period',
        'is_deleted', 'created_at', 'birth_date'
    ]
    search_fields = [
        'name', 'breed__name', 'breed_name',
        'owner__username', 'owner__email', 'color'
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    autocomplete_fields = ['owner', 'category', 'breed']
    readonly_fields = ['created_at', 'updated_at', 'avatar_preview', 'age_display']

    fieldsets = (
        ('基本信息', {
            'fields': (
                'owner', 'category', 'breed', 'breed_name',
                'name', 'birth_date', 'adoption_period',
                'gender', 'weight', 'color'
            )
        }),
        ('头像', {
            'fields': ('avatar', 'avatar_preview')
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

    actions = ['mark_as_deleted', 'mark_as_active']

    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" width="50" height="50" style="border-radius:50%;object-fit:cover;" />',
                obj.avatar
            )
        return '-'

    avatar_preview.short_description = '头像'

    def owner_link(self, obj):
        if not obj.owner_id:
            return '-'
        url = reverse('admin:user_user_change', args=[obj.owner.id])
        return format_html('<a href="{}">{}</a>', url, obj.owner.username)

    owner_link.short_description = '主人'

    def breed_display_admin(self, obj):
        return obj.breed_display or '-'

    breed_display_admin.short_description = '品种'

    def gender_display(self, obj):
        return obj.get_gender_display()

    gender_display.short_description = '性别'

    def age_display(self, obj):
        if obj.age_months is None:
            return '-'
        years = obj.age_years
        months = obj.age_months % 12
        if years > 0:
            return f'{years}岁{months}个月' if months else f'{years}岁'
        return f'{months}个月'

    age_display.short_description = '年龄'

    def mark_as_deleted(self, request, queryset):
        updated = queryset.update(is_deleted=True)
        self.message_user(request, f'成功标记 {updated} 只宠物为已删除')

    mark_as_deleted.short_description = '标记为已删除'

    def mark_as_active(self, request, queryset):
        updated = queryset.update(is_deleted=False)
        self.message_user(request, f'成功恢复 {updated} 只宠物')

    mark_as_active.short_description = '恢复宠物'


@admin.register(PetDiary)
class PetDiaryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'title', 'pet_link', 'author_link',
        'diary_type_display', 'amount', 'expense_type',
        'diary_date', 'has_images', 'has_videos', 'created_at'
    ]
    list_filter = [
        'diary_type', 'expense_type', 'diary_date',
        'created_at', 'pet__category'
    ]
    search_fields = [
        'title', 'content', 'pet__name',
        'author__username', 'hospital'
    ]
    ordering = ['-diary_date', '-created_at']
    date_hierarchy = 'diary_date'
    autocomplete_fields = ['pet', 'author']
    readonly_fields = ['created_at', 'updated_at', 'cover_preview']

    fieldsets = (
        ('基本信息', {
            'fields': ('pet', 'author', 'diary_type', 'diary_date')
        }),
        ('内容', {
            'fields': ('title', 'content')
        }),
        ('媒体', {
            'fields': ('images', 'videos', 'cover_image', 'cover_preview'),
            'classes': ('collapse',)
        }),
        ('记账信息', {
            'fields': ('amount', 'expense_type'),
            'classes': ('collapse',)
        }),
        ('病历信息', {
            'fields': ('hospital', 'next_visit_date'),
            'classes': ('collapse',)
        }),
        ('附加数据', {
            'fields': ('extra',),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def pet_link(self, obj):
        if not obj.pet_id:
            return '-'
        url = reverse('admin:pet_pet_change', args=[obj.pet.id])
        return format_html('<a href="{}">{}</a>', url, obj.pet.name or '未命名宠物')

    pet_link.short_description = '宠物'

    def author_link(self, obj):
        if not obj.author_id:
            return '-'
        url = reverse('admin:user_user_change', args=[obj.author.id])
        return format_html('<a href="{}">{}</a>', url, obj.author.username)

    author_link.short_description = '记录人'

    def diary_type_display(self, obj):
        colors = {
            'daily': '#52c41a',
            'bill': '#fa8c16',
            'medical': '#f5222d',
            'service': '#1890ff',
            'growth': '#722ed1',
        }
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            colors.get(obj.diary_type, '#000'),
            obj.get_diary_type_display()
        )

    diary_type_display.short_description = '类型'

    def cover_preview(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" width="80" height="80" style="border-radius:4px;object-fit:cover;" />',
                obj.cover_image
            )
        return '-'

    cover_preview.short_description = '封面预览'

    def has_images(self, obj):
        has = bool(obj.images)
        return '✓' if has else '✗'

    has_images.short_description = '图片'

    def has_videos(self, obj):
        has = bool(obj.videos)
        return '✓' if has else '✗'

    has_videos.short_description = '视频'


@admin.register(PetServiceRecord)
class PetServiceRecordAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'order_link', 'pet_display', 'provider_display',
        'service_date', 'actual_duration_display',
        'rating_display', 'has_feedback', 'created_at'
    ]
    list_filter = ['rating', 'actual_start_time', 'created_at']
    search_fields = [
        'related_order__id',
        'related_order__user__username',
        'service_summary',
        'customer_feedback'
    ]
    ordering = ['-actual_start_time']
    date_hierarchy = 'actual_start_time'
    autocomplete_fields = ['related_order', 'related_diary']
    readonly_fields = ['created_at', 'updated_at', 'actual_duration']

    fieldsets = (
        ('关联信息', {
            'fields': ('related_order', 'related_diary')
        }),
        ('服务时间', {
            'fields': ('actual_start_time', 'actual_end_time', 'actual_duration')
        }),
        ('宠物状况', {
            'fields': (
                'pet_condition_before', 'pet_condition_after',
                'pet_behavior_notes'
            )
        }),
        ('服务结果', {
            'fields': (
                'service_summary',
                'professional_recommendations',
                'next_service_suggestion'
            )
        }),
        ('媒体记录', {
            'fields': ('before_images', 'after_images', 'process_videos'),
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

    def order_link(self, obj):
        if not obj.related_order_id:
            return '-'
        url = reverse('admin:bill_serviceorder_change', args=[obj.related_order.id])
        return format_html('<a href="{}">订单#{}</a>', url, obj.related_order.id)

    order_link.short_description = '关联订单'

    def pet_display(self, obj):
        pet = obj.pet
        if pet:
            url = reverse('admin:pet_pet_change', args=[pet.id])
            return format_html('<a href="{}">{}</a>', url, pet.name or '未命名宠物')
        return '-'

    pet_display.short_description = '宠物'

    def provider_display(self, obj):
        provider = obj.service_provider
        if provider:
            url = reverse('admin:user_user_change', args=[provider.id])
            return format_html('<a href="{}">{}</a>', url, provider.username)
        return '-'

    provider_display.short_description = '服务提供者'

    def service_date(self, obj):
        if obj.actual_start_time:
            return obj.actual_start_time.strftime('%Y-%m-%d')
        return '-'

    service_date.short_description = '服务日期'

    def actual_duration_display(self, obj):
        if obj.actual_duration:
            hours = obj.actual_duration // 60
            minutes = obj.actual_duration % 60
            return f'{hours}小时{minutes}分钟' if hours else f'{minutes}分钟'
        return '-'

    actual_duration_display.short_description = '实际时长'

    def rating_display(self, obj):
        if obj.rating:
            return format_html('<span title="{}/5">{}</span>', obj.rating, '⭐' * obj.rating)
        return format_html('<span style="color:#999;">未评分</span>')

    rating_display.short_description = '评分'

    def has_feedback(self, obj):
        return '✓' if obj.customer_feedback else '✗'

    has_feedback.short_description = '客户反馈'