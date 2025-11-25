# -*- coding: utf-8 -*-
# @Time    : 2025/11/9 16:22
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StrayAnimalViewSet,
    StrayAnimalInteractionViewSet,
    StrayAnimalFavoriteViewSet,
    StrayAnimalReportViewSet
)

app_name = 'stray_animals'

router = DefaultRouter()
router.register(r'animals', StrayAnimalViewSet, basename='animal')
router.register(r'interactions', StrayAnimalInteractionViewSet, basename='interaction')
router.register(r'favorites', StrayAnimalFavoriteViewSet, basename='favorite')
router.register(r'reports', StrayAnimalReportViewSet, basename='report')

urlpatterns = [
    path('strays/', include(router.urls)),
]