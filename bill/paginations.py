# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 18:25
# @Author  : Delock


from rest_framework.pagination import PageNumberPagination


class OrderPagination(PageNumberPagination):
    """用户端 & 商家端订单分页"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class AdminOrderPagination(PageNumberPagination):
    """管理端订单分页"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100