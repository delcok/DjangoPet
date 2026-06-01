# -*- coding: utf-8 -*-
"""
权限模块
支持五种角色：用户(User)、管理员(Manager)、商家(Merchant)、商家子账号(MerchantSubAccount)、员工(Staff)
"""

from rest_framework import permissions
from managers.models import Manager
from merchants.models import Merchant, MerchantSubAccount
from user.models import User
from staffs.models import Staff  # 新增员工模型导入


class AllowAny(permissions.BasePermission):
    """任何人都可以访问（包括未认证用户）"""

    def has_permission(self, request, view):
        return True


class IsAuthenticated(permissions.BasePermission):
    """必须是已认证用户（任意类型）"""

    def has_permission(self, request, view):
        return bool(
            request.user and
            hasattr(request.user, 'is_authenticated') and
            request.user.is_authenticated
        )


# ============================================================
# 用户权限
# ============================================================

class IsUser(permissions.BasePermission):
    """仅普通用户可访问"""

    message = '此接口仅对用户开放'

    def has_permission(self, request, view):
        return isinstance(request.user, User) and request.user.is_active


class IsActiveUser(permissions.BasePermission):
    """必须是未被封禁的活跃用户"""

    message = '用户状态异常'

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return request.user.is_active and not request.user.is_banned


class IsVipUser(permissions.BasePermission):
    """仅 VIP 用户可访问"""

    message = '此功能仅对 VIP 用户开放'

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return request.user.is_vip and request.user.is_active


class IsVerifiedUser(permissions.BasePermission):
    """仅已实名认证的用户可访问"""

    message = '请先完成实名认证'

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return request.user.is_verified and request.user.is_active


class IsResourceOwner(permissions.BasePermission):
    """
    资源所有者权限(对象级)

    ✅ 修复 #17: 用 is not None 替代 `or`,
    防止 user_id=0 等"假值但有效"的 ID 被错误跳过。
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        if not isinstance(request.user, User):
            return False

        owner_id = getattr(obj, 'user_id', None)
        if owner_id is None:
            owner_id = getattr(obj, 'owner_id', None)
        if owner_id is not None:
            return owner_id == request.user.id

        owner = getattr(obj, 'user', None)
        if owner is None:
            owner = getattr(obj, 'owner', None)
        if owner is not None:
            return owner.id == request.user.id

        return False


class IsAuthorOrReadOnly(permissions.BasePermission):
    """
    内容作者本人可写，读操作放行（对象级）。

    与 IsResourceOwner 的区别：
    - 归属字段优先匹配 author（社区帖子/评论、宠物日记等用的就是 author），
      其次兼容 user / owner；
    - 安全方法（GET/HEAD/OPTIONS）一律放行，可见范围交给各视图的 get_queryset 控制；
    - 带 has_permission，匿名用户不能执行写操作。
    仅对普通用户（User）生效；平台管理请走 Manager 相关权限/接口。

    适用：community 的 Post/Comment、pet 的 PetDiary 等以 author 为归属的资源。
    """

    message = '您无权操作此资源'

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return isinstance(request.user, User) and request.user.is_active

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not isinstance(request.user, User):
            return False

        for id_attr in ('author_id', 'user_id', 'owner_id'):
            owner_id = getattr(obj, id_attr, None)
            if owner_id is not None:
                return owner_id == request.user.id

        for obj_attr in ('author', 'user', 'owner'):
            owner = getattr(obj, obj_attr, None)
            if owner is not None:
                return getattr(owner, 'id', None) == request.user.id

        return False


# ============================================================
# 管理后台权限（平台管理员）
# ============================================================

class IsManager(permissions.BasePermission):
    """仅平台管理员可访问"""

    message = '此接口仅对管理员开放'

    def has_permission(self, request, view):
        return isinstance(request.user, Manager) and request.user.status == 'active'


class IsSuperAdmin(permissions.BasePermission):
    """仅超级管理员可访问"""

    message = '此操作需要超级管理员权限'

    def has_permission(self, request, view):
        if not isinstance(request.user, Manager):
            return False
        return request.user.is_super_admin and request.user.status == 'active'


class HasModuleAccess(permissions.BasePermission):
    """
    模块访问权限

    使用方式：
    在 View 中设置 required_module 属性，如：
    class MerchantViewSet(ViewSet):
        permission_classes = [HasModuleAccess]
        required_module = 'merchant'
    """

    message = '您没有该模块的操作权限'

    def has_permission(self, request, view):
        if not isinstance(request.user, Manager):
            return False

        if request.user.status != 'active':
            return False

        # 超管拥有所有权限
        if request.user.is_super_admin:
            return True

        # 获取 View 定义的 required_module
        required_module = getattr(view, 'required_module', None)
        if not required_module:
            return True  # 未定义则默认允许

        return request.user.has_module_access(required_module)


class ManagerRoleIn(permissions.BasePermission):
    """
    指定角色的管理员可访问

    使用方式：
    class FinanceViewSet(ViewSet):
        permission_classes = [ManagerRoleIn]
        allowed_roles = ['super_admin', 'finance']
    """

    message = '您的角色无权执行此操作'

    def has_permission(self, request, view):
        if not isinstance(request.user, Manager):
            return False

        if request.user.status != 'active':
            return False

        allowed_roles = getattr(view, 'allowed_roles', [])
        if not allowed_roles:
            return True

        return request.user.role in allowed_roles


# ============================================================
# 商家端权限（B端）
# ============================================================

class IsMerchant(permissions.BasePermission):
    """仅商家（主账号或子账号）可访问"""

    message = '此接口仅对商家开放'

    def has_permission(self, request, view):
        # 主账号
        if isinstance(request.user, Merchant):
            return request.user.status != 'closed'
        # 子账号
        if isinstance(request.user, MerchantSubAccount):
            return request.user.is_active and request.user.merchant.status != 'closed'
        return False


class IsMerchantMainAccount(permissions.BasePermission):
    """仅商家主账号可访问（子账号不可）"""

    message = '此操作需要主账号权限'

    def has_permission(self, request, view):
        if not isinstance(request.user, Merchant):
            return False
        return request.user.status != 'closed'


class IsActiveMerchant(permissions.BasePermission):
    """仅营业中的商家可访问"""

    message = '商家账号状态异常'

    def has_permission(self, request, view):
        if isinstance(request.user, Merchant):
            return request.user.status == 'active'
        if isinstance(request.user, MerchantSubAccount):
            return (
                    request.user.is_active and
                    request.user.merchant.status == 'active'
            )
        return False


class IsMerchantResourceOwner(permissions.BasePermission):
    """
    商家资源所有者权限
    检查商家是否有权操作某个资源（如商品、服务等）

    要求对象有 merchant 或 merchant_id 属性
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 获取当前商家 ID
        if isinstance(request.user, Merchant):
            current_merchant_id = request.user.id
        elif isinstance(request.user, MerchantSubAccount):
            current_merchant_id = request.user.merchant_id
        else:
            return False

        # 检查资源归属
        resource_merchant_id = getattr(obj, 'merchant_id', None)
        if resource_merchant_id:
            return resource_merchant_id == current_merchant_id

        resource_merchant = getattr(obj, 'merchant', None)
        if resource_merchant:
            return resource_merchant.id == current_merchant_id

        return False


