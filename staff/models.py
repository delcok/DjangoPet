from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator

class Staff(models.Model):
    username = models.CharField(max_length=30, verbose_name='用户名', blank=True)
    avatar = models.URLField(blank=True, null=True)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="手机号格式不正确")
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, verbose_name='手机号')
    gender = models.CharField(max_length=10, choices=[('M', '男'), ('F', '女'), ('U', '未知')], default='U',
                              verbose_name='性别')
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
    created_at = models.DateTimeField(default=timezone.now)  # 自动创建时间
    updated_at = models.DateTimeField(auto_now=True)