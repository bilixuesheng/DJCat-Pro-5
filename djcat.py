import sys
import traceback
from loguru import logger
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from PySide6.QtCore import QStandardPaths
from qfluentwidgets import qconfig, setThemeColor

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.view.main_window import MainWindow

# 【新增】全局异常拦截器
def exceptionHook(exc_type, exc_value, exc_traceback):
    exc_info = (exc_type, exc_value, exc_traceback)
    message = "".join(traceback.format_exception(*exc_info)).rstrip()
    
    # 1. 记录到日志文件中
    logger.opt(exception=exc_info).error("未处理的程序异常")

    # 2. 发送信号给主界面弹出提示框
    try:
        signalBus.catchException.emit(message)
    except Exception:
        pass

    # 3. 继续调用系统默认的报错钩子，确保控制台也能看到报错
    if "__compiled__" not in globals():
        sys.__excepthook__(*exc_info)


def main():
    # 修改日志路径，加上 "Log/" 文件夹前缀。
    # retention="7 days" 会在每次启动或按天切割时，自动帮你把7天前的文件删掉。
    logger.add("Log/djcatpro日志_{time:YYYY-MM-DD}.log", rotation="00:00", retention="7 days", enqueue=True, encoding="utf-8")
    sys.excepthook = exceptionHook

    app = QApplication(sys.argv)
    
    appLocalDataLocation = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    config_path = f"{appLocalDataLocation}/DJCatPro/UserConfig.json"
    
    qconfig.load(config_path, cfg)
    setThemeColor(QColor(49, 101, 49))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
