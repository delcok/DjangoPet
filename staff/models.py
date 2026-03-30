from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.hashers import make_password, check_password


class Staff(models.Model):
    username = models.CharField(max_length=30, verbose_name='用户名', blank=True)
    password = models.CharField(max_length=128, verbose_name='密码')
    avatar = models.URLField(blank=True, null=True)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="手机号格式不正确")
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, verbose_name='手机号')
    gender = models.CharField(
        max_length=10,
        choices=[('M', '男'), ('F', '女'), ('U', '未知')],
        default='M',
        verbose_name='性别',
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name='出生日期')

    # 微信小程序用户唯一标识符
    openid = models.CharField(max_length=128, blank=True, null=True)
    # 微信标识符
    unionid = models.CharField(max_length=128, blank=True, null=True)
    # 积分
    integral = models.IntegerField(default=0, verbose_name='积分')

    is_active = models.BooleanField(default=True, verbose_name='用户状态')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')

    is_worked = models.BooleanField(default=False, verbose_name='是否工作')

    # 时间戳
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '管理员'
        verbose_name_plural = '管理员'

    def __str__(self):
        return self.username or self.phone

    # ---- 密码相关方法 ----

    def set_password(self, raw_password):
        """用 Django 自带的 hasher 加密并保存密码"""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """校验明文密码是否匹配"""
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """
        保存前自动检测：如果 password 不是以 hash 算法前缀开头，
        说明是明文密码，自动加密。
        这样无论是代码里直接赋值还是 admin 后台修改都能正确加密。
        """
        if self.password and not self.password.startswith(('pbkdf2_sha256$', 'bcrypt', 'argon2')):
            self.set_password(self.password)
        super().save(*args, **kwargs)

    # ---- 兼容 DRF / SimpleJWT 所需的属性 ----

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    # SimpleJWT 的 for_user() 需要 pk
    @property
    def pk(self):
        return self.id