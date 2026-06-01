# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 21:31
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
阿里云 OSS 上传工具（基于 alibabacloud-oss-v2）
"""
import logging
import mimetypes

import alibabacloud_oss_v2 as oss
from django.conf import settings

logger = logging.getLogger(__name__)

_client = None


def get_client() -> oss.Client:
    """获取 OSS Client（懒加载单例）"""
    global _client
    if _client is None:
        cfg_dict = settings.ALIYUN_OSS

        # 静态凭证（用 AK/SK 直接初始化）
        credentials_provider = oss.credentials.StaticCredentialsProvider(
            access_key_id=cfg_dict['ACCESS_KEY_ID'],
            access_key_secret=cfg_dict['ACCESS_KEY_SECRET'],
        )

        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = cfg_dict['REGION']        # 例如 'cn-hangzhou'

        # 自定义域名（CNAME）必须配置
        custom_endpoint = cfg_dict.get('CUSTOM_DOMAIN', '').strip()
        if custom_endpoint:
            cfg.endpoint = custom_endpoint     # 'https://cdn.yimengzhiyuan.com'
            cfg.use_cname = True

        _client = oss.Client(cfg)
    return _client


def upload_bytes(data: bytes, object_key: str, content_type: str = None) -> str:
    """
    上传二进制数据到 OSS

    Args:
        data: 二进制内容
        object_key: OSS 对象路径，如 'campaigns/qr/123_xxx.jpg'
        content_type: MIME 类型，不传则按扩展名推断

    Returns:
        可访问的完整 URL
    """
    if content_type is None:
        guessed, _ = mimetypes.guess_type(object_key)
        content_type = guessed or 'application/octet-stream'

    cfg_dict = settings.ALIYUN_OSS
    client = get_client()
    client.put_object(
        oss.PutObjectRequest(
            bucket=cfg_dict['BUCKET'],
            key=object_key,
            body=data,
            content_type=content_type,
        )
    )
    return _build_url(object_key)


def upload_file(local_path: str, object_key: str, content_type: str = None) -> str:
    """从本地路径上传"""
    with open(local_path, 'rb') as f:
        return upload_bytes(f.read(), object_key, content_type)


def delete_object(object_key: str) -> bool:
    """删除 OSS 对象"""
    if not object_key:
        return False
    try:
        cfg_dict = settings.ALIYUN_OSS
        client = get_client()
        client.delete_object(
            oss.DeleteObjectRequest(
                bucket=cfg_dict['BUCKET'],
                key=object_key,
            )
        )
        return True
    except Exception as e:
        logger.error(f'OSS 删除失败 {object_key}: {e}')
        return False


def extract_object_key(url: str) -> str:
    """从完整 URL 反解出 object_key（用于删除场景）"""
    if not url:
        return ''
    cfg_dict = settings.ALIYUN_OSS
    custom_domain = (cfg_dict.get('CUSTOM_DOMAIN') or '').rstrip('/')
    if custom_domain and url.startswith(custom_domain):
        return url[len(custom_domain) + 1:]
    return ''


def _build_url(object_key: str) -> str:
    """构建访问 URL（基于自定义域名）"""
    cfg_dict = settings.ALIYUN_OSS
    custom_domain = (cfg_dict.get('CUSTOM_DOMAIN') or '').rstrip('/')
    if custom_domain:
        return f'{custom_domain}/{object_key}'
    # 兜底：默认外网域名（中国内地2025年3月后已禁用，仅海外可用）
    bucket = cfg_dict['BUCKET']
    region = cfg_dict['REGION']
    return f'https://{bucket}.oss-{region}.aliyuncs.com/{object_key}'