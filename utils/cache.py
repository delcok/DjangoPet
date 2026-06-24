# utils/cache.py

import redis
import json
import random
import string
from datetime import datetime
from functools import wraps
from django.conf import settings

# ══════════════════════════════════════════════════════════════
# Redis 连接池
# ══════════════════════════════════════════════════════════════

_pool = None


def get_redis_connection():
    """获取 Redis 连接（使用连接池）"""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool(
            host=getattr(settings, 'REDIS_HOST', 'localhost'),
            port=getattr(settings, 'REDIS_PORT', 6379),
            db=getattr(settings, 'REDIS_DB', 0),
            password=getattr(settings, 'REDIS_PASSWORD', None),
            decode_responses=True,
            max_connections=50
        )
    return redis.Redis(connection_pool=_pool)


# ══════════════════════════════════════════════════════════════
# 缓存前缀常量
# ══════════════════════════════════════════════════════════════

class CacheKey:
    """缓存 Key 前缀"""
    # 验证码相关
    SMS_CODE = "sms:code:{scene}:{phone}"  # 验证码存储
    SMS_CODE_VERIFY_COUNT = "sms:verify:{scene}:{phone}"  # 验证次数
    SMS_SEND_INTERVAL = "sms:interval:{phone}"  # 发送间隔
    SMS_DAILY_COUNT = "sms:daily:{phone}:{date}"  # 每日发送次数

    # 登录安全
    LOGIN_FAIL_COUNT = "login:fail:{user_type}:{identifier}"  # 登录失败次数
    ACCOUNT_LOCKED = "login:locked:{user_type}:{identifier}"  # 账户锁定

    # Token 相关
    TOKEN_BLACKLIST = "token:blacklist:{jti}"  # Token 黑名单
    USER_TOKENS = "user:tokens:{user_type}:{user_id}"  # 用户所有 Token

    # 分布式锁
    LOCK = "lock:{name}"

    # 业务缓存
    MERCHANT_INFO = "merchant:info:{merchant_id}"
    MERCHANT_LIST = "merchant:list:{query_hash}"
    CATEGORY_LIST = "category:list"
    DISTRICT_LIST = "district:list"

    # 数据面板
    DASHBOARD_OVERVIEW = "dashboard:overview"


# ══════════════════════════════════════════════════════════════
# 验证码管理
# ══════════════════════════════════════════════════════════════

class SMSCodeManager:
    """短信验证码管理器"""

    # 配置
    CODE_LENGTH = 6  # 验证码长度
    CODE_EXPIRE = 300  # 验证码有效期（秒）
    SEND_INTERVAL = 60  # 发送间隔（秒）
    MAX_DAILY_SEND = 10  # 每日最大发送次数
    MAX_VERIFY_ATTEMPTS = 5  # 最大验证次数

    def __init__(self):
        self.redis = get_redis_connection()

    def generate_code(self) -> str:
        """生成随机验证码"""
        return ''.join(random.choices(string.digits, k=self.CODE_LENGTH))

    def can_send(self, phone: str) -> tuple[bool, str]:
        """
        检查是否可以发送验证码
        返回: (是否可发送, 原因)
        """
        # 检查发送间隔
        interval_key = CacheKey.SMS_SEND_INTERVAL.format(phone=phone)
        if self.redis.exists(interval_key):
            ttl = self.redis.ttl(interval_key)
            return False, f"发送太频繁，请{ttl}秒后重试"

        # 检查每日发送次数
        today = datetime.now().strftime('%Y%m%d')
        daily_key = CacheKey.SMS_DAILY_COUNT.format(phone=phone, date=today)
        daily_count = int(self.redis.get(daily_key) or 0)

        if daily_count >= self.MAX_DAILY_SEND:
            return False, "今日发送次数已达上限，请明天再试"

        return True, ""

    def save_code(self, phone: str, code: str, scene: str = 'login'):
        """
        保存验证码到 Redis
        scene: login(登录) / register(注册) / reset(重置密码) / bind(绑定)
        """
        # 保存验证码
        code_key = CacheKey.SMS_CODE.format(scene=scene, phone=phone)
        self.redis.setex(code_key, self.CODE_EXPIRE, code)

        # 重置验证次数
        verify_key = CacheKey.SMS_CODE_VERIFY_COUNT.format(scene=scene, phone=phone)
        self.redis.delete(verify_key)

        # 设置发送间隔
        interval_key = CacheKey.SMS_SEND_INTERVAL.format(phone=phone)
        self.redis.setex(interval_key, self.SEND_INTERVAL, '1')

        # 增加每日发送计数
        today = datetime.now().strftime('%Y%m%d')
        daily_key = CacheKey.SMS_DAILY_COUNT.format(phone=phone, date=today)
        pipe = self.redis.pipeline()
        pipe.incr(daily_key)
        pipe.expire(daily_key, 86400)  # 24小时过期
        pipe.execute()

    def verify_code(self, phone: str, code: str, scene: str = 'login') -> tuple[bool, str]:
        """
        验证验证码
        返回: (是否正确, 错误信息)
        """
        code_key = CacheKey.SMS_CODE.format(scene=scene, phone=phone)
        verify_key = CacheKey.SMS_CODE_VERIFY_COUNT.format(scene=scene, phone=phone)

        # 检查验证次数
        verify_count = int(self.redis.get(verify_key) or 0)
        if verify_count >= self.MAX_VERIFY_ATTEMPTS:
            # 清除验证码，需要重新获取
            self.redis.delete(code_key)
            self.redis.delete(verify_key)
            return False, "验证次数过多，请重新获取验证码"

        # 获取存储的验证码
        stored_code = self.redis.get(code_key)
        if not stored_code:
            return False, "验证码已过期，请重新获取"

        # 增加验证次数
        self.redis.incr(verify_key)
        self.redis.expire(verify_key, self.CODE_EXPIRE)

        # 验证
        if stored_code != code:
            remaining = self.MAX_VERIFY_ATTEMPTS - verify_count - 1
            return False, f"验证码错误，还剩{remaining}次机会"

        # 验证成功，删除验证码（一次性使用）
        self.redis.delete(code_key)
        self.redis.delete(verify_key)

        return True, ""


