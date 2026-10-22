"""Time Sync：向时间服务器问标准时间，校准 Calibrated Time。

只问 NTP（UDP 123），不改 Windows 系统时钟，理由见 docs/adr/0012-djcat-time.md。启动时、此后每小时、
换了时间服务器、点「立即同步」，以及发现 Windows 时钟被改或电脑刚从睡眠醒来时各同步一次。同步失败时，
本次运行里成功过就继续用上次的结果，从没成功过就是系统时间；结果不存盘。
"""

from __future__ import annotations

import os
import socket
import struct
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime

from loguru import logger
from PySide6.QtCore import QObject, QTimer, Signal

from app.common.clock import Clock, calibratedClock
from app.config.cfg import CUSTOM_TIME_SERVER, TIME_SERVERS, cfg
from app.signal_bus import signalBus

NTP_PORT = 123
NTP_EPOCH_OFFSET = 2208988800
SAMPLES = 4
SAMPLE_TIMEOUT = 2.0
SYNC_INTERVAL_MS = 60 * 60 * 1000
WATCH_INTERVAL_MS = 5000
# 系统时钟和计数器走的差了这么多，就是有人改了 Windows 时间（或系统自己对了一次时）。
CLOCK_CHANGE_SECONDS = 1.0
# 两次检查之间计数器走了这么久，就是电脑睡过一觉。
SLEEP_GAP_SECONDS = 60.0
# 自定义服务器边打字边存，停手这么久才去问，打到一半的地址不用去解析。
SERVER_CHANGE_DELAY_MS = 1000


class NtpError(Exception):
    pass


@dataclass(frozen=True)
class NtpSample:
    epoch: float  # 计数器读数为 counter 的那一刻的标准时间
    counter: float
    delay: float  # 一来一回在路上花的时间


def _ntpTime(packet: bytes, offset: int) -> float:
    seconds, fraction = struct.unpack_from("!II", packet, offset)
    if not seconds & 0x80000000:
        # 2036 年 2 月起 NTP 的秒数从 0 重新数（第 1 纪元）。
        seconds += 2**32
    return seconds - NTP_EPOCH_OFFSET + fraction / 2**32


def _sample(sock, address, host: str, timeout: float, counter) -> NtpSample:
    request = bytearray(48)
    request[0] = (4 << 3) | 3  # 版本 4，客户端
    # 发送时间填随机数（RFC 9109）：服务器原样抄回，用来认出这一问的回答。
    token = os.urandom(8)
    request[40:48] = token
    sent = counter()
    try:
        sock.sendto(request, address)
    except OSError as error:
        raise NtpError(f"连不上 {host}") from error
    # 别处发来的包不算数，但也不能让它们一个接一个地把等待拖长。
    deadline = time.monotonic() + timeout
    while True:
        try:
            sock.settimeout(max(0.0, deadline - time.monotonic()) or 0.001)
            packet, _ = sock.recvfrom(512)
        except OSError as error:
            raise NtpError(f"连不上 {host}") from error
        if len(packet) >= 48 and packet[24:32] == token:
            break
    received = counter()
    leap, mode, stratum = packet[0] >> 6, packet[0] & 7, packet[1]
    if mode != 4 or packet[40:48] == bytes(8):
        raise NtpError(f"{host} 的回应无效")
    if leap == 3 or not 1 <= stratum <= 15:
        raise NtpError(f"{host} 自己还没有对准标准时间")
    serverReceived, serverSent = _ntpTime(packet, 32), _ntpTime(packet, 40)
    delay = max(0.0, (received - sent) - (serverSent - serverReceived))
    return NtpSample(serverSent + delay / 2, received, delay)


def queryNtp(
    host: str,
    port: int = NTP_PORT,
    samples: int = SAMPLES,
    timeout: float = SAMPLE_TIMEOUT,
    counter=time.perf_counter,
) -> NtpSample:
    """问几次，取一来一回最快的那一次：路上越快，"往返各占一半"的估计越准。"""
    if not host:
        raise NtpError("没有填写时间服务器")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except (OSError, UnicodeError) as error:
        raise NtpError(f"找不到 {host}") from error
    # 不少教室网络没有 IPv6，有 IPv4 地址就先用它。
    addresses.sort(key=lambda entry: entry[0] != socket.AF_INET)
    family, socketType, proto, _, address = addresses[0]
    best = None
    failure = None
    with socket.socket(family, socketType, proto) as sock:
        for _ in range(samples):
            try:
                sample = _sample(sock, address, host, timeout, counter)
            except NtpError as error:
                failure = error
                continue
            if best is None or sample.delay < best.delay:
                best = sample
    if best is None:
        raise failure
    return best


def timeServerHost() -> str:
    name = cfg.timeServer.value
    if name == CUSTOM_TIME_SERVER:
        return cfg.customTimeServer.value.strip()
    return dict(TIME_SERVERS).get(name, TIME_SERVERS[0][1])


