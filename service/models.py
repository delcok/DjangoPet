# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Delock (Modified by ChatGPT)

from django.db import models
from django.core.validators import MinValueValidator


# ======================== 宠物类型 ========================

class PetType(models.Model):
    """宠物类型"""
    name = models.CharField(max_length=50, verbose_name='宠物类型', unique=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='基础上门价格',
        validators=[MinValueValidator(0)],
        help_text='该类型宠物的基础上门服务费'
    )
    description = models.TextField(blank=True, verbose_name='类型描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用', db_index=True)
    sort_order = models.IntegerField(default=0, verbose_name='排序', help_text='数字越小越靠前')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '宠物类型'
        verbose_name_plural = '宠物类型'
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['is_active', 'sort_order']),
        ]

    def __str__(self):
        return self.name

    def get_services_count(self):
        """获取使用该宠物类型的基础服务数量"""
        return self.services.filter(is_active=True).count()

    def get_additional_services_count(self):
        """获取适用于该宠物类型的附加服务数量"""
        return self.additional_services.filter(is_active=True).count()

    def delete(self, *args, **kwargs):
        """
        删除宠物类型时：
        - 不删除任何服务；
        - 仅清除服务与本宠物类型的关联；
        """
        # 清除与基础服务、附加服务的关联关系
        for service in self.services.all():
            service.applicable_pets.remove(self)

        for addon in self.additional_services.all():
            addon.applicable_pets.remove(self)

        super().delete(*args, **kwargs)


# ======================== 基础服务 ========================

class ServiceModel(models.Model):
    """基础服务模型"""
    name = models.CharField(max_length=50, verbose_name='服务类型', unique=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='基础价格',
        validators=[MinValueValidator(0)],
        help_text='该服务的基础价格'
    )
    applicable_pets = models.ManyToManyField(
        PetType,
        verbose_name='适用宠物类型',
        blank=True,
        related_name='services',
        help_text='该服务适用的宠物类型，留空表示适用所有类型'
    )
    icon = models.URLField(blank=True, verbose_name='图标地址', help_text='服务图标URL')
    description = models.TextField(blank=True, verbose_name='服务描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用', db_index=True)
    sort_order = models.IntegerField(default=0, verbose_name='排序', help_text='数字越小越靠前')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '基础服务'
        verbose_name_plural = '基础服务'
        ordering = ['sort_order', '-created_at']
        indexes = [
            models.Index(fields=['is_active', 'sort_order']),
        ]

    def __str__(self):
        return f"{self.name} - ¥{self.base_price}"

    def get_applicable_pets_display(self):
        """获取适用宠物类型的显示字符串"""
        pets = self.applicable_pets.all()
        if not pets.exists():
            return "全部宠物类型"
        return ", ".join([pet.name for pet in pets])

    def is_applicable_for_pet(self, pet_type):
        """检查服务是否适用于指定宠物类型"""
        if not self.applicable_pets.exists():
            return True
        return self.applicable_pets.filter(id=pet_type.id).exists()


# ======================== 附加服务 ========================

class AdditionalService(models.Model):
    """附加服务"""
    name = models.CharField(max_length=100, verbose_name='服务名称', unique=True)
    description = models.TextField(blank=True, verbose_name='服务描述')
    icon = models.URLField(blank=True, verbose_name='图标地址', help_text='服务图标URL')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='服务价格',
        validators=[MinValueValidator(0)]
    )
    applicable_pets = models.ManyToManyField(
        PetType,
        verbose_name='适用宠物类型',
        blank=True,
        related_name='additional_services',
        help_text='该附加服务适用的宠物类型，留空表示适用所有类型'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用', db_index=True)
    sort_order = models.IntegerField(default=0, verbose_name='排序', help_text='数字越小越靠前')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '附加服务'
        verbose_name_plural = '附加服务'
        ordering = ['sort_order', '-created_at']
        indexes = [
            models.Index(fields=['is_active', 'sort_order']),
        ]

    def __str__(self):
        return f"{self.name} - ¥{self.price}"

    def get_applicable_pets_display(self):
        """获取适用宠物类型的显示字符串"""
        pets = self.applicable_pets.all()
        if not pets.exists():
            return "全部宠物类型"
        return ", ".join([pet.name for pet in pets])

    def is_applicable_for_pet(self, pet_type):
        """检查附加服务是否适用于指定宠物类型"""
        if not self.applicable_pets.exists():
            return True
        return self.applicable_pets.filter(id=pet_type.id).exists()
