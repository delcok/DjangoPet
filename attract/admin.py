from django.contrib import admin
from .models import HomepagePosition


@admin.register(HomepagePosition)
class HomepagePositionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'position', 'target_type', 'target_id',
        'sort_order', 'is_active', 'updated_at',
    ]
    list_filter = ['position', 'target_type', 'is_active']
    search_fields = ['target_id']
    list_editable = ['sort_order', 'is_active']
    ordering = ['position', '-sort_order']
    list_per_page = 50
