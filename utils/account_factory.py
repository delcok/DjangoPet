# -*- coding: utf-8 -*-
# @Time    : 2026/4/18 11:11
# @Author  : Delock

from django.db import transaction

from user.models import User
from merchants.models import Merchant
from wallet.models import (
    UserWallet,
    MerchantWallet,
    MerchantSettlementConfig,
    WalletTransaction,          # ← 新增导入
)

# 商家默认初始密码(首次登录后需自行修改)
DEFAULT_MERCHANT_PASSWORD = '123456'

# 新用户注册奖励金币
NEW_USER_REGISTER_GOLD = 100


@transaction.atomic
def register_user(**kwargs) -> User:
    """
    注册用户 —— 建账号 + 开钱包 + 发放注册奖励金币。
    """
    user = User.objects.create(**kwargs)
    wallet = UserWallet.objects.create(user=user)

    # 新用户注册奖励：发放金币（GOLD_GRANT 为金币入账动作）
    if NEW_USER_REGISTER_GOLD > 0:
        wallet.change_gold(
            amount=NEW_USER_REGISTER_GOLD,
            action=WalletTransaction.Action.GOLD_GRANT,
            operator_id=user.id,
            operator_role='system',
            related_type='register',
            related_id=user.id,
            remark=f'新用户注册奖励 +{NEW_USER_REGISTER_GOLD}',
            idempotent_key=f'register_reward_{user.id}',
        )

    return user


@transaction.atomic
def onboard_merchant(**kwargs) -> Merchant:
    """
    商家入驻 —— 建商家 + 开钱包 + 初始化结算配置。

    密码处理：默认使用 DEFAULT_MERCHANT_PASSWORD，调用方也可显式传入 password 覆盖。
    密码一律经 set_password() 加密后入库。
    """
    raw_password = kwargs.pop('password', None) or DEFAULT_MERCHANT_PASSWORD
    kwargs.setdefault('status', Merchant.Status.DRAFT)

    merchant = Merchant(**kwargs)
    merchant.set_password(raw_password)
    merchant.save()

    MerchantWallet.objects.create(merchant=merchant)
    MerchantSettlementConfig.objects.create(merchant=merchant)
    return merchant