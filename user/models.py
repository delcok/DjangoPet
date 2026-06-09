from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.hashers import make_password, check_password


# ============================================================
# 1. 用户
# ============================================================
class User(models.Model):
    """
    用户模型类，存储用户相关信息。

    重构说明：
    - 金币 / 积分已迁出到 UserWallet（gold / integral 字段已删除）
    - 地址已迁出到独立的 address app（UserAddress 已删除）
    - openid / unionid 已迁出到 UserAuthProvider（字段已删除，登录只认 provider）
    - 新增字段全部带默认值，迁移不会触发回填阻塞
    - 三方登录全部走 UserAuthProvider（微信 / Apple / 支付宝统一）
    """

    GENDER_CHOICES = [
        ('M', '男'),
        ('F', '女'),
        ('O', '其他'),
        ('U', '未设置'),
    ]

    # 注册渠道（新增）
    CHANNEL_CHOICES = [
        ('wx_mini', '微信小程序'),
        ('ios',     'iOS App'),
        ('android', 'Android App'),
        ('h5',      'H5页面'),
        ('admin',   '后台创建'),
    ]

    # ---------- 基础信息 ----------
    username = models.CharField(max_length=30, verbose_name='用户名', blank=True)
    avatar = models.URLField(max_length=500, blank=True, default="", verbose_name="头像")
    bio = models.CharField(max_length=200, blank=True, default="", verbose_name="个人简介")

    # ---------- 联系方式 ----------
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="手机号格式不正确")
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, verbose_name='手机号')
    email = models.EmailField(max_length=254, blank=True, verbose_name='邮箱', null=True)

    # ---------- 个人信息 ----------
    gender = models.CharField(
        max_length=1, choices=GENDER_CHOICES,
        default='U', verbose_name="性别"
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name='出生日期')

    # ---------- 密码（小程序阶段可为空，App 阶段引导设置） ----------
    _password = models.CharField(
        max_length=128, blank=True, default="",
        db_column='password',
        verbose_name="密码"
    )

    # ---------- VIP相关 ----------
    is_vip = models.BooleanField(default=False, verbose_name='VIP用户')
    vip_level = models.IntegerField(default=0, verbose_name='VIP等级')
    vip_expired_at = models.DateTimeField(null=True, blank=True, verbose_name='VIP到期时间')

    # ---------- 社交统计 ----------
    followers_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="粉丝数")
    following_count = models.PositiveIntegerField(default=0, verbose_name="关注数")
    posts_count = models.PositiveIntegerField(default=0, verbose_name="帖子数")
    likes_received = models.PositiveIntegerField(default=0, verbose_name="获赞数")

    # ---------- 认证信息 ----------
    is_verified = models.BooleanField(default=False, db_index=True, verbose_name="是否认证")
    verification_type = models.CharField(max_length=50, blank=True, default="", verbose_name="认证类型")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="认证时间")

    # ---------- 用户等级系统 ----------
    level = models.PositiveSmallIntegerField(default=1, verbose_name="用户等级")
    exp = models.PositiveIntegerField(default=0, verbose_name="经验值")

    # 金币 / 积分已迁至 UserWallet（gold_balance / points_balance），此处不再保留

    # ---------- 隐私设置 ----------
    is_public = models.BooleanField(default=True, verbose_name="公开资料")
    allow_message = models.BooleanField(default=True, verbose_name="允许私信")

    # ---------- 注册来源 / 邀请（新增） ----------
    register_channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES,
        default='wx_mini', db_index=True,
        verbose_name="注册渠道"
    )
    invite_code = models.CharField(
        max_length=20, blank=True, default="",
        verbose_name="邀请码"
    )
    invited_by = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='invited_users',
        verbose_name="邀请人"
    )

    # ---------- 状态相关（is_banned / ban_reason 新增） ----------
    is_active = models.BooleanField(default=True, verbose_name='用户状态')
    is_banned = models.BooleanField(default=False, verbose_name='是否封禁')
    ban_reason = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="封禁原因"
    )
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    last_active_at = models.DateTimeField(null=True, blank=True, verbose_name="最后活跃时间")

    # ---------- 时间戳 ----------
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['is_verified', '-followers_count']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_active_at']),
            models.Index(fields=['register_channel', 'created_at']),
        ]

    def __str__(self):
        return self.username or self.phone

    # ---------- 密码相关 ----------
    def set_password(self, raw_password):
        """使用 Django 哈希体系加密存储"""
        self._password = make_password(raw_password)

    def check_password(self, raw_password):
        """校验密码"""
        return check_password(raw_password, self._password)

    @property
    def has_password(self):
        """是否已设置密码（小程序迁移 App 时判断）"""
        return bool(self._password)

    # ---------- Django 认证兼容 ----------
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    # ---------- 业务方法 ----------
    @property
    def display_name(self):
        """获取显示名称"""
        return self.username or f"用户{self.phone[-4:]}"

    @property
    def is_complete_profile(self):
        """检查资料是否完整"""
        return bool(self.avatar and self.bio)

    def update_last_active(self):
        """更新最后活跃时间"""
        self.last_active_at = timezone.now()
        self.save(update_fields=['last_active_at'])


