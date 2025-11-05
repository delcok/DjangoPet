# -*- coding: utf-8 -*-
# @Time    : 2025/11/05
# @Author  : Delock (Modified by ChatGPT)

from django.urls import path
from . import views

app_name = 'pet_services'

urlpatterns = [
    # =================== 宠物类型 ===================
    path('pet-types/', views.PetTypeListView.as_view(), name='pettype-list'),
    path('pet-types/<int:pk>/', views.PetTypeDetailView.as_view(), name='pettype-detail'),

    # =================== 基础服务 ===================
    path('services/', views.ServiceModelListView.as_view(), name='service-list'),
    path('services/<int:pk>/', views.ServiceModelDetailView.as_view(), name='service-detail'),

    # =================== 附加服务 ===================
    path('additional-services/', views.AdditionalServiceListView.as_view(), name='additional-list'),
    path('additional-services/<int:pk>/', views.AdditionalServiceDetailView.as_view(), name='additional-detail'),

    # =================== 宠物类型关联服务 ===================
    # 获取该宠物类型下的所有基础 + 附加服务
    path('pet-types/<int:pet_type_id>/services/', views.PetTypeServicesView.as_view(), name='pettype-services'),

    # 向后兼容旧版本接口（等价于上面的 /services/）
    path('pet-types/<int:pet_type_id>/all-services/', views.PetTypeServicesView.as_view(), name='pettype-all-services'),

    # 仅附加服务（用于前端独立展示）
    path('pet-types/<int:pet_type_id>/additional-services/', views.PetTypeAdditionalServicesView.as_view(), name='pettype-additional-services'),

    # =================== 服务概要与搜索 ===================
    # 服务统计汇总
    path('summary/', views.service_summary_view, name='service-summary'),

    # 全局搜索（可搜索基础服务、附加服务、宠物类型）
    path('search/', views.search_services_view, name='service-search'),
]
