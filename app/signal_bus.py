from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    catchException = Signal(str)
    testAudio = Signal(dict)
    installLocationStateChanged = Signal(str)
    # App Font 换完之后发出：控件都已换上新字体，按字体量尺寸或缓存了画面的地方重算。
    appFontChanged = Signal()
    # Time Sync 的进度或结果变了；设置页据此重读 time_sync.timeSyncState()。
    timeSyncStateChanged = Signal()
    # 设置页的「立即同步」，由 MainWindow 的 TimeSync 接手。
    timeSyncRequested = Signal()


signalBus = SignalBus()
