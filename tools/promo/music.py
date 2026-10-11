"""合成宣传片配乐：tools/promo/out/audio.wav（48 kHz 立体声）。

配乐与音效都由 numpy 现场合成，唯一的外部素材是软件自带的考试语音提醒
app/assets/15.wav。CUES 里的时刻与 promo.html 的时间轴一一对应，改动任一处要同步另一处。

    python tools/promo/music.py
"""

import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
OUT = ROOT / "out" / "audio.wav"

SR = 48_000
DURATION = 47.0
BEAT = 0.5  # 120 BPM
BAR = 4 * BEAT
rng = np.random.default_rng(5)

CUES = {
    "transitions": [4.0, 8.0, 13.0, 16.5, 21.0, 28.0, 33.0, 38.0, 42.0],
    "logoPop": [4.3, 42.45],
    "clicks": [10.15, 15.22, 34.88],
    "seqChecks": [10.87, 11.37, 11.87, 12.37],
    "typing": (13.75, 15.1),
    "aiGlow": (15.5, 16.5),
    "countdownTicks": [21.75, 22.75, 23.75, 24.75, 25.75, 26.75, 27.75],
    # 15.wav 先是 2.8 秒的提示音，随后才是语音，跳到 0:15:00 的那一刻就要响
    "voice": 21.75,
    "taskFires": [29.0, 29.85, 30.75, 31.65],
    "downloadDone": 37.25,
    "tilesIn": [38.45, 38.53, 38.61, 38.69, 38.77, 38.85],
    # 倒计时场景只留铺底，鼓组让位给秒针和语音
    "drumsOff": (21.0, 28.0),
    "impacts": [4.0, 42.0],
    "end": 44.0,
}

CHORDS = {
    "F": ([53, 57, 60, 64], 41),
    "G": ([55, 59, 62, 64], 43),
    "Em": ([52, 55, 59, 62], 40),
    "Am": ([57, 60, 64, 67], 45),
    "C": ([48, 55, 60, 62, 64, 67], 36),
}
PROGRESSION = ["F", "G", "Em", "Am"]

N = int(DURATION * SR)
t_all = np.arange(N) / SR


def midiFreq(m):
    return 440.0 * 2 ** ((m - 69) / 12)


FINAL_BAR = 22  # 44 秒起落在 C 上一直响到结尾


def chordAt(barIndex):
    if barIndex >= FINAL_BAR:
        return "C"
    return PROGRESSION[barIndex % 4]


def place(bus, start, signal, gain=1.0, pan=0.0):
    """把单声道或立体声片段叠加到 bus 的 start 秒处。"""
    i = int(round(start * SR))
    if i >= N:
        return
    if signal.ndim == 1:
        left = signal * np.sqrt(0.5 * (1 - pan))
        right = signal * np.sqrt(0.5 * (1 + pan))
        signal = np.stack([left, right], axis=1) * np.sqrt(2)
    end = min(N, i + len(signal))
    bus[i:end] += signal[: end - i] * gain


def fftFilter(x, low=None, high=None, slope=1.0):
    """频域里做平滑的高通/低通，适合噪声类素材。"""
    n = len(x)
    spec = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    mask = np.ones_like(freqs)
    if low:
        mask *= 1 / (1 + (low / np.maximum(freqs, 1)) ** (4 * slope))
    if high:
        mask *= 1 / (1 + (freqs / high) ** (4 * slope))
    if x.ndim == 2:
        mask = mask[:, None]
    return np.fft.irfft(spec * mask, n=n, axis=0)


def env(n, attack, release, total):
    tt = np.arange(n) / SR
    e = np.minimum(1, tt / max(attack, 1e-4))
    e *= np.clip((total - tt) / max(release, 1e-4), 0, 1)
    return e


# ---------------------------------------------------------------- instruments
def padNote(freq, dur, detune):
    n = int((dur + 0.8) * SR)
    tt = np.arange(n) / SR
    f = freq * 2 ** (detune / 1200)
    sig = np.zeros(n)
    for h in range(1, 9):
        sig += np.sin(2 * np.pi * f * h * tt + h * 0.7) * (1 / h) * np.exp(-h / 3.2)
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.1 * tt)
    return sig * env(n, 0.35, 0.8, dur + 0.8) * vib


