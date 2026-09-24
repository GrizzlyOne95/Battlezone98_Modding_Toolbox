"""Audio processing for Battlezone 98 Redux, in Python (no FFmpeg).

Decoding/encoding goes through ``soundfile`` (libsndfile, bundled in its
wheels on Windows, macOS and Linux): WAV, FLAC, OGG/Vorbis, MP3, AIFF, ...
The radio effect chain is NumPy/SciPy re-creations of the FFmpeg filters the
tool used before (``highpass``, ``lowpass``, ``volume``, ``compand``,
``aphaser``, ``aecho``, ``tremolo``), with the same parameters:

* Radio VO: 22050 Hz mono unsigned 8-bit, optional squelch beeps at 30% volume
  before and after the voice line.
* Thrust/turbo loop: 11025 Hz mono unsigned 8-bit, no effects.
* Music: 44100 Hz OGG Vorbis (~quality 5).

All writers produce plain RIFF/WAVE files (``fmt`` + ``data`` only), which is
what the engine's loader expects.
"""

from __future__ import annotations

import math
import os
import wave
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np
from scipy import signal

try:
    import soundfile as sf
except ImportError:  # pragma: no cover - listed in requirements
    sf = None

INPUT_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff")

RADIO_RATE = 22050
LOOP_RATE = 11025
MUSIC_RATE = 44100
BEEP_VOLUME = 0.3


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load(path: str) -> Tuple[np.ndarray, int]:
    """Decode any supported file to float64 samples shaped (frames, channels)."""
    if sf is None:
        raise RuntimeError("The 'soundfile' package is required for audio decoding.")
    try:
        data, rate = sf.read(path, dtype="float64", always_2d=True)
    except Exception as exc:  # soundfile raises its own error types
        raise ValueError(f"Cannot decode {os.path.basename(path)}: {exc}") from exc
    return data, rate


def to_mono(samples: np.ndarray) -> np.ndarray:
    return samples.mean(axis=1) if samples.ndim == 2 else samples


def resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Polyphase resampling (anti-aliased), along the first axis."""
    if rate == target or len(samples) == 0:
        return samples
    g = math.gcd(int(rate), int(target))
    return signal.resample_poly(samples, target // g, rate // g, axis=0)


def write_wav_u8(path: str, mono: np.ndarray, rate: int) -> None:
    """Unsigned 8-bit mono PCM, plain RIFF (fmt + data chunks only)."""
    clipped = np.clip(mono, -1.0, 1.0)
    pcm = np.clip(np.floor(clipped * 128.0 + 128.0), 0, 255).astype(np.uint8)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


_TAGS = ("title", "artist", "album", "date", "comment", "genre", "tracknumber", "copyright", "software")


def write_ogg(path: str, samples: np.ndarray, rate: int, quality: float = 0.5,
              tags: Optional[dict] = None) -> None:
    """OGG Vorbis; ``quality`` 0..1 (0.5 is about Vorbis q5)."""
    if sf is None:
        raise RuntimeError("The 'soundfile' package is required for OGG encoding.")
    peak = np.max(np.abs(samples)) if samples.size else 0.0
    if peak > 1.0:
        samples = samples / peak
    with sf.SoundFile(path, "w", samplerate=rate, channels=samples.shape[1] if samples.ndim == 2 else 1,
                      format="OGG", subtype="VORBIS", compression_level=1.0 - quality) as out:
        for key, value in (tags or {}).items():
            if value:
                try:
                    setattr(out, key, value)
                except Exception:
                    pass
        out.write(samples)


def read_tags(path: str) -> dict:
    if sf is None:
        return {}
    try:
        with sf.SoundFile(path) as handle:
            return {key: getattr(handle, key, "") for key in _TAGS if getattr(handle, key, "")}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Effects (mono float arrays in, mono float arrays out)
# ---------------------------------------------------------------------------

def highpass(x: np.ndarray, rate: int, freq: float) -> np.ndarray:
    sos = signal.butter(2, freq, "highpass", fs=rate, output="sos")
    return signal.sosfilt(sos, x)


def lowpass(x: np.ndarray, rate: int, freq: float) -> np.ndarray:
    sos = signal.butter(2, min(freq, rate / 2 * 0.99), "lowpass", fs=rate, output="sos")
    return signal.sosfilt(sos, x)


@dataclass(frozen=True)
class Compand:
    attack: float                       # seconds
    decay: float                        # seconds
    points: Sequence[Tuple[float, float]]  # (input dB, output dB)
    gain: float = 0.0                   # dB
    initial: float = -90.0              # dB
    delay: float = 0.0                  # look-ahead, seconds

    def transfer(self, level_db: np.ndarray) -> np.ndarray:
        pts = sorted(self.points)
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        # like FFmpeg: below the first point keeps its offset, above the last is 0 dB slope-1
        out = np.interp(level_db, xs, ys)
        below = level_db < xs[0]
        out[below] = level_db[below] + (ys[0] - xs[0])
        above = level_db > xs[-1]
        out[above] = level_db[above] + (ys[-1] - xs[-1])
        return out


def compand(x: np.ndarray, rate: int, params: Compand) -> np.ndarray:
    """Dynamic range compression with an attack/decay envelope follower."""
    if len(x) == 0:
        return x
    rise = 1.0 - math.exp(-1.0 / (rate * params.attack)) if params.attack > 0 else 1.0
    fall = 1.0 - math.exp(-1.0 / (rate * params.decay)) if params.decay > 0 else 1.0
    level = np.abs(x)
    envelope = np.empty_like(level)
    volume = 10 ** (params.initial / 20)
    # a sample loop is needed (the coefficient depends on direction); it is
    # cheap enough at game sample rates
    for i, value in enumerate(level.tolist()):
        volume += (value - volume) * (rise if value > volume else fall)
        envelope[i] = volume
    lookahead = int(round(params.delay * rate))
    if lookahead:
        envelope = np.concatenate([envelope[lookahead:], np.full(lookahead, envelope[-1])])
    env_db = 20 * np.log10(np.maximum(envelope, 1e-9))
    gain_db = params.transfer(env_db) - env_db + params.gain
    return x * (10 ** (gain_db / 20))


def aphaser(x: np.ndarray, rate: int, in_gain: float = 0.8, out_gain: float = 0.9, delay_ms: float = 3.0,
            decay: float = 0.4, speed: float = 0.2, triangular: bool = True) -> np.ndarray:
    """Modulated feedback delay (FFmpeg ``aphaser``)."""
    delay_len = max(1, int(delay_ms * 0.001 * rate + 0.5))
    mod_len = max(1, int(rate / speed + 0.5))
    phase = np.arange(mod_len) / mod_len
    if triangular:
        wave_ = 1.0 - np.abs(2.0 * phase - 1.0)            # 0..1..0
        wave_ = np.roll(wave_, mod_len // 4)
    else:
        wave_ = (np.sin(2 * np.pi * phase) + 1.0) / 2.0
    modulation = (wave_ * (delay_len - 1) + 1).astype(np.int64) % delay_len
    buffer = [0.0] * delay_len
    out = np.empty_like(x)
    delay_pos = mod_pos = 0
    mod = modulation.tolist()
    for i, sample in enumerate(x.tolist()):
        value = sample * in_gain + buffer[(delay_pos + mod[mod_pos]) % delay_len] * decay
        mod_pos = (mod_pos + 1) % mod_len
        delay_pos = (delay_pos + 1) % delay_len
        buffer[delay_pos] = value
        out[i] = value * out_gain
    return out


def aecho(x: np.ndarray, rate: int, in_gain: float, out_gain: float, delay_ms: float, decay: float) -> np.ndarray:
    """Single-tap echo (FFmpeg ``aecho``); the output is longer by the delay."""
    delay = int(delay_ms * rate / 1000)
    out = np.zeros(len(x) + delay)
    out[:len(x)] += x * in_gain
    out[delay:delay + len(x)] += x * decay
    return out * out_gain


def tremolo(x: np.ndarray, rate: int, freq: float, depth: float) -> np.ndarray:
    t = np.arange(len(x)) / rate
    env = np.sin(2 * np.pi * np.mod(freq * t + 0.25, 1.0))
    offset = 1.0 - depth / 2.0
    return x * (env * (1.0 - abs(offset)) + offset)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

INTENSITIES = {
    # (highpass Hz, lowpass Hz, compressor): the FFmpeg ``compand`` settings the
    # tool used before (attack|decay : points : soft-knee : gain 0 : -90 dB : delay)
    "light": (300, 4000, Compand(0.3, 1.0, ((-90, -60), (-60, -40), (-40, -30), (-20, -20)), 0, -90, 0.2)),
    "medium": (500, 3000, Compand(0.2, 1.0, ((-90, -60), (-60, -40), (-40, -20), (-10, -10)), 0, -90, 0.15)),
    "heavy": (700, 2500, Compand(0.1, 1.0, ((-90, -60), (-60, -30), (-30, -20), (-10, -10)), 0, -90, 0.1)),
}


@dataclass
class RadioSettings:
    intensity: str = "medium"           # none / light / medium / heavy
    phaser: bool = False
    echo: bool = False
    echo_delay_ms: float = 40.0
    beep_path: Optional[str] = None


def radio_chain(voice: np.ndarray, rate: int, settings: RadioSettings) -> np.ndarray:
    """The radio VO filter chain on mono samples already at ``rate``."""
    x = voice
    if settings.intensity != "none":
        hp, lp, comp = INTENSITIES[settings.intensity]
        x = lowpass(highpass(x, rate, hp), rate, lp) * 2.0
        x = compand(x, rate, comp)
    if settings.phaser:
        x = aphaser(x, rate)
    if settings.echo:
        x = aecho(x, rate, 0.8, 0.9, settings.echo_delay_ms, 0.3)
    if settings.intensity != "none":
        x = tremolo(x, rate, 30.0, 0.05)
    return x


def _load_mono(path: str, rate: int) -> np.ndarray:
    data, source_rate = load(path)
    return resample(to_mono(data), source_rate, rate)


def radio_vo(source: str, output: str, settings: RadioSettings) -> float:
    """Master a voice line for the in-game radio; returns the duration in seconds."""
    voice = radio_chain(_load_mono(source, RADIO_RATE), RADIO_RATE, settings)
    if settings.beep_path:
        beep = _load_mono(settings.beep_path, RADIO_RATE) * BEEP_VOLUME
        voice = np.concatenate([beep, voice, beep])
    write_wav_u8(output, voice, RADIO_RATE)
    return len(voice) / RADIO_RATE


def engine_loop(source: str, output: str) -> float:
    """Thrust/turbo loop: 11025 Hz unsigned 8-bit mono, no effects."""
    samples = _load_mono(source, LOOP_RATE)
    write_wav_u8(output, samples, LOOP_RATE)
    return len(samples) / LOOP_RATE


def music_ogg(source: str, output: str, keep_tags: bool = False) -> float:
    """Music track: 44100 Hz OGG Vorbis, channels preserved."""
    data, rate = load(source)
    data = resample(data, rate, MUSIC_RATE)
    write_ogg(output, data, MUSIC_RATE, tags=read_tags(source) if keep_tags else None)
    return len(data) / MUSIC_RATE


def duration(path: str) -> float:
    if sf is None:
        raise RuntimeError("The 'soundfile' package is required.")
    return sf.info(path).duration
