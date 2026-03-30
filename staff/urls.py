# -*- coding: utf-8 -*-
# @Time    : 2026/3/30 18:43
# @Author  : Delock

from django.urls import path
from . import views

urlpatterns = [
    path('staff/login/', views.staff_login, name='staff-login'),
    path('staff/profile/', views.staff_profile, name='staff-profile'),
]