def epiano(freq, dur=1.4, bright=1.8):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    index = bright * np.exp(-tt / 0.16)
    sig = np.sin(2 * np.pi * freq * tt + index * np.sin(2 * np.pi * freq * tt))
    sig += 0.18 * np.sin(2 * np.pi * freq * 4.01 * tt) * np.exp(-tt / 0.08)
    amp = np.exp(-tt / 0.42) * np.minimum(1, tt / 0.002)
    return sig * amp


def bell(freq, dur=1.8):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = np.sin(2 * np.pi * freq * tt + 1.2 * np.exp(-tt / 0.3) * np.sin(2 * np.pi * freq * 3.5 * tt))
    sig += 0.35 * np.sin(2 * np.pi * freq * 2 * tt) * np.exp(-tt / 0.25)
    return sig * np.exp(-tt / 0.55) * np.minimum(1, tt / 0.001)


def bassNote(freq, dur):
    n = int((dur + 0.05) * SR)
    tt = np.arange(n) / SR
    sig = np.sin(2 * np.pi * freq * tt) + 0.35 * np.sin(2 * np.pi * 2 * freq * tt) + 0.1 * np.sin(2 * np.pi * 3 * freq * tt)
    amp = np.minimum(1, tt / 0.006) * (0.65 + 0.35 * np.exp(-tt / 0.12))
    amp *= np.clip((dur + 0.05 - tt) / 0.05, 0, 1)
    return np.tanh(1.4 * sig) * amp


def kick():
    n = int(0.5 * SR)
    tt = np.arange(n) / SR
    f = 46 + 120 * np.exp(-tt / 0.028)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-tt / 0.26)
    click = fftFilter(rng.standard_normal(n), low=2000) * np.exp(-tt / 0.004) * 0.3
    return np.tanh(1.6 * (body + click))


def clap():
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    noise = fftFilter(rng.standard_normal(n), low=900, high=4200)
    e = np.zeros(n)
    for k, d in enumerate([0, 0.011, 0.022]):
        e += (tt >= d) * np.exp(-np.maximum(tt - d, 0) / (0.012 if k < 2 else 0.13))
    return noise * e / 3


def hat(open_=False):
    n = int((0.25 if open_ else 0.08) * SR)
    tt = np.arange(n) / SR
    noise = fftFilter(rng.standard_normal(n), low=7500)
    return noise * np.exp(-tt / (0.09 if open_ else 0.025))


def whoosh(dur=0.9):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    noise = fftFilter(rng.standard_normal((n, 2)), low=500, high=5000)
    peak = dur * 0.45
    e = np.where(tt < peak, (tt / peak) ** 2, np.exp(-(tt - peak) / 0.16))
    pan = np.clip(tt / dur, 0, 1)
    noise[:, 0] *= np.sqrt(1 - pan)
    noise[:, 1] *= np.sqrt(pan)
    return noise * e[:, None]


def riser(dur):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    noise = fftFilter(rng.standard_normal(n), low=900, high=9000)
    sweep = np.sin(2 * np.pi * np.cumsum(220 + 1800 * (tt / dur) ** 2) / SR) * 0.15
    return (noise * 0.5 + sweep) * (tt / dur) ** 2.4


def impact():
    n = int(1.6 * SR)
    tt = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 60 * np.exp(-tt / 0.08)) / SR) * np.exp(-tt / 0.45)
    air = fftFilter(rng.standard_normal(n), low=300, high=7000) * np.exp(-tt / 0.35) * 0.35
    return np.tanh(1.3 * (boom + air))


def uiClick():
    n = int(0.05 * SR)
    tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * 1700 * tt) * np.exp(-tt / 0.006)
            + fftFilter(rng.standard_normal(n), low=3000) * np.exp(-tt / 0.003) * 0.4)


def tick():
    n = int(0.08 * SR)
    tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * 2600 * tt) * np.exp(-tt / 0.01) * 0.7
            + np.sin(2 * np.pi * 900 * tt) * np.exp(-tt / 0.02) * 0.5)


def keyTap():
    n = int(0.03 * SR)
    tt = np.arange(n) / SR
    return fftFilter(rng.standard_normal(n), low=1500, high=6000) * np.exp(-tt / 0.005)


