from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    catchException = Signal(str)
    testAudio = Signal(dict)
    installLocationStateChanged = Signal(str)
    # App Font 换完之后发出：控件都已换上新字体，按字体量尺寸或缓存了画面的地方重算。
    appFontChanged = Signal()


signalBus = SignalBus()
