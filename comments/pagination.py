# -*- coding: utf-8 -*-
# @Time    : 2026/4/19 20:49
# @Author  : Delock

# -*- coding: utf-8 -*-
from rest_framework.pagination import PageNumberPagination


class ReviewPageNumberPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'