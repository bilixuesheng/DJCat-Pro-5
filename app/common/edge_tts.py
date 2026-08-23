import os
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal


DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_SPEECH_PREFIX = "djcat-edge-tts-"


def cleanup_edge_speech_files(directory=None):
    root = Path(directory or tempfile.gettempdir())
    failed = []
    try:
        paths = tuple(root.glob(f"{EDGE_SPEECH_PREFIX}*.mp3"))
    except OSError:
        return [root]
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            failed.append(path)
    return failed


def filter_chinese_voices(voices):
    """Return normalized Edge TTS voices whose locale is Chinese."""
    result = []
    seen = set()

    for voice in voices:
        locale = str(voice.get("Locale", ""))
        short_name = str(voice.get("ShortName", ""))
        if not locale.lower().startswith("zh-") or not short_name or short_name in seen:
            continue

        seen.add(short_name)
        gender = "女声" if voice.get("Gender") == "Female" else "男声"
        friendly_name = str(voice.get("FriendlyName", "")).strip() or short_name
        result.append(
            {
                "name": short_name,
                "label": f"{friendly_name}（{locale} · {gender}）",
                "locale": locale,
                "gender": gender,
            }
        )

    return sorted(result, key=lambda item: (item["locale"], item["name"]))


def load_chinese_voices():
    """Load the current Chinese-only Edge TTS voice catalog from the network."""
    import asyncio
    import edge_tts

    return filter_chinese_voices(asyncio.run(edge_tts.list_voices()))


def synthesize_edge_speech(text, voice, output_path):
    """Synthesize text to an MP3 file with Edge TTS."""
    import asyncio
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice)
    asyncio.run(communicate.save(str(output_path)))


class EdgeSpeechWorker(QObject):
    finished = Signal(int, str, str)

    def __init__(self, request_id, text, voice, parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.text = text
        self.voice = voice
        self._cancelEvent = threading.Event()

    def cancel(self):
        self._cancelEvent.set()

    def run(self):
        descriptor, path = tempfile.mkstemp(prefix=EDGE_SPEECH_PREFIX, suffix=".mp3")
        os.close(descriptor)

        try:
            synthesize_edge_speech(self.text, self.voice, path)
        except Exception as error:
            Path(path).unlink(missing_ok=True)
            message = "" if self._cancelEvent.is_set() else str(error)
            self.finished.emit(self.request_id, "", message)
            return

        if self._cancelEvent.is_set():
            Path(path).unlink(missing_ok=True)
            self.finished.emit(self.request_id, "", "")
            return

        self.finished.emit(self.request_id, path, "")
