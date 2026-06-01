from rest_framework.pagination import (
    PageNumberPagination,
    LimitOffsetPagination,
    CursorPagination
)
from rest_framework.response import Response
from collections import OrderedDict


class StandardPagination(PageNumberPagination):
    """
    标准分页器
    适用于大多数列表接口

    请求参数:
        page: 页码（默认1）
        page_size: 每页数量（默认20，最大100）

    响应格式:
        {
            "count": 100,
            "total_pages": 5,
            "current_page": 1,
            "page_size": 20,
            "next": "http://...",
            "previous": null,
            "results": [...]
        }
    """
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


class MerchantListPagination(PageNumberPagination):
    """
    商家列表分页（C端用户使用）
    - 默认20条，最大50条
    - 防止用户请求过多数据
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('total_pages', self.page.paginator.num_pages),
            ('current_page', self.page.number),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('results', data)
        ]))


class InfiniteScrollPagination(PageNumberPagination):
    """
    无限滚动分页（移动端下拉加载）
    - 简化响应，只返回是否有下一页
    - 适合移动端无限滚动场景

    响应格式:
        {
            "has_more": true,
            "next_page": 2,
            "results": [...]
        }
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        has_next = self.page.has_next()
        return Response(OrderedDict([
            ('has_more', has_next),
            ('next_page', self.page.number + 1 if has_next else None),
            ('results', data)
        ]))


class AdminPagination(PageNumberPagination):
    """
    管理后台分页
    - 默认20条，最大200条
    - 包含更详细的分页信息
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('total_pages', self.page.paginator.num_pages),
            ('current_page', self.page.number),
            ('page_size', self.get_page_size(self.request)),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('start_index', self.page.start_index()),
            ('end_index', self.page.end_index()),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


class SmallPagination(PageNumberPagination):
    """
    小列表分页
    适用于下拉选择框等小数据量场景
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class LargeResultsPagination(PageNumberPagination):
    """
    大数据量分页
    适用于数据导出等场景
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class CursorStandardPagination(CursorPagination):
    """
    游标分页
    适用于:
    - 大数据量实时列表（如消息列表）
    - 防止数据变化导致的分页问题
    - 不需要知道总数的场景

    优点：性能好，不会出现翻页时数据重复/丢失
    缺点：不能跳页，只能上一页/下一页
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-created_at'  # 必须指定排序字段

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


class OffsetPagination(LimitOffsetPagination):
    """
    偏移量分页
    适用于需要精确控制起始位置的场景

    请求参数:
        offset: 起始位置（默认0）
        limit: 数量（默认20，最大100）
    """
    default_limit = 20
    max_limit = 100
    limit_query_param = 'limit'
    offset_query_param = 'offset'


class NoPagination:
    """
    不分页
    适用于数据量小的下拉列表等
    注意：请确保数据量可控，避免返回过多数据
    """
    display_page_controls = False

    def paginate_queryset(self, queryset, request, view=None):
        return None

    def get_paginated_response(self, data):
        return Response(data)


# ══════════════════════════════════════════════════════════════
# 分页工具函数
# ══════════════════════════════════════════════════════════════

def get_pagination_class(pagination_type: str = 'standard'):
    """
    根据类型获取分页器类

    Args:
        pagination_type: standard / merchant / infinite / admin / cursor / none
    """
    mapping = {
        'standard': StandardPagination,
        'merchant': MerchantListPagination,
        'infinite': InfiniteScrollPagination,
        'admin': AdminPagination,
        'small': SmallPagination,
        'large': LargeResultsPagination,
        'cursor': CursorStandardPagination,
        'offset': OffsetPagination,
        'none': NoPagination,
    }
    return mapping.get(pagination_type, StandardPagination)