"""不经过 `QWidget.screen()` 取窗口所在的屏幕。

PySide 对"返回一个没有父对象的 QObject 指针"的方法启用返回值启发式：`QWidget.screen()`
（以及 `QWindow.screen()`）返回的 QScreen 包装对象会被登记成这个控件的子对象。控件销毁时
shiboken 把全局 QScreen 当子对象一并作废，之后的父子关系处理还会把所有权交给 Python；
这个包装对象一被回收，shiboken 就 delete 掉 Qt 仍在屏幕列表里使用的 QScreen，下一次任何
控件取屏幕时崩溃。投送、倒计时和全屏时钟窗口会反复创建和销毁，正是这条路径。

`screenAt()` 和 `primaryScreen()` 是静态方法，没有 self 可挂，不触发这条启发式。
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget


def screenFor(widget: QWidget) -> QScreen:
    """`widget` 所在窗口的屏幕；窗口还没有落在任何屏幕上时退回主屏幕。"""
    window = widget.window()
    return (
        QGuiApplication.screenAt(window.frameGeometry().center())
        or QGuiApplication.primaryScreen()
    )