# ============================================================
# 3. 三方登录绑定（新增表，未来 Apple/支付宝/抖音 全走这里）
# ============================================================
class UserAuthProvider(models.Model):
    """
    三方登录绑定表（登录的唯一凭证来源）。
    线上策略：
    - 微信小程序登录只认这张表（openid 存 provider_uid，unionid 存 union_id）
    - 新渠道（Apple / 支付宝 / 抖音）同样只写这张表，User 表不随渠道膨胀
    """

    PROVIDER_CHOICES = [
        ('wx_mini', '微信小程序'),
        ('wx_mp',   '微信公众号'),
        ('wx_app',  '微信开放平台(App)'),
        ('apple',   'Apple'),
        ('alipay',  '支付宝'),
        ('douyin',  '抖音'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='auth_providers', verbose_name='用户'
    )
    provider = models.CharField(
        max_length=20, choices=PROVIDER_CHOICES, verbose_name='登录渠道'
    )
    # 该渠道下的唯一标识（openid / apple sub / alipay uid）
    provider_uid = models.CharField(max_length=128, verbose_name='渠道用户标识')
    # 微信体系的 UnionID（跨小程序/公众号/App 打通）
    union_id = models.CharField(
        max_length=128, blank=True, default="",
        db_index=True, verbose_name='UnionID'
    )

    extra_data = models.JSONField(
        null=True, blank=True, verbose_name='渠道额外信息'
    )

    access_token = models.TextField(blank=True, default="", verbose_name='Access Token')
    refresh_token = models.TextField(blank=True, default="", verbose_name='Refresh Token')
    token_expires_at = models.DateTimeField(null=True, blank=True, verbose_name='Token 过期时间')

    created_at = models.DateTimeField(default=timezone.now, verbose_name='绑定时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_auth_providers'
        verbose_name = '三方登录绑定'
        verbose_name_plural = '三方登录绑定'
        unique_together = ['provider', 'provider_uid']
        indexes = [
            models.Index(fields=['user', 'provider']),
            models.Index(fields=['union_id']),
        ]

    def __str__(self):
        return f"{self.user.username or self.user.phone} - {self.get_provider_display()}"


# ============================================================
# 4. 用户设备（新增表，多端埋点用）
# ============================================================
class UserDevice(models.Model):
    """用户设备记录 —— 为移动端迁移做数据埋点"""

    PLATFORM_CHOICES = [
        ('wx_mini', '微信小程序'),
        ('ios',     'iOS'),
        ('android', 'Android'),
        ('h5',      'H5'),
        ('web',     'Web'),
    ]

    PUSH_CHANNEL_CHOICES = [
        ('apns',   'APNs'),
        ('fcm',    'FCM'),
        ('jpush',  '极光推送'),
        ('huawei', '华为推送'),
        ('xiaomi', '小米推送'),
        ('oppo',   'OPPO推送'),
        ('vivo',   'vivo推送'),
        ('wx',     '微信订阅消息'),
        ('none',   '无'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='devices', verbose_name='用户'
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, verbose_name='平台')

    device_id = models.CharField(
        max_length=128, blank=True, default="",
        verbose_name='设备唯一标识',
        help_text='iOS: IDFV / Android: ANDROID_ID / 小程序: 自生成'
    )
    push_token = models.CharField(
        max_length=256, blank=True, default="", verbose_name='推送Token'
    )
    push_channel = models.CharField(
        max_length=20, choices=PUSH_CHANNEL_CHOICES,
        default='none', verbose_name='推送通道'
    )

    device_brand = models.CharField(
        max_length=30, blank=True, default="", verbose_name='设备品牌'
    )
    device_model = models.CharField(max_length=100, blank=True, default="", verbose_name='设备型号')
    os_version = models.CharField(max_length=30, blank=True, default="", verbose_name='系统版本')
    app_version = models.CharField(max_length=20, blank=True, default="", verbose_name='应用版本')
    wx_sdk_version = models.CharField(
        max_length=20, blank=True, default="", verbose_name='小程序基础库版本'
    )
    screen_width = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='屏幕宽度')
    screen_height = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='屏幕高度')
    network_type = models.CharField(max_length=20, blank=True, default="", verbose_name='网络类型')

    channel = models.CharField(
        max_length=50, blank=True, default="",
        verbose_name='下载渠道',
        help_text='如 appstore / huawei / xiaomi / oppo / vivo / 应用宝'
    )
    campaign = models.CharField(max_length=50, blank=True, default="", verbose_name='推广活动标识')

    is_active = models.BooleanField(default=True, verbose_name='是否活跃')
    last_active_at = models.DateTimeField(null=True, blank=True, verbose_name='最后活跃时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='首次记录时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_devices'
        verbose_name = '用户设备'
        verbose_name_plural = '用户设备'
        unique_together = ['user', 'device_id']
        indexes = [
            models.Index(fields=['user', 'platform']),
            models.Index(fields=['platform', 'last_active_at']),
            models.Index(fields=['channel']),
        ]

    def __str__(self):
        return f"{self.user.username or self.user.phone} - {self.get_platform_display()} - {self.device_model}"


# ============================================================
# 5. 用户登录日志（新增表，埋点 + 风控）
# ============================================================
class UserLoginLog(models.Model):
    """登录日志 —— 埋点分析 + 安全风控"""

    LOGIN_METHOD_CHOICES = [
        ('wx_mini',   '微信小程序授权'),
        ('wx_mp',     '微信公众号授权'),
        ('sms',       '短信验证码'),
        ('password',  '密码登录'),
        ('apple',     'Apple 登录'),
        ('one_click', '一键登录'),
        ('alipay',    '支付宝登录'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='login_logs', verbose_name='用户'
    )
    login_method = models.CharField(
        max_length=20, choices=LOGIN_METHOD_CHOICES, verbose_name='登录方式'
    )
    platform = models.CharField(max_length=20, verbose_name='平台')
    device_id = models.CharField(max_length=128, blank=True, default="", verbose_name='设备标识')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP地址')
    location = models.CharField(max_length=100, blank=True, default="", verbose_name='登录地点')
    user_agent = models.TextField(blank=True, default="", verbose_name='User-Agent')

    is_success = models.BooleanField(default=True, verbose_name='是否成功')
    fail_reason = models.CharField(max_length=100, blank=True, default="", verbose_name='失败原因')

    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='登录时间')

    class Meta:
        db_table = 'user_login_logs'
        verbose_name = '登录日志'
        verbose_name_plural = '登录日志'
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['platform', '-created_at']),
            models.Index(fields=['ip_address']),
        ]

    def __str__(self):
        status = "成功" if self.is_success else "失败"
        return f"{self.user.username or self.user.phone} {self.get_login_method_display()} {status}"


