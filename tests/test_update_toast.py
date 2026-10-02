from __future__ import annotations

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import InfoBarIcon

from app.view.components.update_toast import UpdateToast

WIDEST = "100% · 1023.9 MB / 1023.9 MB · 1023.9 MB/s"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance()


@pytest.fixture
def host(app):
    parent = QWidget()
    parent.resize(900, 420)
    parent.show()
    yield parent
    parent.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def rightEdge(toast):
    return toast.x() + toast.width()


def finishAnimation(animation):
    # 直接拨到终点，不等 Qt 的动画时钟：整套测试里前面的用例可能让全局动画驱动停摆，
    # 定时器和排队调用照常，动画却一帧不走。
    if animation is not None and animation.state() == QAbstractAnimation.State.Running:
        animation.setCurrentTime(animation.duration())


def settle(toast):
    """让 InfoBarManager 的滑入动画走完，卡片落到它的终点。"""
    finishAnimation(toast.property("slideAni"))


def testDownloadingReservesWidthAndHasNoCloseButton(host):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    settle(toast)
    width = toast.width()

    toast.setDownloadProgress("1% · 0.2 MB / 20.0 MB · 9.9 KB/s", 1)
    toast.setDownloadProgress(WIDEST, 100)
    toast.setDownloadProgress("下载失败，正在重试 1/3...")
    QTest.qWait(50)

    assert toast.isVisible()
    assert toast.closeButton.isHidden()
    assert toast._buttonBox.isHidden()
    assert toast.width() == width
    assert rightEdge(toast) == host.width() - 24


def testProgressAnimatesAndFallsBackToIndeterminate(host):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    assert toast._progress is None
    assert toast._indeterminateTimer.isActive()

    toast.setDownloadProgress("40%", 40)
    assert toast._progress == 40
    assert not toast._indeterminateTimer.isActive()
    animation = toast._progressAnimation
    assert animation.duration() == 150
    animation.setCurrentTime(75)
    assert 0 < toast._displayProgress < 40
    halfway = toast._displayProgress

    # 动画途中又来新进度：从当前显示值接着追，不从 0 重放。
    toast.setDownloadProgress("60%", 60)
    assert animation.startValue() == halfway
    finishAnimation(animation)
    assert toast._displayProgress == 60

    toast.setDownloadProgress("下载失败，正在重试 1/3...")
    assert toast._progress is None
    assert toast._displayProgress == 0
    assert toast._indeterminateTimer.isActive()


@pytest.mark.parametrize(
    "steps",
    [
        ("finish", "fail", "finish"),
        ("fail", "finish", "fail"),
        ("finish", "start", "finish"),
    ],
)
def testStateChangesFitTheCardToItsContent(host, steps):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    settle(toast)
    for step in steps:
        if step == "finish":
            toast.finishDownload("v5.3.0 下载完成", "是否立即安装更新？")
        elif step == "fail":
            toast.failDownload("更新下载失败", "HTTP 503")
        else:
            toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
        QTest.qWait(50)
        # 换状态后卡片应当正好是新内容的宽度，并且右边仍贴着父窗口内侧 24 px。
        assert toast.width() == toast.sizeHint().width()
        assert rightEdge(toast) == host.width() - 24


def testFinishedAndFailedStatesShowTheirOwnButtons(host):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)

    toast.finishDownload("v5.3.0 下载完成", "是否立即安装更新？")
    assert toast.iconWidget.icon is InfoBarIcon.SUCCESS
    assert not toast.installButton.isHidden()
    assert not toast.laterButton.isHidden()
    assert toast.retryButton.isHidden()
    assert not toast.closeButton.isHidden()

    toast.failDownload("更新下载失败", "HTTP 503")
    assert toast.iconWidget.icon is InfoBarIcon.ERROR
    assert toast.installButton.isHidden()
    assert toast.laterButton.isHidden()
    assert not toast.retryButton.isHidden()
    assert not toast.closeButton.isHidden()
    assert toast.contentLabel.text() == "HTTP 503"
    assert not toast._indeterminateTimer.isActive()


def testProgressUpdatesAfterFinishingAreIgnored(host):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    toast.finishDownload("v5.3.0 下载完成", "是否立即安装更新？")

    toast.setDownloadProgress("99%", 99)

    assert toast.contentLabel.text() == "是否立即安装更新？"
    assert not toast._indeterminateTimer.isActive()


def testButtonsEmitAndLaterCloses(host):
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    toast.finishDownload("v5.3.0 下载完成", "是否立即安装更新？")
    installs = []
    retries = []
    closed = []
    toast.installClicked.connect(lambda: installs.append(True))
    toast.retryClicked.connect(lambda: retries.append(True))
    toast.closedSignal.connect(lambda: closed.append(True))

    toast.installButton.click()
    toast.failDownload("更新下载失败", "HTTP 503")
    toast.retryButton.click()
    toast.finishDownload("v5.3.0 下载完成", "是否立即安装更新？")
    toast.laterButton.click()

    assert installs == [True]
    assert retries == [True]
    assert closed == [True]


def testStateChangeDuringSlideInLandsAtTheNewSize(host):
    # 例如下载一开始就失败：滑入动画还没停，卡片就换了尺寸。动画的终点必须跟着改，
    # 否则最后几帧会把卡片拉回按旧宽度算的位置。
    toast = UpdateToast(host)
    toast.startDownload("正在下载更新 v5.3.0", "正在连接下载服务器...", WIDEST)
    assert toast.property("slideAni").state() == QAbstractAnimation.State.Running
    toast.failDownload("更新下载失败", "HTTP 403")

    settle(toast)

    assert rightEdge(toast) == host.width() - 24
