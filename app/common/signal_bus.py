from PySide6.QtCore import QObject, Signal

class SignalBus(QObject):
    # 捕获异常的信号
    catchException = Signal(str)

signalBus = SignalBus()