# ============================================================
# 6. 邀请奖励记录（新增表）
# ============================================================
class InviteReward(models.Model):
    """
    邀请奖励发放记录
    - 每条 = 邀请人因某个被邀请人触发的一次奖励
    - (inviter, invitee) 唯一约束防重复发放
    """

    STATUS_CHOICES = [
        ('pending',  '待发放'),
        ('issued',   '已发放'),
        ('reversed', '已撤销'),
    ]

    inviter = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invite_rewards_as_inviter',
        verbose_name='邀请人',
    )
    invitee = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invite_rewards_as_invitee',
        verbose_name='被邀请人',
    )
    reward_gold = models.PositiveIntegerField(default=100, verbose_name='奖励金币')
    # ★ 新增：被邀请人(新用户)注册奖励
    invitee_reward_gold = models.PositiveIntegerField(default=0, verbose_name='被邀请人奖励金币')
    invitee_business_no = models.CharField(
        max_length=64, blank=True, default='', verbose_name='被邀请人钱包流水号',
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default='issued', db_index=True, verbose_name='发放状态',
    )
    business_no = models.CharField(max_length=64, blank=True, default='', verbose_name='钱包流水号')
    remark = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')
    issued_at = models.DateTimeField(null=True, blank=True, verbose_name='发放时间')
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='创建时间')

    class Meta:
        db_table = 'user_invite_rewards'
        verbose_name = '邀请奖励'
        verbose_name_plural = '邀请奖励'
        unique_together = ['inviter', 'invitee']
        indexes = [
            models.Index(fields=['inviter', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.inviter_id} 邀请 {self.invitee_id} +{self.reward_gold}'

class UserProfileAudit(models.Model):
    """
    用户资料修改审核（头像 / 昵称）
    - 用户提交的新头像/昵称先进这张表，status=pending
    - 管理员审核通过(approve) → 写回 User 的真实字段
    - 驳回(reject) → 不动用户资料，记录原因
    - 约定：每个 (user, field) 同时最多一条 pending 记录
    """

    class Field(models.TextChoices):
        USERNAME = 'username', '昵称'
        AVATAR   = 'avatar',   '头像'

    class Status(models.TextChoices):
        PENDING  = 'pending',  '待审核'
        APPROVED = 'approved', '已通过'
        REJECTED = 'rejected', '已驳回'

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='profile_audits', verbose_name='用户'
    )
    field = models.CharField(max_length=20, choices=Field.choices, verbose_name='字段')
    old_value = models.TextField(blank=True, default='', verbose_name='原值')
    new_value = models.TextField(blank=True, default='', verbose_name='新值(待审核)')
    status = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.PENDING, db_index=True, verbose_name='审核状态'
    )

    reviewer_id = models.IntegerField(null=True, blank=True, verbose_name='审核管理员ID')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='审核时间')
    reject_reason = models.CharField(max_length=200, blank=True, default='', verbose_name='驳回原因')

    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='提交时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_profile_audits'
        verbose_name = '资料审核'
        verbose_name_plural = '资料审核'
        indexes = [
            models.Index(fields=['user', 'field', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user_id} {self.get_field_display()} {self.get_status_display()}'