# 只修改这两个配置

list_display = [
    'id',
    'avatar_preview',
    'username',
    'phone',
    'gender_display',
    'age_display',
    'integral_display',
    'is_worked_badge',  # 保留美化显示
    'is_active_badge',  # 保留美化显示
    'orders_count',
    'last_login_display',
    'created_at',
]

# 移除 list_editable 或者设为空
list_editable = []