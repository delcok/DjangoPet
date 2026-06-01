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
)

# 商家默认初始密码(首次登录后需自行修改)
DEFAULT_MERCHANT_PASSWORD = '123456'


@transaction.atomic
def register_user(**kwargs) -> User:
    """
    注册用户 —— 建账号 + 开钱包。
    """
    user = User.objects.create(**kwargs)
    UserWallet.objects.create(user=user)
    return user


@transaction.atomic
def onboard_merchant(**kwargs) -> Merchant:
    """
    商家入驻 —— 建商家 + 开钱包 + 初始化结算配置。

    密码处理：默认使用 DEFAULT_MERCHANT_PASSWORD，调用方也可显式传入 password 覆盖。
    密码一律经 set_password() 加密后入库。
    """
    raw_password = kwargs.pop('password', None) or DEFAULT_MERCHANT_PASSWORD

    merchant = Merchant(**kwargs)
    merchant.set_password(raw_password)
    merchant.save()

    MerchantWallet.objects.create(merchant=merchant)
    MerchantSettlementConfig.objects.create(merchant=merchant)
    return merchant