# ============================================================
# 员工权限（新增）
# ============================================================

class IsStaff(permissions.BasePermission):
    """仅员工可访问"""

    message = '此接口仅对员工开放'

    def has_permission(self, request, view):
        if not isinstance(request.user, Staff):
            return False
        return request.user.status == 'active'


class IsActiveStaff(permissions.BasePermission):
    """仅在职且在线的员工可访问"""

    message = '员工状态异常'

    def has_permission(self, request, view):
        if not isinstance(request.user, Staff):
            return False
        return (
            request.user.status == 'active' and
            request.user.merchant.status == 'active'
        )


class IsAvailableStaff(permissions.BasePermission):
    """仅可接单状态的员工可访问"""

    message = '员工当前无法接单'

    def has_permission(self, request, view):
        if not isinstance(request.user, Staff):
            return False
        return request.user.is_available


class IsStaffResourceOwner(permissions.BasePermission):
    """
    员工资源所有者权限
    检查员工是否有权操作某个资源（如自己的订单）

    要求对象有 staff 或 staff_id 属性
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        if not isinstance(request.user, Staff):
            return False

        # 检查资源归属
        resource_staff_id = getattr(obj, 'staff_id', None)
        if resource_staff_id:
            return resource_staff_id == request.user.id

        resource_staff = getattr(obj, 'staff', None)
        if resource_staff:
            return resource_staff.id == request.user.id

        return False


class IsStaffOfSameMerchant(permissions.BasePermission):
    """
    同商家员工权限
    检查员工是否与资源属于同一商家

    要求对象有 merchant 或 merchant_id 属性
    """

    message = '您无权操作其他商家的资源'

    def has_object_permission(self, request, view, obj):
        if not isinstance(request.user, Staff):
            return False

        # 获取资源所属商家ID
        resource_merchant_id = getattr(obj, 'merchant_id', None)
        if resource_merchant_id:
            return resource_merchant_id == request.user.merchant_id

        resource_merchant = getattr(obj, 'merchant', None)
        if resource_merchant:
            return resource_merchant.id == request.user.merchant_id

        return False


# ============================================================
# 商家或员工权限（新增）
# ============================================================

class IsMerchantOrStaff(permissions.BasePermission):
    """商家（主账号/子账号）或员工可访问"""

    message = '此接口仅对商家和员工开放'

    def has_permission(self, request, view):
        # 商家主账号
        if isinstance(request.user, Merchant):
            return request.user.status != 'closed'
        # 商家子账号
        if isinstance(request.user, MerchantSubAccount):
            return request.user.is_active and request.user.merchant.status != 'closed'
        # 员工
        if isinstance(request.user, Staff):
            return (
                request.user.status == 'active' and
                request.user.merchant.status != 'closed'
            )
        return False


class IsMerchantOrStaffResourceOwner(permissions.BasePermission):
    """
    商家或员工资源所有者权限
    商家可以操作本店所有资源，员工只能操作自己的资源

    要求对象有 merchant/merchant_id 和 staff/staff_id 属性
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 商家主账号 - 可操作本店所有资源
        if isinstance(request.user, Merchant):
            resource_merchant_id = getattr(obj, 'merchant_id', None)
            if resource_merchant_id:
                return resource_merchant_id == request.user.id
            resource_merchant = getattr(obj, 'merchant', None)
            if resource_merchant:
                return resource_merchant.id == request.user.id
            return False

        # 商家子账号 - 可操作本店所有资源
        if isinstance(request.user, MerchantSubAccount):
            resource_merchant_id = getattr(obj, 'merchant_id', None)
            if resource_merchant_id:
                return resource_merchant_id == request.user.merchant_id
            resource_merchant = getattr(obj, 'merchant', None)
            if resource_merchant:
                return resource_merchant.id == request.user.merchant_id
            return False

        # 员工 - 只能操作自己的资源
        if isinstance(request.user, Staff):
            # 先检查是否是同一商家
            resource_merchant_id = getattr(obj, 'merchant_id', None)
            if resource_merchant_id and resource_merchant_id != request.user.merchant_id:
                return False

            # 再检查是否是自己的资源
            resource_staff_id = getattr(obj, 'staff_id', None)
            if resource_staff_id:
                return resource_staff_id == request.user.id

            resource_staff = getattr(obj, 'staff', None)
            if resource_staff:
                return resource_staff.id == request.user.id

            # 如果资源没有 staff 字段（如商品），则同商家即可
            return True

        return False


