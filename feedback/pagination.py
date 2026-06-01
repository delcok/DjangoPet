# -*- coding: utf-8 -*-
"""
反馈分页
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class FeedbackPagination(PageNumberPagination):
    """
    反馈分页：?page=&page_size=
    统一响应结构，user / admin 两个视图集共用。
    """

    page_size = 10
    page_query_param = 'page'
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'code': 200,
            'message': '获取成功',
            'total': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'data': data,
        })
