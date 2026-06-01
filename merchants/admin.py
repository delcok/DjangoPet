# merchants/admin.py
"""
商家模块 Django Admin 配置
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.hashers import make_password, identify_hasher
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe

from .models import Merchant, MerchantCategory, BusinessDistrict, MerchantSubAccount


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────
def _is_hashed(password: str) -> bool:
    """判断密码字符串是否已经是 Django 识别的哈希格式"""
    if not password:
        return False
    try:
        identify_hasher(password)
        return True
    except ValueError:
        return False


# ─────────────────────────────────────────────────────────────
# 商家分类
# ─────────────────────────────────────────────────────────────
@admin.register(MerchantCategory)
class MerchantCategoryAdmin(admin.ModelAdmin):
    """商家分类管理"""
    list_display = ['id', 'name', 'icon_preview', 'sort_order', 'commission_rate',
                    'is_active', 'merchant_count', 'created_at']
    list_display_links = ['id', 'name']
    list_editable = ['sort_order', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    ordering = ['sort_order', 'id']

    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<img src="{}" width="30" height="30" />', obj.icon)
        return '-'
    icon_preview.short_description = '图标'

    def merchant_count(self, obj):
        return obj.merchants.count()
    merchant_count.short_description = '商家数'


# ─────────────────────────────────────────────────────────────
# 商圈
# ─────────────────────────────────────────────────────────────
@admin.register(BusinessDistrict)
class BusinessDistrictAdmin(admin.ModelAdmin):
    """商圈管理"""
    list_display = ['id', 'name', 'province', 'city', 'district', 'heat_score',
                    'radius', 'sort_order', 'is_active', 'merchant_count']
    list_display_links = ['id', 'name']
    list_editable = ['sort_order', 'is_active', 'heat_score']
    list_filter = ['province', 'city', 'district', 'is_active']
    search_fields = ['name', 'province', 'city', 'district', 'address']
    ordering = ['sort_order', '-heat_score']

    fieldsets = (
        ('基本信息', {'fields': ('name',)}),
        ('省市区', {
            'fields': ('province', 'city', 'district', 'address'),
            'description': '商圈所在的省市区信息'
        }),
        ('位置信息', {'fields': ('longitude', 'latitude', 'radius', 'boundary')}),
        ('排序与状态', {'fields': ('heat_score', 'sort_order', 'is_active')}),
    )

    def merchant_count(self, obj):
        return obj.merchants.filter(status='active').count()
    merchant_count.short_description = '商家数'


# ─────────────────────────────────────────────────────────────
# 商家 —— 带密码哈希处理
# ─────────────────────────────────────────────────────────────
class MerchantAdminForm(forms.ModelForm):
    """
    商家后台表单
    通过虚拟字段 raw_password 接收明文密码,
    save_model() 里统一哈希后写入真正的 password 字段。
    """
    raw_password = forms.CharField(
        label='登录密码',
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={'autocomplete': 'new-password', 'style': 'width: 320px;'}
        ),
        help_text='新建商家必填;编辑时留空表示不修改密码。',
    )

    class Meta:
        model = Merchant
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        # 新建时必须填密码
        if not self.instance.pk and not cleaned.get('raw_password'):
            self.add_error('raw_password', '新建商家必须设置登录密码')
        return cleaned


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    """商家管理"""
    form = MerchantAdminForm

    list_display = [
        'id', 'name', 'logo_preview', 'phone', 'category',
        'status_badge', 'is_open',
        # ✅ 配送方式徽章列(一眼可见配送/自提开关 + 计费方式)
        'delivery_badge',
        'rating', 'monthly_sales',
        'is_recommended', 'created_at',
    ]
    list_display_links = ['id', 'name']
    list_editable = ['is_open', 'is_recommended']
    list_filter = [
        'status', 'is_open', 'is_recommended', 'category',
        # ✅ 配送相关筛选
        'support_home_delivery', 'support_self_pickup', 'freight_mode',
        'pickup_discount_type',
        'business_district', 'created_at',
    ]
    search_fields = ['name', 'phone', 'contact_name', 'address']
    raw_id_fields = ['category', 'business_district']
    readonly_fields = [
        'password', 'token_version', 'created_at', 'updated_at', 'last_login',
        # ✅ 配送配置概览(只读、展示完整配送策略)
        'delivery_config_overview',
    ]
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'logo', 'images', 'description', 'announcement')
        }),
        ('分类与商圈', {
            'fields': ('category', 'business_district')
        }),
        ('登录信息', {
            'fields': ('phone', 'raw_password', 'password',
                       'token_version', 'last_login'),
            'description': '在「登录密码」中输入明文,保存时会自动加密。',
        }),
        ('联系信息', {
            'fields': ('contact_name', 'contact_phone')
        }),
        ('地址信息', {
            'fields': ('province', 'city', 'district', 'address',
                       'longitude', 'latitude'),
            'description': '此处填写的地址同时也是「到店自提」的取货点。',
        }),
        ('营业信息', {
            'fields': ('business_hours', 'is_open')
        }),

        # ✅ 配送配置 — 三段式:总开关 + 配送 + 自提
        ('配送配置 — 总开关', {
            'fields': (
                'delivery_config_overview',
                'support_home_delivery', 'support_self_pickup',
            ),
            'description': (
                '<b>商家级配送方式开关</b>(至少需要开启一项,否则商家无法接单):<br>'
                '• <b>support_home_delivery</b> 关闭后,所有商品都不能配送<br>'
                '• <b>support_self_pickup</b> 关闭后,所有商品都不能自提<br>'
                '注:商品级 <code>allow_delivery/allow_pickup</code> 在商家级关闭时不生效'
            ),
        }),
        ('配送配置 — 配送上门(home_delivery)', {
            'fields': (
                'freight_mode',
                'delivery_fee', 'min_order_amount',
                'free_delivery_threshold',
                'delivery_range',
                'distance_rules',
            ),
            'description': (
                '<b>计费方式 freight_mode</b>:<br>'
                '• <code>free</code> 全店包邮<br>'
                '• <code>flat</code> 统一运费 = delivery_fee<br>'
                '• <code>distance</code> 按距离阶梯,需配置 distance_rules,'
                '例如 <code>[{"max_km":3,"fee":5},{"max_km":10,"fee":10},{"max_km":null,"fee":20}]</code>,'
                'max_km=null 表示该档之外的兜底<br>'
                '<b>delivery_range</b>:配送范围(<b>米</b>),0 = 未配置/拒绝配送<br>'
                '<b>free_delivery_threshold</b>:满 X 元免运费,留空 = 不启用'
            ),
        }),
        ('配送配置 — 到店自提(self_pickup)', {
            'fields': (
                'pickup_discount_type', 'pickup_discount_value',
                'pickup_note',
            ),
            'description': (
                '<b>自提优惠 pickup_discount_type</b>:<br>'
                '• <code>none</code> 无优惠(仅免运费)<br>'
                '• <code>amount</code> 立减 X 元(pickup_discount_value)<br>'
                '• <code>percent</code> 按 X% 打折(pickup_discount_value=5 表示 95 折)<br>'
                '<b>自提地址</b>:复用上方「地址信息」中的地址,「联系信息」中的客服电话'
            ),
        }),

        ('评分与销量', {
            'fields': ('rating', 'total_sales', 'monthly_sales'),
            'classes': ('collapse',)
        }),
        ('推荐与排序', {
            'fields': ('is_recommended', 'recommend_sort', 'sort_order')
        }),
        ('资质信息', {
            'fields': ('license_no', 'license_image',
                       'id_card_front', 'id_card_back'),
            'classes': ('collapse',)
        }),
        ('结算信息', {
            'fields': ('bank_name', 'bank_account_name', 'bank_account_no',
                       'commission_rate'),
            'classes': ('collapse',)
        }),
        ('支付信息', {
            'fields': ('wechat_mch_id', 'alipay_pid'),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('status', 'reject_reason',
                       'login_fail_count', 'locked_until')
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # ─── 核心:保存时处理密码 ───
    def save_model(self, request, obj, form, change):
        raw = form.cleaned_data.get('raw_password')

        if raw:
            # 1) 用户填了新密码 → 哈希后写入 + token_version 递增(作废旧 token)
            obj.password = make_password(raw)
            obj.token_version = (obj.token_version or 0) + 1
        else:
            # 2) 没填新密码
            if not change:
                # 新建兜底(clean() 已拦截,理论上不会走到这)
                obj.set_password(obj.password or '')
            elif obj.password and not _is_hashed(obj.password):
                # 老数据是明文,顺手哈希一次
                obj.password = make_password(obj.password)

        super().save_model(request, obj, form, change)

    # ─── 展示辅助 ───
    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" width="40" height="40" style="border-radius:4px;" />',
                obj.logo
            )
        return '-'
    logo_preview.short_description = 'Logo'

    def status_badge(self, obj):
        colors = {
            'pending': '#faad14',
            'active': '#52c41a',
            'suspended': '#ff4d4f',
            'rejected': '#ff4d4f',
            'closed': '#8c8c8c',
        }
        color = colors.get(obj.status, '#8c8c8c')
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = '状态'

    # ─── ✅ 列表里的配送方式徽章 ───
    @admin.display(description='配送方式', ordering='support_home_delivery')
    def delivery_badge(self, obj):
        """
        列表里一眼可见:
        - 两种方式各自的开关状态
        - 配送计费模式(免运费/固定/按距离)
        - 自提优惠类型
        """
        sd = obj.support_home_delivery
        sp = obj.support_self_pickup

        parts = []

        # 主开关徽章 — 纯静态 HTML
        if sd and sp:
            parts.append(
                '<span style="color:#52c41a;font-weight:600">🚚+🏪</span>'
            )
        elif sd and not sp:
            parts.append(
                '<span style="color:#1976d2;font-weight:600">🚚 仅配送</span>'
            )
        elif sp and not sd:
            parts.append(
                '<span style="color:#d4a017;font-weight:600">🏪 仅自提</span>'
            )
        else:
            parts.append(
                '<span style="color:#ff4d4f;font-weight:700">⚠ 都未开启</span>'
            )

        # 计费方式(只在支持配送时显示) — 有插值用 format_html
        if sd:
            mode = (obj.freight_mode or '').lower()
            if mode == 'free':
                color, text = '#52c41a', '全店包邮'
            elif mode == 'flat':
                color, text = '#8c8c8c', f'固定¥{obj.delivery_fee or 0}'
            elif mode == 'distance':
                color, text = '#1976d2', '阶梯'
            else:
                color, text = '#8c8c8c', mode or '?'
            parts.append(str(format_html(
                '<br><span style="font-size:11px;color:{}">运费:{}</span>',
                color, text,
            )))

        # 自提优惠(只在支持自提时显示)
        if sp:
            dtype = (obj.pickup_discount_type or 'none').lower()
            if dtype == 'amount' and obj.pickup_discount_value:
                parts.append(str(format_html(
                    '<br><span style="font-size:11px;color:#d4a017">'
                    '自提:-¥{}</span>',
                    obj.pickup_discount_value,
                )))
            elif dtype == 'percent' and obj.pickup_discount_value:
                parts.append(str(format_html(
                    '<br><span style="font-size:11px;color:#d4a017">'
                    '自提:{}% off</span>',
                    obj.pickup_discount_value,
                )))

        return mark_safe(''.join(parts))

    # ─── ✅ 详情页的"配送配置概览"只读字段 ───
    @admin.display(description='配送配置总览')
    def delivery_config_overview(self, obj):
        """详情页顶部展示当前完整配送策略,方便快速核对"""
        if not obj.pk:
            return mark_safe(
                '<i style="color:#8c8c8c">保存商家后此处显示当前配送策略概览</i>'
            )

        sd = obj.support_home_delivery
        sp = obj.support_self_pickup

        lines = []

        # 行 1:总开关(纯静态 HTML)
        if sd and sp:
            lines.append('<b style="color:#52c41a">✓ 配送+自提均开启</b>')
        elif sd:
            lines.append('<b style="color:#1976d2">仅配送上门</b>')
        elif sp:
            lines.append('<b style="color:#d4a017">仅到店自提</b>')
        else:
            lines.append(
                '<b style="color:#ff4d4f">⚠ 配送/自提都未开启,该商家无法接单</b>'
            )

        # 行 2:运费策略(文本,转义后插入)
        if sd:
            mode = (obj.freight_mode or '').lower()
            if mode == 'free':
                line2 = '运费:全店包邮'
            elif mode == 'flat':
                free_th = obj.free_delivery_threshold
                free_part = (f',满 ¥{free_th} 免运'
                             if free_th and free_th > 0 else '')
                line2 = f'运费:固定 ¥{obj.delivery_fee or 0}{free_part}'
            elif mode == 'distance':
                rules = obj.distance_rules or []
                if rules:
                    INF = 10 ** 9
                    sorted_rules = sorted(
                        rules,
                        key=lambda r: (r.get('max_km')
                                       if r.get('max_km') is not None else INF)
                    )
                    parts_text = []
                    for r in sorted_rules:
                        mk = r.get('max_km')
                        fee = r.get('fee', 0)
                        if mk is None:
                            parts_text.append(f'其余¥{fee}')
                        else:
                            parts_text.append(f'{mk}km内¥{fee}')
                    line2 = f'运费(按距离):{" / ".join(parts_text)}'
                else:
                    line2 = '运费:阶梯模式但未配置 distance_rules'
            else:
                line2 = f'运费:{mode or "未知模式"}'

            if obj.delivery_range and obj.delivery_range > 0:
                # 模型里 delivery_range 单位是米
                line2 += f',配送范围 {obj.delivery_range / 1000:.1f}km'
            else:
                line2 += ',未设置配送范围'

            lines.append(escape(line2))

        # 行 3:自提优惠
        if sp:
            dtype = (obj.pickup_discount_type or 'none').lower()
            if dtype == 'none':
                line3 = '自提:仅免运费,无额外优惠'
            elif dtype == 'amount':
                line3 = f'自提:立减 ¥{obj.pickup_discount_value or 0}'
            elif dtype == 'percent':
                pct = obj.pickup_discount_value or 0
                line3 = f'自提:{pct}% off (即 {Decimal_pct_to_zhe(pct)})'
            else:
                line3 = f'自提:{dtype}'
            lines.append(escape(line3))

        # 行 4:最低订单金额
        if obj.min_order_amount and obj.min_order_amount > 0:
            lines.append(escape(f'起送金额:¥{obj.min_order_amount}'))

        body = '<br>'.join(str(x) for x in lines)
        return mark_safe(
            '<div style="padding:10px 14px;background:#fafafa;'
            'border-left:3px solid #1976d2;border-radius:4px;'
            'line-height:1.8;font-size:13px;">' + body + '</div>'
        )

    # ─── 批量操作 ───
    actions = [
        'approve_merchants', 'suspend_merchants', 'activate_merchants',
        # ✅ 配送相关批量操作
        'enable_self_pickup', 'enable_home_delivery',
    ]

    @admin.action(description='审核通过选中的商家')
    def approve_merchants(self, request, queryset):
        count = queryset.filter(status='pending').update(status='active')
        self.message_user(request, f'已审核通过 {count} 个商家')

    @admin.action(description='暂停选中的商家')
    def suspend_merchants(self, request, queryset):
        count = queryset.filter(status='active').update(status='suspended')
        self.message_user(request, f'已暂停 {count} 个商家')

    @admin.action(description='启用选中的商家')
    def activate_merchants(self, request, queryset):
        count = queryset.filter(status='suspended').update(status='active')
        self.message_user(request, f'已启用 {count} 个商家')

    @admin.action(description='批量开启「到店自提」')
    def enable_self_pickup(self, request, queryset):
        count = queryset.update(support_self_pickup=True)
        self.message_user(request, f'已为 {count} 个商家开启自提')

    @admin.action(description='批量开启「送货上门」')
    def enable_home_delivery(self, request, queryset):
        count = queryset.update(support_home_delivery=True)
        self.message_user(request, f'已为 {count} 个商家开启配送')


def Decimal_pct_to_zhe(pct) -> str:
    """把百分比折扣转成中文"X 折"展示
    pickup_discount_value=5 → "95 折"(打 95% 折,等同 5% off)
    pickup_discount_value=10 → "9 折"
    """
    try:
        p = float(pct)
        zhe = (100 - p) / 10
        # 整数显示整数,小数保留一位
        if zhe == int(zhe):
            return f'{int(zhe)} 折'
        return f'{zhe:.1f} 折'
    except (TypeError, ValueError):
        return f'{pct}% off'


# ─────────────────────────────────────────────────────────────
# 商家子账号 —— 同样加上密码哈希
# ─────────────────────────────────────────────────────────────
class MerchantSubAccountAdminForm(forms.ModelForm):
    raw_password = forms.CharField(
        label='登录密码',
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={'autocomplete': 'new-password', 'style': 'width: 320px;'}
        ),
        help_text='新建必填;编辑时留空表示不修改密码。',
    )

    class Meta:
        model = MerchantSubAccount
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get('raw_password'):
            self.add_error('raw_password', '新建子账号必须设置登录密码')
        return cleaned


@admin.register(MerchantSubAccount)
class MerchantSubAccountAdmin(admin.ModelAdmin):
    """商家子账号管理"""
    form = MerchantSubAccountAdminForm

    list_display = ['id', 'merchant', 'name', 'phone', 'is_active',
                    'last_login', 'created_at']
    list_display_links = ['id', 'name']
    list_editable = ['is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'phone', 'merchant__name']
    raw_id_fields = ['merchant']
    readonly_fields = ['password', 'token_version', 'last_login']

    fieldsets = (
        ('基本信息', {
            'fields': ('merchant', 'name', 'phone', 'permissions', 'is_active')
        }),
        ('登录信息', {
            'fields': ('raw_password', 'password', 'token_version', 'last_login'),
            'description': '在「登录密码」中输入明文,保存时会自动加密。',
        }),
        ('安全', {
            'fields': ('login_fail_count', 'locked_until'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        raw = form.cleaned_data.get('raw_password')
        if raw:
            obj.password = make_password(raw)
            obj.token_version = (obj.token_version or 0) + 1
        elif change and obj.password and not _is_hashed(obj.password):
            obj.password = make_password(obj.password)
        super().save_model(request, obj, form, change)