# ══════════════════════════════════════════════════════════════
# 登录安全管理
# ══════════════════════════════════════════════════════════════

class LoginSecurityManager:
    """登录安全管理器"""

    MAX_FAIL_COUNT = 5  # 最大失败次数
    LOCK_DURATION = 1800  # 锁定时长（秒）= 30分钟
    FAIL_COUNT_EXPIRE = 3600  # 失败计数过期时间（秒）

    def __init__(self):
        self.redis = get_redis_connection()

    def is_locked(self, identifier: str, user_type: str = 'merchant') -> tuple[bool, int]:
        """
        检查账户是否被锁定
        返回: (是否锁定, 剩余锁定秒数)
        """
        lock_key = CacheKey.ACCOUNT_LOCKED.format(
            user_type=user_type,
            identifier=identifier
        )
        ttl = self.redis.ttl(lock_key)
        if ttl > 0:
            return True, ttl
        return False, 0

    def record_fail(self, identifier: str, user_type: str = 'merchant') -> tuple[int, bool]:
        """
        记录登录失败
        返回: (当前失败次数, 是否触发锁定)
        """
        fail_key = CacheKey.LOGIN_FAIL_COUNT.format(
            user_type=user_type,
            identifier=identifier
        )

        # 增加失败次数
        pipe = self.redis.pipeline()
        pipe.incr(fail_key)
        pipe.expire(fail_key, self.FAIL_COUNT_EXPIRE)
        results = pipe.execute()

        fail_count = results[0]

        # 检查是否需要锁定
        if fail_count >= self.MAX_FAIL_COUNT:
            lock_key = CacheKey.ACCOUNT_LOCKED.format(
                user_type=user_type,
                identifier=identifier
            )
            self.redis.setex(lock_key, self.LOCK_DURATION, '1')
            self.redis.delete(fail_key)  # 清除失败计数
            return fail_count, True

        return fail_count, False

    def clear_fail_count(self, identifier: str, user_type: str = 'merchant'):
        """登录成功后清除失败计数"""
        fail_key = CacheKey.LOGIN_FAIL_COUNT.format(
            user_type=user_type,
            identifier=identifier
        )
        self.redis.delete(fail_key)

    def get_remaining_attempts(self, identifier: str, user_type: str = 'merchant') -> int:
        """获取剩余尝试次数"""
        fail_key = CacheKey.LOGIN_FAIL_COUNT.format(
            user_type=user_type,
            identifier=identifier
        )
        fail_count = int(self.redis.get(fail_key) or 0)
        return max(0, self.MAX_FAIL_COUNT - fail_count)


# ══════════════════════════════════════════════════════════════
# Token 管理
# ══════════════════════════════════════════════════════════════

class TokenManager:
    """Token 管理器"""

    def __init__(self):
        self.redis = get_redis_connection()

    def add_to_blacklist(self, jti: str, expire: int = 86400 * 7):
        """将 Token 加入黑名单"""
        key = CacheKey.TOKEN_BLACKLIST.format(jti=jti)
        self.redis.setex(key, expire, '1')

    def is_blacklisted(self, jti: str) -> bool:
        """检查 Token 是否在黑名单"""
        key = CacheKey.TOKEN_BLACKLIST.format(jti=jti)
        return self.redis.exists(key) > 0

    def save_user_token(self, user_id: int, user_type: str, jti: str, expire: int = 86400 * 7):
        """保存用户的 Token（用于强制下线）"""
        key = CacheKey.USER_TOKENS.format(user_type=user_type, user_id=user_id)
        self.redis.sadd(key, jti)
        self.redis.expire(key, expire)

    def invalidate_all_tokens(self, user_id: int, user_type: str):
        """使用户所有 Token 失效（强制下线）"""
        key = CacheKey.USER_TOKENS.format(user_type=user_type, user_id=user_id)
        tokens = self.redis.smembers(key)

        pipe = self.redis.pipeline()
        for jti in tokens:
            blacklist_key = CacheKey.TOKEN_BLACKLIST.format(jti=jti)
            pipe.setex(blacklist_key, 86400 * 7, '1')
        pipe.delete(key)
        pipe.execute()


