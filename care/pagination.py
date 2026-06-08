# -*- coding: utf-8 -*-
"""分页类。如你项目已有统一分页/响应封装,可直接换成你的。"""
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """常规列表:默认每页 20,?page=2&page_size=30"""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LargeResultsSetPagination(PageNumberPagination):
    """内容库等较长列表:默认每页 50"""
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200