# -*- coding: utf-8 -*-
# @Time    : 2025/10/20 18:56
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PetCategoryViewSet,
    PetViewSet,
    PetDiaryViewSet,
    PetServiceRecordViewSet
)

# 创建路由器
router = DefaultRouter()

# 注册视图集
router.register(r'categories', PetCategoryViewSet, basename='pet-category')
router.register(r'pets', PetViewSet, basename='pet')
router.register(r'diaries', PetDiaryViewSet, basename='pet-diary')
router.register(r'service-records', PetServiceRecordViewSet, basename='pet-service-record')

app_name = 'pet'

urlpatterns = [
    path('pet/', include(router.urls)),
]