# ══════════════════════════════════════════════════════════════
# 业务数据缓存
# ══════════════════════════════════════════════════════════════

class BusinessCache:
    """业务数据缓存"""

    DEFAULT_EXPIRE = 300  # 默认5分钟

    def __init__(self):
        self.redis = get_redis_connection()

    def get_merchant(self, merchant_id: int) -> dict | None:
        """获取商家缓存"""
        key = CacheKey.MERCHANT_INFO.format(merchant_id=merchant_id)
        data = self.redis.get(key)
        return json.loads(data) if data else None

    def set_merchant(self, merchant_id: int, data: dict, expire: int = None):
        """设置商家缓存"""
        key = CacheKey.MERCHANT_INFO.format(merchant_id=merchant_id)
        self.redis.setex(
            key,
            expire or self.DEFAULT_EXPIRE,
            json.dumps(data, ensure_ascii=False)
        )

    def delete_merchant(self, merchant_id: int):
        """删除商家缓存"""
        key = CacheKey.MERCHANT_INFO.format(merchant_id=merchant_id)
        self.redis.delete(key)

    def get_category_list(self) -> list | None:
        """获取分类列表缓存"""
        data = self.redis.get(CacheKey.CATEGORY_LIST)
        return json.loads(data) if data else None

    def set_category_list(self, data: list, expire: int = 3600):
        """设置分类列表缓存"""
        self.redis.setex(
            CacheKey.CATEGORY_LIST,
            expire,
            json.dumps(data, ensure_ascii=False)
        )

    def delete_category_list(self):
        """删除分类列表缓存"""
        self.redis.delete(CacheKey.CATEGORY_LIST)

    def get_district_list(self) -> list | None:
        """获取商圈列表缓存"""
        data = self.redis.get(CacheKey.DISTRICT_LIST)
        return json.loads(data) if data else None

    def set_district_list(self, data: list, expire: int = 3600):
        """设置商圈列表缓存"""
        self.redis.setex(
            CacheKey.DISTRICT_LIST,
            expire,
            json.dumps(data, ensure_ascii=False)
        )


# ══════════════════════════════════════════════════════════════
# 分布式锁
# ══════════════════════════════════════════════════════════════

class DistributedLock:
    """分布式锁"""

    def __init__(self, name: str, expire: int = 10):
        self.redis = get_redis_connection()
        self.name = name
        self.key = CacheKey.LOCK.format(name=name)
        self.expire = expire
        self.token = None

    def acquire(self, blocking: bool = True, timeout: int = None) -> bool:
        """获取锁"""
        import time
        import uuid

        self.token = str(uuid.uuid4())
        start = time.time()

        while True:
            if self.redis.set(self.key, self.token, nx=True, ex=self.expire):
                return True

            if not blocking:
                return False

            if timeout and (time.time() - start) > timeout:
                return False

            time.sleep(0.1)

    def release(self):
        """释放锁"""
        # 使用 Lua 脚本保证原子性
        lua_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        self.redis.eval(lua_script, 1, self.key, self.token)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ══════════════════════════════════════════════════════════════
# 缓存装饰器
# ══════════════════════════════════════════════════════════════

def cache_result(key_pattern: str, expire: int = 300):
    """
    缓存函数结果的装饰器

    使用示例:
    @cache_result('user:profile:{user_id}', expire=600)
    def get_user_profile(user_id):
        ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存 key
            cache_key = key_pattern.format(*args, **kwargs)

            redis_conn = get_redis_connection()

            # 尝试从缓存获取
            cached = redis_conn.get(cache_key)
            if cached:
                return json.loads(cached)

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            if result is not None:
                redis_conn.setex(
                    cache_key,
                    expire,
                    json.dumps(result, ensure_ascii=False, default=str)
                )

            return result

        return wrapper

    return decorator


def invalidate_cache(key_pattern: str):
    """
    清除缓存的装饰器

    使用示例:
    @invalidate_cache('user:profile:{user_id}')
    def update_user_profile(user_id, data):
        ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            # 清除缓存
            cache_key = key_pattern.format(*args, **kwargs)
            redis_conn = get_redis_connection()
            redis_conn.delete(cache_key)

            return result

        return wrapper

    return decorator