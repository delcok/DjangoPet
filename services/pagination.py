# -*- coding: utf-8 -*-
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """标准分页器"""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })


class SmallPagination(PageNumberPagination):
    """小分页器（用于移动端）"""

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class LargePagination(PageNumberPagination):
    """大分页器（用于后台管理）"""

    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200