# ============================================================
# 组合权限（多角色场景）
# ============================================================

class IsUserOrManager(permissions.BasePermission):
    """用户或管理员可访问"""

    def has_permission(self, request, view):
        if isinstance(request.user, User):
            return request.user.is_active and not request.user.is_banned
        if isinstance(request.user, Manager):
            return request.user.status == 'active'
        return False


class IsOwnerOrManager(permissions.BasePermission):
    """
    资源所有者或管理员可访问（对象级）
    常用于订单、评价等用户创建但管理员也可管理的资源
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 管理员直接放行
        if isinstance(request.user, Manager) and request.user.status == 'active':
            return True

        # 用户需检查所有权
        if isinstance(request.user, User):
            owner_id = getattr(obj, 'user_id', None)
            if owner_id:
                return owner_id == request.user.id

        return False


class IsOwnerOrMerchant(permissions.BasePermission):
    """
    资源所有者或相关商家可访问（对象级）
    常用于订单（用户可查看自己的，商家可查看店内的）
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 用户 - 检查是否为订单所有者
        if isinstance(request.user, User):
            owner_id = getattr(obj, 'user_id', None)
            if owner_id:
                return owner_id == request.user.id
            return False

        # 商家 - 检查是否为订单所属商家
        if isinstance(request.user, Merchant):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.id
            return False

        # 商家子账号
        if isinstance(request.user, MerchantSubAccount):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.merchant_id
            return False

        return False


class IsOwnerOrMerchantOrStaff(permissions.BasePermission):
    """
    资源所有者、相关商家或服务员工可访问（对象级）
    适用于服务订单场景
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 用户 - 检查是否为订单所有者
        if isinstance(request.user, User):
            owner_id = getattr(obj, 'user_id', None)
            if owner_id:
                return owner_id == request.user.id
            return False

        # 商家主账号 - 检查是否为所属商家
        if isinstance(request.user, Merchant):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.id
            return False

        # 商家子账号
        if isinstance(request.user, MerchantSubAccount):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.merchant_id
            return False

        # 员工 - 检查是否为服务员工
        if isinstance(request.user, Staff):
            # 检查是否是同一商家
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id and merchant_id != request.user.merchant_id:
                return False

            # 检查是否是负责该订单的员工
            staff_id = getattr(obj, 'staff_id', None)
            if staff_id:
                return staff_id == request.user.id

            # 如果订单还没分配员工，同商家员工都可以操作
            return True

        return False


class IsOwnerOrMerchantOrManager(permissions.BasePermission):
    """
    资源所有者、相关商家或管理员可访问（对象级）
    最宽松的三方权限，适用于需要用户、商家、平台三方都能操作的场景
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 管理员
        if isinstance(request.user, Manager) and request.user.status == 'active':
            return True

        # 用户
        if isinstance(request.user, User):
            owner_id = getattr(obj, 'user_id', None)
            if owner_id:
                return owner_id == request.user.id
            return False

        # 商家主账号
        if isinstance(request.user, Merchant):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.id
            return False

        # 商家子账号
        if isinstance(request.user, MerchantSubAccount):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.merchant_id
            return False

        return False


