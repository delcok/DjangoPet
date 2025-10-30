# -*- coding: utf-8 -*-
# @Time    : 2025/9/10 20:33
# @Author  : Delock


from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'pet_services'

# API路由
urlpatterns = [
    # 基础服务 API
    path('services/', views.ServiceModelListView.as_view(), name='service-list'),
    path('services/<int:pk>/', views.ServiceModelDetailView.as_view(), name='service-detail'),

    # 宠物类型 API
    path('pet-types/', views.PetTypeListView.as_view(), name='pet-type-list'),
    path('pet-types/<int:pk>/', views.PetTypeDetailView.as_view(), name='pet-type-detail'),

    # 附加服务 API
    path('additional-services/', views.AdditionalServiceListView.as_view(), name='additional-service-list'),
    path('additional-services/<int:pk>/', views.AdditionalServiceDetailView.as_view(),
         name='additional-service-detail'),

    # 根据宠物类型获取服务
    path('pet-types/<int:pet_type_id>/services/', views.PetTypeServiceView.as_view(), name='pet-type-services'),

    # 统计和搜索 API
    path('summary/', views.service_summary_view, name='service-summary'),
    path('search/', views.search_services_view, name='search-services'),
]