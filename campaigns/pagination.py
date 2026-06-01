# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 23:36
# @Author  : Delock
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    标准分页类，相比默认 PageNumberPagination 的改进:
    - 当 page=1 且结果为空时，返回空列表而不是 404
    - 支持前端通过 page_size 参数动态指定每页条数
    - 限制 page_size 上限防止恶意请求
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        """
        重写以兼容空结果集
        """
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        from django.core.paginator import Paginator, InvalidPage
        from rest_framework.exceptions import NotFound

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
        except InvalidPage:
            # ✅ 关键改动:第 1 页空结果时不抛 404,返回空列表
            if str(page_number) == '1':
                self.page = self._make_empty_page(paginator)
            else:
                raise NotFound(f'页码 {page_number} 无效')

        if paginator.num_pages > 1 and self.template is not None:
            self.display_page_controls = True

        self.request = request
        return list(self.page)

    def _make_empty_page(self, paginator):
        """构造一个"空的第一页"对象，让 DRF 流程能继续走"""
        from django.core.paginator import Page
        return Page([], 1, paginator)

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'results': data,
        })