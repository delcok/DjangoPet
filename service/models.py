from django.db import models
from django.core.validators import MinValueValidator


class ServiceModel(models.Model):
    """基础服务模型"""
    name = models.CharField(max_length=50, verbose_name='服务类型', unique=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='基础价格',
        validators=[MinValueValidator(0)]
    )
    icon = models.URLField(blank=True, verbose_name='图标地址')
    description = models.TextField(blank=True, verbose_name='服务描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '基础服务'
        verbose_name_plural = '基础服务'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - ¥{self.base_price}"


class PetType(models.Model):
    """宠物类型"""
    name = models.CharField(max_length=50, verbose_name='宠物类型', unique=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='基础上门价格',
        validators=[MinValueValidator(0)]
    )
    description = models.TextField(blank=True, verbose_name='类型描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '宠物类型'
        verbose_name_plural = '宠物类型'
        ordering = ['name']

    def __str__(self):
        return self.name


class AdditionalService(models.Model):
    """附加服务"""
    name = models.CharField(max_length=100, verbose_name='服务名称', unique=True)
    description = models.TextField(blank=True, verbose_name='服务描述')
    icon = models.URLField(blank=True, verbose_name='图标地址')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='服务价格',
        validators=[MinValueValidator(0)]
    )
    applicable_pets = models.ManyToManyField(
        PetType,
        verbose_name='适用宠物类型',
        blank=True
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '附加服务'
        verbose_name_plural = '附加服务'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - ¥{self.price}"

    def get_applicable_pets_display(self):
        """获取适用宠物类型的显示字符串"""
        return ", ".join([pet.name for pet in self.applicable_pets.all()])