from django.db import models

class Banner(models.Model):
    """轮播图模型"""
    TYPE_CHOICES = [
        ('home', '首页轮播'),
        ('community', '社区轮播'),
        ('service', '服务轮播'),
    ]

    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='home',
        verbose_name='轮播图类型',
        help_text='用于区分不同页面的轮播图'
    )
    url = models.URLField(verbose_name='图片链接', help_text='轮播图图片地址')
    link = models.URLField(
        blank=True,
        null=True,
        verbose_name='跳转链接',
        help_text='点击轮播图后跳转的链接，可以是内部路由或外部链接'
    )
    title = models.CharField(max_length=100, blank=True, null=True, verbose_name='标题')
    description = models.TextField(blank=True, verbose_name='描述')
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name='排序',
        help_text='数字越小越靠前显示'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'banner'
        verbose_name = '轮播图'
        verbose_name_plural = '轮播图'
        ordering = ['sort_order', 'created_at']
        indexes = [
            models.Index(fields=['type', 'is_active']),
            models.Index(fields=['sort_order']),
        ]

    def __str__(self):
        return f'{self.get_type_display()} - {self.title or self.id}'

