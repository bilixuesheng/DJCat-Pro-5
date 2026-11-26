import re
import sys

import pytest

from app.common import anti_popup_block as apb
from app.config.constants import APP_NAME

NAME_PATTERN = re.compile(r"^[A-Za-z]+ [2-9]$")


def testRandomNameLooksLikeASoftwareName():
    for _ in range(200):
        name = apb.randomDisguisedName()
        assert NAME_PATTERN.fullmatch(name), name


def testRandomNameAvoidsHonestNameAndTheCurrentOne():
    for _ in range(200):
        current = apb.randomDisguisedName()
        nextName = apb.randomDisguisedName(exclude=current)
        assert nextName != current
        assert nextName != APP_NAME
        assert nextName != apb.HONEST_PRODUCT_NAME


def testDesiredNameIsHonestWhenOffAndDisguisedWhenOn():
    assert apb.desiredProductName(False, "Whatever 3") == apb.HONEST_PRODUCT_NAME
    assert apb.desiredProductName(True, "SmartClass 4") == "SmartClass 4"
    # 伪装名空白时退回默认，不会写成空串。
    assert apb.desiredProductName(True, "") == apb.DEFAULT_DISGUISED_NAME
    assert apb.desiredProductName(True, "  Trimmed 5  ") == "Trimmed 5"


def testNeedsReapplyWhenDiskNameDiffersFromDesired():
    # 开着但磁盘还是诚实名（被更新还原）→ 要重套。
    assert apb.needsReapply(True, "DJCat Pro", apb.HONEST_PRODUCT_NAME) is True
    # 开着且已是目标名 → 不动。
    assert apb.needsReapply(True, "DJCat Pro", "DJCat Pro") is False
    # 关着但磁盘还留着伪装名 → 要写回诚实名。
    assert apb.needsReapply(False, "DJCat Pro", "DJCat Pro") is True
    assert apb.needsReapply(False, "DJCat Pro", apb.HONEST_PRODUCT_NAME) is False


def testNeedsReapplyIsFalseWhenNameCannotBeRead():
    # 读不到就不触发，免得反复退出重启。
    assert apb.needsReapply(True, "DJCat Pro", None) is False
    assert apb.needsReapply(False, "DJCat Pro", None) is False


def testTipHiddenWheneverEnabled():
    assert apb.tipShouldShow(True, False, False) is False
    assert apb.tipShouldShow(True, True, True) is False


def testTipVisibilityWhenDisabled():
    assert apb.tipShouldShow(False, False, False) is True
    # 本次 × 关掉。
    assert apb.tipShouldShow(False, False, True) is False
    # 永久「不再显示」。
    assert apb.tipShouldShow(False, True, False) is False


@pytest.mark.skipif(sys.platform == "win32", reason="仅在非 Windows 上验证安全回退")
def testProductNameReadReturnsNoneOffWindows():
    assert apb.exeProductName() is None
