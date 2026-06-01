# -*- coding: utf-8 -*-
# @Time    : 2026/4/17
# @Author  : Delock

from collections import OrderedDict
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    标准分页 —— 用户端通用
    使用方式：?page=1&page_size=20
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('total', self.page.paginator.count),
            ('page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('total_pages', self.page.paginator.num_pages),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('results', data),
        ]))


class AdminUserPagination(PageNumberPagination):
    """
    管理员用户列表分页 —— 默认 20，最大 200
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('total', self.page.paginator.count),
            ('page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('total_pages', self.page.paginator.num_pages),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('results', data),
        ]))


class LoginLogPagination(PageNumberPagination):
    """
    登录日志分页 —— 数据量大，默认 50
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('total', self.page.paginator.count),
            ('page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('total_pages', self.page.paginator.num_pages),
            ('results', data),
        ]))