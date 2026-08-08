import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.common.edge_tts import (
    DEFAULT_EDGE_VOICE,
    EdgeSpeechWorker,
    clear_edge_speech_files,
    filter_chinese_voices,
    synthesize_edge_speech,
)
from app.view.pages.schedule_page import ChineseVoiceLoader, create_task_form
from app.view.windows.main_window import MainWindow
from deploy import build_args


class EdgeTtsVoiceTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def testVoiceFilterKeepsOnlyChineseLocales(self):
        voices = filter_chinese_voices(
            [
                {
                    "ShortName": "en-US-EmmaNeural",
                    "Locale": "en-US",
                    "Gender": "Female",
                },
                {
                    "ShortName": "zh-TW-HsiaoChenNeural",
                    "FriendlyName": "Microsoft 曉臻 Online (Natural) - Chinese (Taiwan)",
                    "Locale": "zh-TW",
                    "Gender": "Female",
                },
                {
                    "ShortName": "zh-CN-YunxiNeural",
                    "FriendlyName": "Microsoft 云希 Online (Natural) - Chinese (Mainland)",
                    "Locale": "zh-CN",
                    "Gender": "Male",
                },
            ]
        )

        self.assertEqual(
            [voice["name"] for voice in voices],
            ["zh-CN-YunxiNeural", "zh-TW-HsiaoChenNeural"],
        )
        self.assertEqual([voice["gender"] for voice in voices], ["男声", "女声"])

    @patch.object(ChineseVoiceLoader, "start")
    def testEdgeTtsSelectionShowsVoicePickerAndPersistsVoice(self, start_loader):
        form, widgets = create_task_form(None)
        self.addCleanup(form.deleteLater)

        self.assertTrue(widgets["voiceCard"].isHidden())

        widgets["typeCombo"].setCurrentText("Edge TTS（需要联网）")

        self.assertFalse(widgets["voiceCard"].isHidden())
        self.assertEqual(widgets["voiceCombo"].currentData(), DEFAULT_EDGE_VOICE)
        start_loader.assert_called_once()

    @patch.object(ChineseVoiceLoader, "start")
    def testLoadedVoiceListRestoresSavedChineseVoice(self, start_loader):
        form, widgets = create_task_form(
            None,
            {
                "name": "测试任务",
                "time": "12:30:00",
                "weeks": [0],
                "type": "Edge TTS（需要联网）",
                "content": "测试播报",
                "file": "",
                "repeat": 1,
                "volume": 80,
                "voice": "zh-TW-HsiaoChenNeural",
                "enabled": True,
            },
        )
        self.addCleanup(form.deleteLater)
        voices = filter_chinese_voices(
            [
                {
                    "ShortName": "zh-CN-XiaoxiaoNeural",
                    "Locale": "zh-CN",
                    "Gender": "Female",
                },
                {
                    "ShortName": "zh-TW-HsiaoChenNeural",
                    "Locale": "zh-TW",
                    "Gender": "Female",
                },
            ]
        )

        widgets["voiceLoader"].finished.emit(voices, "")

        self.assertEqual(widgets["voiceCombo"].count(), 2)
        self.assertEqual(
            widgets["voiceCombo"].currentData(),
            "zh-TW-HsiaoChenNeural",
        )
        start_loader.assert_called_once()

    def testSynthesisUsesSelectedVoiceAndWritesRequestedFile(self):
        class CommunicateStub:
            def __init__(self, text, voice):
                self.text = text
                self.voice = voice

            async def save(self, output_path):
                Path(output_path).write_bytes(b"test-mp3")

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "speech.mp3"
            with patch("app.common.edge_tts.edge_tts.Communicate", CommunicateStub):
                synthesize_edge_speech(
                    "测试播报",
                    "zh-TW-HsiaoChenNeural",
                    output_path,
                )

            self.assertEqual(output_path.read_bytes(), b"test-mp3")

    def testWorkerRemovesPartialFileWhenSynthesisFails(self):
        results = []
        worker = EdgeSpeechWorker(7, "测试播报", DEFAULT_EDGE_VOICE)
        worker.finished.connect(
            lambda request_id, path, error: results.append(
                (request_id, path, error)
            )
        )

        with patch(
            "app.common.edge_tts.synthesize_edge_speech",
            side_effect=RuntimeError("offline"),
        ):
            worker.run()

        self.assertEqual(results, [(7, "", "offline")])

    def testCanceledWorkerRemovesFileAndSignalsCompletion(self):
        results = []
        outputPaths = []
        worker = EdgeSpeechWorker(8, "测试播报", DEFAULT_EDGE_VOICE)
        worker.finished.connect(lambda *args: results.append(args))

        def synthesize(_, __, outputPath):
            outputPaths.append(Path(outputPath))
            Path(outputPath).write_bytes(b"test-mp3")
            worker.cancel()

        with patch(
            "app.common.edge_tts.synthesize_edge_speech",
            side_effect=synthesize,
        ):
            worker.run()

        self.assertEqual(results, [(8, "", "")])
        self.assertEqual(len(outputPaths), 1)
        self.assertFalse(outputPaths[0].exists())

    def testStartupCleanupRemovesOnlyEdgeSpeechTemporaryFiles(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_directory = Path(directory)
            stale_speech = temp_directory / "djcat-edge-tts-stale.mp3"
            unrelated = temp_directory / "unrelated.mp3"
            stale_speech.write_bytes(b"stale")
            unrelated.write_bytes(b"keep")

            clear_edge_speech_files(temp_directory)

            self.assertFalse(stale_speech.exists())
            self.assertTrue(unrelated.exists())

    def testPlaybackRoutesEdgeTtsToOnlineSynthesizer(self):
        window = MagicMock()
        window._resourcesShutdown = False

        MainWindow._playAudioTask(
            window,
            {
                "type": "Edge TTS（需要联网）",
                "content": "  测试播报  ",
                "voice": "zh-TW-HsiaoChenNeural",
                "repeat": 2,
                "volume": 70,
            },
        )

        window._setBroadcastVolume.assert_called_once_with(70)
        window._startEdgeTts.assert_called_once_with(
            "测试播报",
            "zh-TW-HsiaoChenNeural",
            2,
            70,
        )
        window.tts.say.assert_not_called()

    def testCompletedSynthesisUsesSavedRepeatAndVolume(self):
        window = MagicMock()
        window._edge_tts_request_id = 4
        worker = MagicMock()
        window._edge_tts_jobs = {4: (worker, MagicMock(), 3, 55)}

        MainWindow._onEdgeTtsReady(window, 4, "/tmp/edge-result.mp3", "")

        window._setBroadcastVolume.assert_called_once_with(55)
        window._cleanupEdgeTtsFile.assert_called_once_with()
        self.assertEqual(window._edge_tts_temp_path, "/tmp/edge-result.mp3")
        self.assertEqual(window.current_play_repeats, 2)
        source = window.player.setSource.call_args.args[0]
        self.assertEqual(source.toLocalFile(), "/tmp/edge-result.mp3")
        window.player.play.assert_called_once_with()
        worker.deleteLater.assert_called_once_with()

    def testCancelPendingSynthesisKeepsJobsUntilCompletion(self):
        window = MagicMock()
        window._edge_tts_request_id = 4
        firstWorker = MagicMock()
        secondWorker = MagicMock()
        window._edge_tts_jobs = {
            3: (firstWorker, MagicMock(), 1, 100),
            4: (secondWorker, MagicMock(), 1, 100),
        }
        window._invalidatePendingEdgeTts = lambda: MainWindow._invalidatePendingEdgeTts(
            window
        )

        MainWindow._cancelPendingEdgeTts(window)

        self.assertEqual(window._edge_tts_request_id, 5)
        self.assertEqual(set(window._edge_tts_jobs), {3, 4})
        firstWorker.cancel.assert_called_once_with()
        secondWorker.cancel.assert_called_once_with()

        MainWindow._onEdgeTtsReady(window, 3, "", "")

        self.assertEqual(set(window._edge_tts_jobs), {4})
        firstWorker.deleteLater.assert_called_once_with()

    @patch("app.view.windows.main_window.InfoBar.error")
    def testSynthesisFailureShowsNetworkError(self, show_error):
        window = MagicMock()
        window._edge_tts_request_id = 5
        window._edge_tts_jobs = {5: (MagicMock(), MagicMock(), 1, 100)}

        MainWindow._onEdgeTtsReady(window, 5, "", "offline")

        show_error.assert_called_once()
        self.assertEqual(
            show_error.call_args.kwargs["content"],
            "请检查网络连接后重试。",
        )
        window.player.play.assert_not_called()

    def testWindowsBuildExplicitlyIncludesEdgeTtsPackage(self):
        self.assertIn("--include-package=edge_tts", build_args())
