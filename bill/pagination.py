# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:09
# @Author  : Delock

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from collections import OrderedDict


class StandardResultsSetPagination(PageNumberPagination):
    """标准分页器"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('total_pages', self.page.paginator.num_pages),
            ('current_page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


class BillPagination(StandardResultsSetPagination):
    """账单分页器"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50


class ServiceOrderPagination(StandardResultsSetPagination):
    """服务订单分页器"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 30


class SmallResultsSetPagination(PageNumberPagination):
    """小结果集分页器（用于移动端）"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 20
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('current_page', self.page.number),
            ('results', data)
        ]))