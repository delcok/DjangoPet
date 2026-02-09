from django.contrib import admin
from .models import Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    # 列表页显示哪些列
    list_display = (
        "id",
        "username",
        "phone",
        "gender",
        "birth_date",
        "integral",
        "is_active",
        "is_worked",
        "last_login",
        "created_at",
        "updated_at",
    )

    # 右侧筛选器
    list_filter = ("gender", "is_active", "is_worked", "created_at", "updated_at")

    # 搜索框（支持模糊搜索）
    search_fields = ("username", "phone", "openid", "unionid")

    # 默认排序（- 代表倒序）
    ordering = ("-created_at",)

    # 表单页可直接编辑的字段（列表页内联编辑）
    list_editable = ("is_active", "is_worked")

    # 分页每页多少条
    list_per_page = 25

    # 日期层级导航
    date_hierarchy = "created_at"

    # 表单页：只读字段（建议把时间戳设为只读）
    readonly_fields = ("created_at", "updated_at", "last_login")

    # 表单页字段分组（更清晰）
    fieldsets = (
        ("基础信息", {
            "fields": ("username", "avatar", "phone", "gender", "birth_date")
        }),
        ("微信信息", {
            "fields": ("openid", "unionid"),
            "classes": ("collapse",),
        }),
        ("状态与积分", {
            "fields": ("integral", "is_active", "is_worked", "last_login")
        }),
        ("时间戳", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # 新增页默认展示的字段顺序（可选）
    add_fieldsets = (
        (None, {
            "fields": ("username", "phone", "gender", "birth_date", "is_active", "is_worked")
        }),
    )

    # 性别显示为中文 label（男/女/未知）
    @admin.display(description="性别")
    def gender_display(self, obj):
        return obj.get_gender_display()
