# -*- coding: utf-8 -*-
# @Time    : 2026/6/7 16:25
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
adoption/pagination.py — 领养模块分页器

- 页码分页: 响应里带 has_next,小程序 onReachBottom 触底加载直接用
- 动态流(领养后的TA)用游标分页: 新数据持续插入时页码分页会"翻页漂移"
  (上一页看过的内容被顶到下一页重复出现),游标分页天然免疫
"""
from collections import OrderedDict

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class BasePageNumberPagination(PageNumberPagination):
    page_query_param = 'page'
    page_size_query_param = 'page_size'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('total', self.page.paginator.count),
            ('page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('total_pages', self.page.paginator.num_pages),
            ('has_next', self.page.has_next()),
            ('list', data),
        ]))


class StandardPagination(BasePageNumberPagination):
    """C端默认: 宠物列表 / 我的申请 / 我的收藏"""
    page_size = 10
    max_page_size = 50


class AdminPagination(BasePageNumberPagination):
    """后台列表: 申请单 / 违规 / 资格档案"""
    page_size = 20
    max_page_size = 100


class UpdateFeedCursorPagination(CursorPagination):
    """领养动态流(按时间倒序的无限滚动)"""
    page_size = 10
    max_page_size = 30
    page_size_query_param = 'page_size'
    cursor_query_param = 'cursor'
    ordering = ('-created_at', '-id')

    def get_ordering(self, request, queryset, view):
        # 游标分页的 cursor 是按排序键编码位置的,排序必须由分页器自己锁定,
        # 不能让 view 上的 OrderingFilter 改写(否则换了模型/字段就崩或静默错乱)
        return self.ordering