from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent
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


def settle(toast):
    # 等 InfoBarManager 的滑入动画把卡片送到右下角。动画名义上 200 ms，但整套测试跑满时
    # 定时器会被拖慢，固定等一段时间不可靠。
    deadline = time.monotonic() + 3
    while rightEdge(toast) != toast.parentWidget().width() - 24:
        assert time.monotonic() < deadline, "Update Toast 没有滑到右下角"
        QTest.qWait(10)


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
    QTest.qWait(30)
    assert 0 < toast._displayProgress < 40
    QTest.qWait(250)
    assert toast._displayProgress == 40

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
    toast.failDownload("更新下载失败", "HTTP 403")

    settle(toast)
    QTest.qWait(300)

    assert rightEdge(toast) == host.width() - 24
