import asyncio

import edge_tts


DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"


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
    return filter_chinese_voices(asyncio.run(edge_tts.list_voices()))