@dataclass(frozen=True)
class TimeSyncState:
    syncing: bool = False
    syncedAt: datetime | None = None  # 上次成功同步时的 Calibrated Time
    deviation: float | None = None  # 那次测出的系统时钟比标准时间慢多少秒（负数是快）
    error: str = ""  # 最近一次失败的原因；之后成功了就清空


_state = TimeSyncState()


def timeSyncState() -> TimeSyncState:
    return _state


def _setState(state: TimeSyncState) -> None:
    global _state
    _state = state
    signalBus.timeSyncStateChanged.emit()


class TimeSync(QObject):
    """MainWindow 创建并 start()，退出时 shutdown()；设置页经 signalBus 请求同步、读 timeSyncState()。"""

    _finished = Signal(int, object, object)

    def __init__(
        self,
        parent=None,
        query=None,
        clock: Clock = calibratedClock,
        systemTime=time.time,
        counter=time.perf_counter,
    ):
        super().__init__(parent)
        self._query = query
        self._clock = clock
        self._systemTime = systemTime
        self._counter = counter
        self._generation = 0
        self._running = False
        self._resyncPending = False
        self._shutdown = False
        self._lastWatch = (systemTime(), counter())
        self._periodicTimer = QTimer(self)
        self._periodicTimer.setInterval(SYNC_INTERVAL_MS)
        self._watchTimer = QTimer(self)
        self._watchTimer.setInterval(WATCH_INTERVAL_MS)
        self._serverTimer = QTimer(self)
        self._serverTimer.setSingleShot(True)
        self._periodicTimer.timeout.connect(self.syncNow)
        self._watchTimer.timeout.connect(self._watch)
        self._serverTimer.timeout.connect(self.syncNow)
        self._finished.connect(self._onFinished)

    def start(self) -> None:
        cfg.timeSyncEnabled.valueChanged.connect(self._onEnabledChanged)
        cfg.timeServer.valueChanged.connect(self._onServerChanged)
        cfg.customTimeServer.valueChanged.connect(self._onServerChanged)
        signalBus.timeSyncRequested.connect(self.syncNow)
        self._periodicTimer.start()
        self._watchTimer.start()
        self.syncNow()

    def shutdown(self) -> None:
        self._shutdown = True
        self._generation += 1
        for timer in (self._periodicTimer, self._watchTimer, self._serverTimer):
            timer.stop()

    def syncNow(self) -> None:
        if self._shutdown or not cfg.timeSyncEnabled.value:
            return
        if self._running:
            self._resyncPending = True
            return
        self._running = True
        self._resyncPending = False
        _setState(replace(_state, syncing=True))
        host = timeServerHost()
        threading.Thread(
            target=self._run, args=(self._generation, host), daemon=True
        ).start()

    def _run(self, generation: int, host: str) -> None:
        query = self._query or queryNtp
        try:
            result, error = query(host), None
        except NtpError as failure:
            result, error = None, str(failure)
        except Exception as failure:  # noqa: BLE001 - 校时失败不能拖垮程序
            logger.exception("网络校时出错")
            result, error = None, f"同步出错：{failure}"
        try:
            self._finished.emit(generation, result, error)
        except RuntimeError:
            pass  # TimeSync 已随主窗口销毁

    def _onFinished(self, generation: int, result, error) -> None:
        self._running = False
        if generation != self._generation:
            self.syncNow()
            return
        if result is None:
            logger.warning("网络校时失败：{}", error)
            _setState(replace(_state, syncing=False, error=error))
        else:
            self._clock.synchronize(result.epoch, result.counter)
            deviation = self._clock.deviation()
            logger.info(
                "网络校时：标准时间比系统时间快 {:+.3f} 秒，往返 {:.0f} ms",
                deviation,
                result.delay * 1000,
            )
            _setState(TimeSyncState(False, self._clock.now(), deviation, ""))
        if self._resyncPending:
            self.syncNow()

    def _onEnabledChanged(self, enabled: bool) -> None:
        if self._shutdown:
            return
        self._generation += 1
        if enabled:
            self.syncNow()
            return
        self._serverTimer.stop()
        self._clock.forget()
        _setState(TimeSyncState())

    def _onServerChanged(self, _value=None) -> None:
        if not self._shutdown:
            self._serverTimer.start(SERVER_CHANGE_DELAY_MS)

    def _watch(self) -> None:
        system, counter = self._systemTime(), self._counter()
        lastSystem, lastCounter = self._lastWatch
        self._lastWatch = (system, counter)
        elapsed = counter - lastCounter
        if (
            abs((system - lastSystem) - elapsed) > CLOCK_CHANGE_SECONDS
            or elapsed > SLEEP_GAP_SECONDS
        ):
            self.syncNow()
