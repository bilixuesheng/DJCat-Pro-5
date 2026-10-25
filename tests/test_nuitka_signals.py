from __future__ import annotations

import gc
import weakref

from PySide6.QtCore import SignalInstance

from app.platform import nuitka_signals


class _Receiver:
    def onChanged(self):
        pass


class _CompiledMethod:
    """Stands in for a Nuitka compiled bound method: `im_func` plus a hold on `im_self`."""

    def __init__(self, receiver):
        self.im_self = receiver
        self.im_func = type(receiver).onChanged


def _nuitkaNamespace():
    # 照 Nuitka PySide6 插件注入的 post-import 代码：protect() 把交进来的方法追加到模块级 _protected。
    namespace = {"_protected": []}
    exec("def connect(self, slot):\n    _protected.append(slot)\n", namespace)
    return namespace


def test_connected_receiver_is_freed_once_patched():
    namespace = _nuitkaNamespace()
    nuitka_signals.releaseSignalReceivers(namespace["connect"])
    receiver = _Receiver()
    alive = weakref.ref(receiver)

    namespace["connect"](None, _CompiledMethod(receiver))
    del receiver
    gc.collect()

    assert alive() is None
    assert list(namespace["_protected"]) == [_Receiver.onChanged]


def test_receivers_protected_before_the_patch_are_released_too():
    namespace = _nuitkaNamespace()
    receiver = _Receiver()
    alive = weakref.ref(receiver)
    namespace["connect"](None, _CompiledMethod(receiver))

    nuitka_signals.releaseSignalReceivers(namespace["connect"])
    del receiver
    gc.collect()

    assert alive() is None


def test_each_function_is_kept_once_however_often_it_connects():
    namespace = _nuitkaNamespace()
    nuitka_signals.releaseSignalReceivers(namespace["connect"])

    for _ in range(50):
        namespace["connect"](None, _CompiledMethod(_Receiver()))

    assert list(namespace["_protected"]) == [_Receiver.onChanged]


def test_functions_from_a_fixed_nuitka_are_kept_as_they_are():
    namespace = _nuitkaNamespace()
    nuitka_signals.releaseSignalReceivers(namespace["connect"])

    namespace["connect"](None, _Receiver.onChanged)

    assert list(namespace["_protected"]) == [_Receiver.onChanged]


def test_patching_twice_keeps_the_same_list():
    namespace = _nuitkaNamespace()
    nuitka_signals.releaseSignalReceivers(namespace["connect"])
    patched = namespace["_protected"]

    nuitka_signals.releaseSignalReceivers(namespace["connect"])

    assert namespace["_protected"] is patched


def test_running_from_source_leaves_pyside_alone():
    nuitka_signals.releaseSignalReceivers()

    assert not hasattr(SignalInstance.connect, "__globals__")
