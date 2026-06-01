
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class AdminPagination(PageNumberPagination):
    """
    管理后台通用分页器

    支持的查询参数：
    - page: 页码，默认1
    - page_size: 每页数量，默认20，最大100

    示例：
    - /api/managers/?page=1&page_size=20
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        """
        自定义分页响应格式

        返回格式：
        {
            "count": 总数量,
            "page": 当前页码,
            "page_size": 每页数量,
            "total_pages": 总页数,
            "next": 下一页链接,
            "previous": 上一页链接,
            "results": 数据列表
        }
        """
        return Response({
            'count': self.page.paginator.count,
            'page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'total_pages': self.page.paginator.num_pages,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })


class LargeResultsSetPagination(PageNumberPagination):
    """
    大数据集分页器（用于导出等场景）
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class SmallResultsSetPagination(PageNumberPagination):
    """
    小数据集分页器（用于下拉选择等场景）
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'page': self.page.number,
            'total_pages': self.page.paginator.num_pages,
            'results': data
        })