class IsOwnerOrMerchantOrStaffOrManager(permissions.BasePermission):
    """
    资源所有者、相关商家、服务员工或管理员可访问（对象级）
    最完整的四方权限，适用于服务订单等复杂场景
    """

    message = '您无权操作此资源'

    def has_object_permission(self, request, view, obj):
        # 管理员
        if isinstance(request.user, Manager) and request.user.status == 'active':
            return True

        # 用户
        if isinstance(request.user, User):
            owner_id = getattr(obj, 'user_id', None)
            if owner_id:
                return owner_id == request.user.id
            return False

        # 商家主账号
        if isinstance(request.user, Merchant):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.id
            return False

        # 商家子账号
        if isinstance(request.user, MerchantSubAccount):
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id:
                return merchant_id == request.user.merchant_id
            return False

        # 员工
        if isinstance(request.user, Staff):
            # 检查是否是同一商家
            merchant_id = getattr(obj, 'merchant_id', None)
            if merchant_id and merchant_id != request.user.merchant_id:
                return False

            # 检查是否是负责该订单的员工
            staff_id = getattr(obj, 'staff_id', None)
            if staff_id:
                return staff_id == request.user.id

            return True

        return False


# ============================================================
# 宠物 / 服务记录权限（原 pet.permissions 迁入）
# ============================================================

class IsServiceProvider(permissions.BasePermission):
    """宠物服务记录权限（对象级）

    - 宠物主人（User）：可读，且仅能执行 add_feedback（添加反馈/评分），不能改服务记录本身；
    - 服务人员（Staff）：可读写自己负责订单（related_order.staff）的服务记录。

    依赖 PetServiceRecord 的两个属性：
        obj.pet              -> related_order.pets.first()
        obj.service_provider -> related_order.staff

    说明：用 isinstance 区分 User / Staff，避免两类模型主键数值偶然相等时的误判，
    同时不依赖 request.user.is_authenticated（Staff 主体不一定有该属性）。
    """

    message = '您无权操作此服务记录'

    def has_permission(self, request, view):
        # 仅宠物主人或服务人员可进入；匿名/其它角色一律拒绝
        return isinstance(request.user, (User, Staff))

    def has_object_permission(self, request, view, obj):
        user = request.user
        pet = obj.pet

        # 宠物主人：只读 + add_feedback
        if isinstance(user, User) and pet and pet.owner_id == user.id:
            return request.method in permissions.SAFE_METHODS or view.action == 'add_feedback'

        # 服务人员：本人负责的订单可读写
        provider = obj.service_provider
        if isinstance(user, Staff) and provider and provider.id == user.id:
            return True

        return False


class ReadOnly(permissions.BasePermission):
    """
    只读权限，仅允许 GET、HEAD、OPTIONS 请求
    通常与其他权限组合使用
    """

    SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

    def has_permission(self, request, view):
        return request.method in self.SAFE_METHODS


# ============================================================
# 辅助函数
# ============================================================

def get_merchant_id_from_request(request):
    """
    从请求中获取商家ID
    支持商家主账号、子账号、员工
    """
    user = request.user

    if isinstance(user, Merchant):
        return user.id
    elif isinstance(user, MerchantSubAccount):
        return user.merchant_id
    elif isinstance(user, Staff):
        return user.merchant_id
    elif hasattr(user, '_merchant'):
        return user._merchant.id

    return None


def is_merchant_role(user):
    """检查用户是否为商家角色（主账号、子账号或员工）"""
    return isinstance(user, (Merchant, MerchantSubAccount, Staff))


def get_user_type(user):
    """获取用户类型字符串"""
    if isinstance(user, User):
        return 'user'
    elif isinstance(user, Manager):
        return 'manager'
    elif isinstance(user, Merchant):
        return 'merchant'
    elif isinstance(user, MerchantSubAccount):
        return 'merchant_sub'
    elif isinstance(user, Staff):
        return 'staff'
    return 'unknown'