def shimmer(dur):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for k, m in enumerate([84, 88, 91, 95, 96]):
        sig += np.sin(2 * np.pi * midiFreq(m) * tt + k) * (0.5 + 0.5 * np.sin(2 * np.pi * (2.3 + k * 0.7) * tt + k))
    e = np.minimum(1, tt / 0.2) * np.clip((dur - tt) / 0.3, 0, 1)
    return sig * e / 5


def loadVoice():
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(REPO / "app" / "assets" / "15.wav"),
         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def reverb(x, seconds=2.4, decay=0.55):
    n = int(seconds * SR)
    tt = np.arange(n) / SR
    ir = rng.standard_normal((n, 2)) * np.exp(-tt / decay)[:, None]
    ir = fftFilter(ir, low=200, high=6500)
    ir[: int(0.012 * SR)] = 0  # 预延迟
    ir /= np.sqrt(np.sum(ir ** 2, axis=0))
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    out = np.fft.irfft(np.fft.rfft(x, size, axis=0) * np.fft.rfft(ir, size, axis=0), size, axis=0)
    return out[: len(x)]


# ---------------------------------------------------------------- arrangement
def drumsActive(t):
    a, b = CUES["drumsOff"]
    return not (a <= t < b) and t < CUES["end"]


def build():
    music = np.zeros((N, 2))
    send = np.zeros((N, 2))
    drums = np.zeros((N, 2))
    sfx = np.zeros((N, 2))
    kicks = []

    for b in range(FINAL_BAR + 1):
        start = b * BAR
        name = chordAt(b)
        notes, root = CHORDS[name]
        final = name == "C"
        length = DURATION - start if final else BAR
        # 铺底
        padGain = 0.05 if start < 4 else 0.065
        for k, m in enumerate(notes):
            f = midiFreq(m)
            for det, pan in ((-7, -0.6), (7, 0.6)):
                note = padNote(f, length, det)
                place(music, start, note, padGain, pan)
                place(send, start, note, padGain * 0.8, pan)
        # 电钢琴琶音：八分音符
        arpNotes = [n + 12 for n in notes[:4]]
        pattern = [0, 1, 2, 3, 2, 1, 2, 3]
        if final:
            for k, m in enumerate(sorted(arpNotes + [notes[-1] + 12])):
                place(music, start + k * 0.06, epiano(midiFreq(m), 2.4, 1.2), 0.11, -0.3 + 0.15 * k)
                place(send, start + k * 0.06, epiano(midiFreq(m), 2.4, 1.2), 0.12)
        else:
            for k, idx in enumerate(pattern):
                at = start + k * BEAT / 2
                countdown = CUES["drumsOff"][0] <= at < CUES["drumsOff"][1]
                if countdown and k % 2:
                    continue
                vel = (0.085 if start < 4 else 0.1) * (1.0 if k % 2 == 0 else 0.75)
                if countdown:
                    vel *= 0.6
                note = epiano(midiFreq(arpNotes[idx]))
                pan = -0.35 if k % 2 == 0 else 0.35
                place(music, at, note, vel, pan)
                place(send, at, note, vel * 0.9, pan)
        # 贝斯
        if start >= 4:
            f = midiFreq(root)
            if final:
                place(music, start, bassNote(f, 2.0), 0.18)
            elif start < 8 or not drumsActive(start + 0.01):
                place(music, start, bassNote(f, BAR - 0.05), 0.15)
            else:
                for off, d, mul in [(0, .45, 1), (.75, .2, 1), (1.0, .45, 1), (1.5, .2, 2), (1.75, .2, 1)]:
                    place(music, start + off, bassNote(f * mul, d), 0.16)

    # 鼓组
    beats = int(DURATION / BEAT)
    for i in range(beats):
        at = i * BEAT
        if at < 4 or not drumsActive(at):
            continue
        inBar = i % 4
        half = at < 8
        if not half or inBar in (0, 2):
            place(drums, at, kick(), 0.48)
            kicks.append(at)
        if not half and inBar in (1, 3):
            place(drums, at, clap(), 0.28, 0.05)
            place(send, at, clap(), 0.18)
        if not half:
            place(drums, at + BEAT / 2, hat(open_=(inBar == 3)), 0.09 if inBar != 3 else 0.06, 0.3)
            place(drums, at, hat(), 0.04, -0.3)

    # 倒计时结束前的军鼓渐强，把鼓组接回来
    for k in range(4):
        at = CUES["drumsOff"][1] - 0.5 + k * 0.125
        place(drums, at, clap(), 0.08 + 0.05 * k, 0.0)

    # 侧链：底鼓压一下铺底和琶音
    duck = np.ones(N)
    for at in kicks:
        i = int(at * SR)
        n = min(N - i, int(0.35 * SR))
        tt = np.arange(n) / SR
        duck[i:i + n] = np.minimum(duck[i:i + n], 1 - 0.45 * np.exp(-tt / 0.11))
    music *= duck[:, None]

    # 转场与界面音效
    place(sfx, 2.4, riser(1.6), 0.16)
    for at in CUES["transitions"]:
        w = whoosh()
        place(sfx, at - 0.45, w, 0.13)
        place(send, at - 0.45, w, 0.08)
    for at in CUES["impacts"]:
        place(sfx, at, impact(), 0.3)
        place(send, at, impact(), 0.15)
    for at in CUES["logoPop"]:
        for k, m in enumerate([79, 84, 88]):
            place(sfx, at + 0.05 + k * 0.07, bell(midiFreq(m)), 0.07, -0.2 + 0.2 * k)
            place(send, at + 0.05 + k * 0.07, bell(midiFreq(m)), 0.06)
    for at in CUES["clicks"]:
        place(sfx, at, uiClick(), 0.22)
    for k, at in enumerate(CUES["seqChecks"]):
        place(sfx, at, bell(midiFreq(84 + [0, 2, 4, 7][k]), 0.8), 0.06, 0.2)
        place(send, at, bell(midiFreq(84 + [0, 2, 4, 7][k]), 0.8), 0.04)
    a, b = CUES["typing"]
    at = a
    while at < b:
        place(sfx, at, keyTap(), rng.uniform(0.05, 0.09), rng.uniform(-0.3, 0.3))
        at += rng.uniform(0.045, 0.09)
    a, b = CUES["aiGlow"]
    place(sfx, a, shimmer(b - a + 0.2), 0.12)
    place(send, a, shimmer(b - a + 0.2), 0.12)
    for at in CUES["countdownTicks"]:
        place(sfx, at, tick(), 0.18)
        place(send, at, tick(), 0.05)
    for k, at in enumerate(CUES["taskFires"]):
        m = [76, 79, 83, 88][k]
        place(sfx, at, bell(midiFreq(m), 1.0), 0.08, 0.3)
        place(send, at, bell(midiFreq(m), 1.0), 0.06)
    at = CUES["downloadDone"]
    for k, m in enumerate([84, 88, 91, 96]):
        place(sfx, at + k * 0.06, bell(midiFreq(m), 1.2), 0.07, -0.3 + 0.2 * k)
        place(send, at + k * 0.06, bell(midiFreq(m), 1.2), 0.07)
    for at in CUES["tilesIn"]:
        place(sfx, at + 0.05, keyTap(), 0.05)

    wet = reverb(send)
    mix = music + drums + sfx + wet * 0.55
    mix = fftFilter(mix, low=28)

    # 语音提醒时把配乐压低
    voice = loadVoice()
    v0 = CUES["voice"]
    v1 = v0 + len(voice) / SR
    gain = np.ones(N)
    ramp = 0.18
    gain -= 0.62 * np.clip((t_all - (v0 - ramp)) / ramp, 0, 1) * np.clip(((v1 + ramp) - t_all) / ramp, 0, 1)
    mix *= gain[:, None]
    mix /= np.max(np.abs(mix))
    voiceBus = np.zeros((N, 2))
    place(voiceBus, v0, voice / np.max(np.abs(voice)), 0.95)
    mix = mix * 0.62 + voiceBus * 0.7

    # 收尾淡出、轻度限幅
    fade = np.clip((DURATION - t_all) / 1.6, 0, 1) ** 1.5
    mix *= fade[:, None]
    mix = np.tanh(1.2 * mix) / np.tanh(1.2)
    mix *= 0.7 / np.max(np.abs(mix))
    return mix


def main():
    mix = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(OUT)


if __name__ == "__main__":
    main()
