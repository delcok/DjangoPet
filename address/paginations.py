# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 17:08
# @Author  : Delock


from rest_framework.pagination import PageNumberPagination


class AddressPagination(PageNumberPagination):
    """
    用户端地址分页
    地址一般不多，默认 10 条/页，最多 20
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 20


class AddressAdminPagination(PageNumberPagination):
    """管理端地址分页"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100