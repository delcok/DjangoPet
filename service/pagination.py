# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:09
# @Author  : Delock

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CustomPageNumberPagination(PageNumberPagination):
    """自定义分页类"""
    page_size = 10  # 默认每页数量
    page_size_query_param = 'page_size'  # 允许客户端设置每页数量的参数名
    max_page_size = 100  # 最大每页数量
    page_query_param = 'page'  # 页码参数名

    def get_paginated_response(self, data):
        """自定义分页响应格式"""
        return Response({
            'pagination': {
                'links': {
                    'next': self.get_next_link(),
                    'previous': self.get_previous_link()
                },
                'count': self.page.paginator.count,
                'current_page': self.page.number,
                'total_pages': self.page.paginator.num_pages,
                'page_size': self.get_page_size(self.request),
                'has_next': self.page.has_next(),
                'has_previous': self.page.has_previous(),
            },
            'results': data
        })


class SmallResultsSetPagination(PageNumberPagination):
    """小结果集分页类"""
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20


class LargeResultsSetPagination(PageNumberPagination):
    """大结果集分页类"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200