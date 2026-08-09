from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    catchException = Signal(str)
    testAudio = Signal(dict)
    homeCardsChanged = Signal()
    appStoreCacheCleared = Signal()


signalBus = SignalBus()
