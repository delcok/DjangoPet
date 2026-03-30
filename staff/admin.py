from django import forms
from django.contrib import admin
from .models import Staff


class StaffCreationForm(forms.ModelForm):
    """新增管理员时使用的表单 —— 明文输入密码"""
    password = forms.CharField(
        label='密码',
        widget=forms.PasswordInput,
        required=True,
    )

    class Meta:
        model = Staff
        fields = '__all__'

    def save(self, commit=True):
        staff = super().save(commit=False)
        staff.set_password(self.cleaned_data['password'])
        if commit:
            # 直接调用 models.Model.save 跳过 Staff.save 里的二次加密
            super(Staff, staff).save()
        return staff


class StaffChangeForm(forms.ModelForm):
    """
    编辑管理员时使用的表单
    密码字段留空表示不修改，填写则重新加密
    """
    password = forms.CharField(
        label='密码',
        widget=forms.PasswordInput,
        required=False,
        help_text='留空则不修改密码',
    )

    class Meta:
        model = Staff
        fields = '__all__'

    def save(self, commit=True):
        staff = super().save(commit=False)
        raw_pw = self.cleaned_data.get('password')
        if raw_pw:
            staff.set_password(raw_pw)
        else:
            # 密码留空 → 保持数据库中原来的值
            if staff.pk:
                staff.password = Staff.objects.values_list('password', flat=True).get(pk=staff.pk)
        if commit:
            super(Staff, staff).save()
        return staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm

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

    # 搜索框
    search_fields = ("username", "phone", "openid", "unionid")

    # 默认排序
    ordering = ("-created_at",)

    # 列表页内联编辑
    list_editable = ("is_active", "is_worked")

    list_per_page = 25

    date_hierarchy = "created_at"

    readonly_fields = ("created_at", "updated_at", "last_login")

    # 编辑页字段分组
    fieldsets = (
        ("基础信息", {
            "fields": ("username", "password", "avatar", "phone", "gender", "birth_date")
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

    # 新增页字段
    add_fieldsets = (
        (None, {
            "fields": ("username", "password", "phone", "gender", "birth_date", "is_active", "is_worked")
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """新增时用 add_form，编辑时用 form"""
        if obj is None:
            kwargs['form'] = self.add_form
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        """新增时用 add_fieldsets"""
        if obj is None and self.add_fieldsets:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    @admin.display(description="性别")
    def gender_display(self, obj):
        return obj.get_gender_display()