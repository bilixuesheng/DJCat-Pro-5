import re
import sys
from datetime import date

import pytest

from app.common import anti_popup_block as apb
from app.config.constants import APP_NAME

NAME_PATTERN = re.compile(r"^[A-Za-z]+ [2-9]$")
TODAY = date(2026, 11, 27)
AUTO, MANUAL = apb.MODE_AUTO, apb.MODE_MANUAL


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


def testCustomNameTrimsAndRejectsEmptyOrHonest():
    assert apb.normalizeCustomName("  SmartClass 4  ") == "SmartClass 4"
    assert apb.normalizeCustomName("") is None
    assert apb.normalizeCustomName("   ") is None
    # 等于诚实名（含去空格后相等）→ 不合格。
    assert apb.normalizeCustomName("电教猫 Pro 5") is None
    assert apb.normalizeCustomName("  电教猫 Pro 5 ") is None
    # 最低校验：不拦中文，填含中文的名字是用户自担的选择。
    assert apb.normalizeCustomName("电教猫Helper") == "电教猫Helper"


def testNoRotationWhenDisabledOrManual():
    assert apb.startupRotationPlan(False, AUTO, 3, "2026-01-01", TODAY) == (False, None)
    assert apb.startupRotationPlan(True, MANUAL, 3, "2026-01-01", TODAY) == (False, None)


def testMissingBaselineIsEstablishedWithoutRotating():
    # 旧配置/首次没有基线：只建立基线、本次不换，免得升级后立刻轮换。
    assert apb.startupRotationPlan(True, AUTO, 3, "", TODAY) == (False, TODAY)
    assert apb.startupRotationPlan(True, AUTO, 3, "garbage", TODAY) == (False, TODAY)


def testRotatesOnlyWhenIntervalElapsed():
    # 未到点不动。
    assert apb.startupRotationPlan(True, AUTO, 3, "2026-11-25", TODAY) == (False, None)
    # 当天即基线 → 未到点。
    assert apb.startupRotationPlan(True, AUTO, 3, "2026-11-27", TODAY) == (False, None)
    # 刚好到点、超期都换，并把基线重设为今天。
    assert apb.startupRotationPlan(True, AUTO, 3, "2026-11-24", TODAY) == (True, TODAY)
    # 错过多个周期也只换一次（返回单个 today）。
    assert apb.startupRotationPlan(True, AUTO, 3, "2026-10-01", TODAY) == (True, TODAY)
    # 带时间戳的 ISO 也能解析。
    assert apb.startupRotationPlan(
        True, AUTO, 3, "2026-11-24T08:00:00", TODAY
    ) == (True, TODAY)


def testBaselineInFutureIsTreatedAsClockResetAndRotates():
    # 主板电池没电、时钟被重置 → 立即换并重设基线。
    assert apb.startupRotationPlan(True, AUTO, 3, "2027-01-01", TODAY) == (True, TODAY)


def testIntervalFallsBackToOneDayWhenNonPositive():
    assert apb.startupRotationPlan(True, AUTO, 0, "2026-11-26", TODAY) == (True, TODAY)
    assert apb.startupRotationPlan(True, AUTO, -5, "2026-11-26", TODAY) == (True, TODAY)


@pytest.mark.skipif(sys.platform == "win32", reason="仅在非 Windows 上验证安全回退")
def testProductNameReadReturnsNoneOffWindows():
    assert apb.exeProductName() is None
