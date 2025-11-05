from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.hashers import make_password, check_password

# 用户字段
class User(models.Model):
    """
    用户模型类，存储用户相关信息。
    """

    GENDER_CHOICES = [
        ('M', '男'),
        ('F', '女'),
        ('O', '其他'),
        ('U', '未设置'),
    ]
    # 基础信息
    username = models.CharField(max_length=30, verbose_name='用户名', blank=True)
    avatar = models.URLField(max_length=500, blank=True, default="", verbose_name="头像")
    bio = models.CharField(max_length=200, blank=True, default="", verbose_name="个人简介")

    # 联系方式
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="手机号格式不正确")
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, verbose_name='手机号')
    email = models.EmailField(max_length=254, blank=True, verbose_name='邮箱', null=True)

    # 个人信息
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        default='U',
        verbose_name="性别"
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name='出生日期')

    # 微信相关
    openid = models.CharField(max_length=128, blank=True, null=True, verbose_name="微信小程序用户唯一标识符")
    unionid = models.CharField(max_length=128, blank=True, null=True, verbose_name="微信标识符")

    # VIP相关
    is_vip = models.BooleanField(default=False, verbose_name='VIP用户')
    vip_level = models.IntegerField(default=0, verbose_name='VIP等级')
    vip_expired_at = models.DateTimeField(null=True, blank=True, verbose_name='VIP到期时间')

    # 社交统计
    followers_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="粉丝数")
    following_count = models.PositiveIntegerField(default=0, verbose_name="关注数")
    posts_count = models.PositiveIntegerField(default=0, verbose_name="帖子数")
    likes_received = models.PositiveIntegerField(default=0, verbose_name="获赞数")

    # 认证信息
    is_verified = models.BooleanField(default=False, db_index=True, verbose_name="是否认证")
    verification_type = models.CharField(max_length=50, blank=True, default="", verbose_name="认证类型")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="认证时间")

    # 用户等级系统
    level = models.PositiveSmallIntegerField(default=1, verbose_name="用户等级")
    exp = models.PositiveIntegerField(default=0, verbose_name="经验值")

    # 积分金币系统
    integral = models.IntegerField(default=0, verbose_name='积分')
    gold = models.IntegerField(default=0, verbose_name='金币')

    # 隐私设置
    is_public = models.BooleanField(default=True, verbose_name="公开资料")
    allow_message = models.BooleanField(default=True, verbose_name="允许私信")

    # 状态相关
    is_active = models.BooleanField(default=True, verbose_name='用户状态')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    last_active_at = models.DateTimeField(null=True, blank=True, verbose_name="最后活跃时间")

    # 时间戳
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
        ]

    def __str__(self):
        return self.username or self.phone

    # 添加Django认证系统需要的属性
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    # 新增方法
    @property
    def display_name(self):
        """获取显示名称"""
        return  self.username or f"用户{self.phone[-4:]}"

    @property
    def is_complete_profile(self):
        """检查资料是否完整"""
        return bool(self.avatar and self.bio)

    def update_last_active(self):
        """更新最后活跃时间"""
        self.last_active_at = timezone.now()
        self.save(update_fields=['last_active_at'])

# 用户地址字段
class UserAddress(models.Model):
    """
    用户收货地址模型类，存储用户收货地址相关信息。
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses', verbose_name='用户')
    receiver_name = models.CharField(max_length=30, verbose_name='收货人姓名')
    receiver_phone = models.CharField(max_length=17, verbose_name='收货人电话')
    # 地址信息
    province = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    city = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    district = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    detail_address = models.CharField(max_length=200, verbose_name='详细地址')

    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='经度'
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='纬度'
    )
    access_instructions = models.TextField(
        blank=True, null=True,
        verbose_name='入户说明'
    )

    is_default = models.BooleanField(default=False, verbose_name='默认地址')
    tag = models.CharField(max_length=20, blank=True, verbose_name='地址标签', null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_addresses'
        verbose_name = '用户地址'
        verbose_name_plural = '用户地址'

    def __str__(self):
        return f"{self.user.username}-{self.receiver_name}-{self.detail_address}"

# 超级管理员模型
class SuperAdmin(models.Model):
    """
    超级管理员模型
    """
    username = models.CharField(max_length=50, unique=True, verbose_name='用户名')
    password = models.CharField(max_length=128, verbose_name='密码')
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="手机号格式不正确")
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, verbose_name='手机号')
    is_active = models.BooleanField(default=True, verbose_name='是否激活')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'super_admins'
        verbose_name = '超级管理员'
        verbose_name_plural = '超级管理员'

    def __str__(self):
        return self.username

    def set_password(self, raw_password):
        """设置密码"""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """验证密码"""
        return check_password(raw_password, self.password)

    # 添加Django认证系统需要的属性
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


