
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """标准分页：默认 20 条，最大 100 条"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class SmallPagination(PageNumberPagination):
    """小分页：用于管理端列表，默认 10 条"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50