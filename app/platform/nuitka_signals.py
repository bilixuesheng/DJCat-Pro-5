"""Let the packaged build free widgets that connected their methods to signals.

Nuitka's PySide6 plugin wraps ``SignalInstance.connect``, ``disconnect`` and
``QTimer.singleShot``: every compiled bound method passed to them is appended to a
module-level ``_protected`` list that is never emptied (Nuitka/Nuitka#4108, present in
the 4.1.3 we build with). A bound method holds its receiver, so every widget that ever
connected one of its own methods stays alive with everything it references, such as a
Display Window's background image or a Window Transition's snapshots. The list only has
to keep the compiled functions alive, so it is swapped for one that keeps the function
and drops the receiver. Running from source there is no such list and this does nothing.
"""

from PySide6.QtCore import SignalInstance


class _FunctionRefs(list):
    def __init__(self, methods=()):
        super().__init__()
        self._functions = set()
        for method in methods:
            self.append(method)

    def append(self, method) -> None:
        # Nuitka 修好 #4108 之后交进来的已经是函数本身。
        function = getattr(method, "im_func", method)
        # 每次 connect 都会交一次，同一个函数只留一份，列表不随开关窗口的次数增长。
        if function in self._functions:
            return
        self._functions.add(function)
        super().append(function)


def releaseSignalReceivers(connect=None) -> None:
    # 调用时再取：Nuitka 在 PySide6 导入完成后才换掉 connect。
    namespace = getattr(connect or SignalInstance.connect, "__globals__", None)
    if not isinstance(namespace, dict):
        return
    protected = namespace.get("_protected")
    if isinstance(protected, list) and not isinstance(protected, _FunctionRefs):
        namespace["_protected"] = _FunctionRefs(protected)
