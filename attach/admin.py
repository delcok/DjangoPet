from django.contrib import admin
from attach.models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'type', 'sort_order', 'is_active', 'created_at']
    list_filter = ['type', 'is_active', 'created_at']
    list_editable = ['sort_order', 'is_active']
    search_fields = ['title', 'description']
    ordering = ['type', 'sort_order']

    fieldsets = (
        ('基本信息', {
            'fields': ('type', 'title', 'description')
        }),
        ('链接设置', {
            'fields': ('url', 'link')
        }),
        ('显示设置', {
            'fields': ('sort_order', 'is_active')
        }),
    )

    def get_queryset(self, request):
        # 管理后台显示所有轮播图（包括已禁用的）
        return Banner.objects.all()

