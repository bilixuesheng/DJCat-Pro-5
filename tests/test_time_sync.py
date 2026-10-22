import socket
import struct
import threading
import time
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.common import time_sync
from app.common.clock import Clock
from app.common.time_sync import NtpError, NtpSample, TimeSync, queryNtp, timeSyncState
from app.config.cfg import CUSTOM_TIME_SERVER, cfg
from app.signal_bus import signalBus
from tests.support import isolateCfg

NTP_EPOCH_OFFSET = 2208988800
SERVER_TIME = 1_792_000_000.25


def ntpTimestamp(epoch):
    seconds = epoch + NTP_EPOCH_OFFSET
    whole = int(seconds)
    return struct.pack("!II", whole & 0xFFFFFFFF, int((seconds - whole) * 2**32))


def reply(serverTime, li=0, stratum=2, mode=4, originate=None):
    def build(request):
        header = bytes([(li << 6) | (4 << 3) | mode, stratum, 6, 0xEC])
        return (
            header
            + bytes(12)
            + bytes(8)
            + (request[40:48] if originate is None else originate)
            + ntpTimestamp(serverTime)
            + ntpTimestamp(serverTime)
        )

    return build


class FakeNtpServer:
    def __init__(self, test, replies):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.replies = list(replies)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        test.addCleanup(self.socket.close)

    def _serve(self):
        for build in self.replies:
            try:
                request, address = self.socket.recvfrom(512)
            except OSError:
                return
            packet = build(request)
            if packet is not None:
                self.socket.sendto(packet, address)


def counterReading(*values):
    readings = iter(values)
    return lambda: next(readings)


class QueryNtpTest(TestCase):
    def query(self, server, counter, samples=1, timeout=1.0):
        return queryNtp("127.0.0.1", port=server.port, samples=samples, timeout=timeout, counter=counter)

    def testStandardTimeIsTheServerReplyPlusHalfTheRoundTrip(self):
        server = FakeNtpServer(self, [reply(SERVER_TIME)])

        sample = self.query(server, counterReading(100.0, 100.2))

        self.assertAlmostEqual(sample.epoch, SERVER_TIME + 0.1, places=5)
        self.assertEqual(sample.counter, 100.2)
        self.assertAlmostEqual(sample.delay, 0.2, places=5)

    def testKeepsTheSampleWithTheShortestRoundTrip(self):
        server = FakeNtpServer(
            self,
            [reply(SERVER_TIME), reply(SERVER_TIME + 1), reply(SERVER_TIME + 2)],
        )

        sample = self.query(
            server, counterReading(0.0, 0.5, 1.0, 1.1, 2.0, 2.3), samples=3
        )

        self.assertAlmostEqual(sample.epoch, SERVER_TIME + 1 + 0.05, places=5)
        self.assertEqual(sample.counter, 1.1)

    def testRefusesRepliesThatAreNotAnAnswerToThisRequest(self):
        cases = {
            "unsynchronized": reply(SERVER_TIME, li=3),
            "kiss of death": reply(SERVER_TIME, stratum=0),
            "not a server": reply(SERVER_TIME, mode=3),
            "stale": reply(SERVER_TIME, originate=bytes(8)),
        }
        for name, build in cases.items():
            with self.subTest(name):
                server = FakeNtpServer(self, [build])
                with self.assertRaises(NtpError):
                    self.query(server, counterReading(0.0, 0.1), timeout=0.3)

    def testSilentServerNamesTheHostItCouldNotReach(self):
        server = FakeNtpServer(self, [lambda request: None])

        with self.assertRaises(NtpError) as raised:
            self.query(server, counterReading(0.0, 0.1), timeout=0.2)

        self.assertIn("127.0.0.1", str(raised.exception))


class FakeQuery:
    def __init__(self):
        self.hosts = []
        self.results = []

    def __call__(self, host):
        self.hosts.append(host)
        result = self.results.pop(0) if self.results else NtpSample(SERVER_TIME, 50.0, 0.02)
        if isinstance(result, Exception):
            raise result
        return result


class TimeSyncTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.timeSyncEnabled, True, save=False)
        cfg.set(cfg.timeServer, "阿里云", save=False)
        cfg.set(cfg.customTimeServer, "", save=False)
        self.system = SERVER_TIME - 2.4
        self.counter = 50.0
        self.clock = Clock(lambda: self.system, lambda: self.counter)
        self.query = FakeQuery()
        self.sync = TimeSync(
            query=self.query,
            clock=self.clock,
            systemTime=lambda: self.system,
            counter=lambda: self.counter,
        )
        self.addCleanup(self.sync.deleteLater)
        self.addCleanup(self.sync.shutdown)

    def waitForSync(self):
        deadline = time.monotonic() + 2
        while timeSyncState().syncing:
            if time.monotonic() > deadline:
                self.fail("timed out waiting for Time Sync")
            QTest.qWait(10)

    def testStartAsksTheChosenServerAndCalibratesTheClock(self):
        changes = []

        def record():
            changes.append(timeSyncState())

        signalBus.timeSyncStateChanged.connect(record)
        self.addCleanup(signalBus.timeSyncStateChanged.disconnect, record)

        self.sync.start()
        self.waitForSync()

        self.assertEqual(self.query.hosts, ["ntp.aliyun.com"])
        self.assertAlmostEqual(self.clock.epoch(), SERVER_TIME, places=3)
        state = timeSyncState()
        self.assertAlmostEqual(state.deviation, 2.4, places=3)
        self.assertEqual(state.error, "")
        self.assertIsNotNone(state.syncedAt)
        self.assertTrue(changes[0].syncing)

    def testFailureKeepsTheTimeOfTheLastSuccessfulSync(self):
        self.sync.start()
        self.waitForSync()
        syncedAt = timeSyncState().syncedAt
        self.query.results.append(NtpError("连不上 ntp.aliyun.com"))

        signalBus.timeSyncRequested.emit()
        self.waitForSync()

        self.assertTrue(self.clock.synchronized())
        self.assertEqual(timeSyncState().error, "连不上 ntp.aliyun.com")
        self.assertEqual(timeSyncState().syncedAt, syncedAt)

    def testTurningTimeSyncOffGoesBackToSystemTime(self):
        self.sync.start()
        self.waitForSync()

        cfg.set(cfg.timeSyncEnabled, False, save=False)

        self.assertFalse(self.clock.synchronized())
        self.assertIsNone(timeSyncState().syncedAt)
        signalBus.timeSyncRequested.emit()
        self.assertEqual(self.query.hosts, ["ntp.aliyun.com"])

    def testChangingTheWindowsClockSyncsAgainWithoutMovingCalibratedTime(self):
        self.sync.start()
        self.waitForSync()

        self.counter += 5
        self.system += 5 + 3600
        self.sync._watch()
        self.waitForSync()

        self.assertEqual(len(self.query.hosts), 2)

    def testWakingFromSleepSyncsAgain(self):
        self.sync.start()
        self.waitForSync()

        self.counter += 4 * 3600
        self.system += 4 * 3600
        self.sync._watch()
        self.waitForSync()

        self.assertEqual(len(self.query.hosts), 2)

    def testCustomServerIsAskedOnceTypingStops(self):
        self.sync.start()
        self.waitForSync()

        with patch.object(time_sync, "SERVER_CHANGE_DELAY_MS", 20):
            cfg.set(cfg.timeServer, CUSTOM_TIME_SERVER, save=False)
            cfg.set(cfg.customTimeServer, "ntp.exam", save=False)
            cfg.set(cfg.customTimeServer, "ntp.example.test", save=False)
            QTest.qWait(80)
        self.waitForSync()

        self.assertEqual(self.query.hosts, ["ntp.aliyun.com", "ntp.example.test"])
