import gc
import os

import pytest

# 必须早于任何测试模块导入 PySide6。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

qtApplication = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def collectEarlierGarbage():
    # 前面测试留下的无父控件若在 QFluentWidgets 遍历样式表登记时被回收，销毁信号会从
    # 正在遍历的字典里删项（dictionary changed size during iteration）。先在测试开始前回收掉。
    gc.collect()
