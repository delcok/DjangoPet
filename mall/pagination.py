# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:35
# @Author  : Delock
# pagination.py
# Django REST Framework 分页配置

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    """
    标准分页类
    每页24条数据，适用于商品列表等需要较多数据的场景
    """
    page_size = 24  # 默认每页24条
    page_size_query_param = 'page_size'  # 允许客户端通过此参数修改每页条数
    max_page_size = 100  # 每页最多100条
    page_query_param = 'page'  # 页码参数名

    def get_paginated_response(self, data):
        """
        自定义分页响应格式
        """
        return Response({
            'count': self.page.paginator.count,  # 总条数
            'next': self.get_next_link(),  # 下一页链接
            'previous': self.get_previous_link(),  # 上一页链接
            'current_page': self.page.number,  # 当前页码
            'total_pages': self.page.paginator.num_pages,  # 总页数
            'page_size': self.page_size,  # 每页条数
            'results': data  # 数据列表
        })


class SmallResultsSetPagination(PageNumberPagination):
    """
    小数据量分页类
    每页10条数据，适用于订单列表、收藏列表等
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'current_page': self.page.number,
            'total_pages': self.page.paginator.num_pages,
            'page_size': self.page_size,
            'results': data
        })


class LargeResultsSetPagination(PageNumberPagination):
    """
    大数据量分页类
    每页50条数据，适用于管理后台等需要展示更多数据的场景
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'current_page': self.page.number,
            'total_pages': self.page.paginator.num_pages,
            'page_size': self.page_size,
            'results': data
        })