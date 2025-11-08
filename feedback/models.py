from django.db import models

from user.models import User


class Feedback(models.Model):
    """用户反馈（建议/吐槽）"""

    TYPE_CHOICES = [
        ('suggestion', '建议'),
        ('complaint', '吐槽'),
    ]

    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('resolved', '已解决'),
        ('closed', '已关闭'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                             verbose_name='提交用户')
    feedback_type = models.CharField('类型', max_length=20, choices=TYPE_CHOICES, default='suggestion')
    content = models.TextField('反馈内容', max_length=1000)
    contact_info = models.CharField('联系方式', max_length=100, blank=True)
    status = models.CharField('处理状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    reply = models.TextField('回复内容', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'feedback'
        verbose_name = '用户反馈'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_feedback_type_display()} - {self.content[:20]}"