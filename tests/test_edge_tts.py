import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.common.edge_tts import DEFAULT_EDGE_VOICE, filter_chinese_voices
from app.view.pages.schedule_page import ChineseVoiceLoader, create_task_form


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
