import os

# 必须早于任何测试模块导入 PySide6。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

qtApplication = QApplication.instance() or QApplication([])
