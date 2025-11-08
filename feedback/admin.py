from django.contrib import admin
from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'feedback_type', 'content_preview', 'status', 'created_at']
    list_filter = ['feedback_type', 'status', 'created_at']
    search_fields = ['content', 'contact_info', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 20

    fieldsets = [
        ('基本信息', {
            'fields': ['user', 'feedback_type', 'content', 'contact_info']
        }),
        ('处理信息', {
            'fields': ['status', 'reply']
        }),
        ('时间信息', {
            'fields': ['created_at', 'updated_at']
        }),
    ]

    def content_preview(self, obj):
        return obj.content[:30] + '...' if len(obj.content) > 30 else obj.content

    content_preview.short_description = '内容预览'