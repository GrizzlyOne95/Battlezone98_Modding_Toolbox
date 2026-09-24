import wave

import numpy as np
import pytest
import soundfile as sf

from bztoolbox.modules.audio import processing
from bztoolbox.modules.audio.audio import COMM_BEEP


def _tone(path, rate=44100, seconds=1.0, channels=2, fmt="WAV", subtype=None):
    t = np.arange(int(rate * seconds)) / rate
    mono = 0.5 * np.sin(2 * np.pi * 440 * t)
    data = np.column_stack([mono] * channels) if channels > 1 else mono
    sf.write(str(path), data, rate, format=fmt, subtype=subtype)
    return path


def _wav_params(path):
    with wave.open(str(path), "rb") as handle:
        return handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()


def _chunks(path):
    raw = path.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    ids, pos = [], 12
    while pos < len(raw):
        ids.append(raw[pos:pos + 4])
        pos += 8 + int.from_bytes(raw[pos + 4:pos + 8], "little")
    return ids


@pytest.mark.parametrize("intensity", ["none", "light", "medium", "heavy"])
def test_radio_vo_format(tmp_path, intensity):
    src = _tone(tmp_path / "line.wav")
    out = tmp_path / "out.wav"
    settings = processing.RadioSettings(intensity=intensity, phaser=True, echo=True, beep_path=COMM_BEEP)
    seconds = processing.radio_vo(str(src), str(out), settings)
    channels, width, rate, frames = _wav_params(out)
    assert (channels, width, rate) == (1, 1, 22050)
    beep_seconds = sf.info(COMM_BEEP).duration
    assert seconds == pytest.approx(1.0 + 0.04 + 2 * beep_seconds, abs=0.01)
    assert frames == pytest.approx(seconds * 22050, abs=1)
    assert _chunks(out) == [b"fmt ", b"data"]
    pcm = np.frombuffer(out.read_bytes()[44:], dtype=np.uint8)
    assert pcm.min() < 100 and pcm.max() > 156  # the voice survives the chain


def test_engine_loop(tmp_path):
    src = _tone(tmp_path / "thrust.wav", rate=22050, seconds=0.5, channels=1)
    out = tmp_path / "loop.wav"
    processing.engine_loop(str(src), str(out))
    channels, width, rate, frames = _wav_params(out)
    assert (channels, width, rate) == (1, 1, 11025)
    assert frames == pytest.approx(0.5 * 11025, abs=2)


def test_music_ogg_and_tags(tmp_path):
    src = tmp_path / "music.flac"
    t = np.arange(48000) / 48000
    with sf.SoundFile(str(src), "w", samplerate=48000, channels=2, format="FLAC") as handle:
        handle.title = "Track"
        handle.write(np.column_stack([0.5 * np.sin(2 * np.pi * 440 * t)] * 2))
    out = tmp_path / "music.ogg"
    processing.music_ogg(str(src), str(out), keep_tags=True)
    assert processing.read_tags(str(out)).get("title") == "Track"
    info = sf.info(str(out))
    assert (info.format, info.samplerate, info.channels) == ("OGG", 44100, 2)
    assert info.duration == pytest.approx(1.0, abs=0.02)
    processing.music_ogg(str(src), str(out), keep_tags=False)
    assert processing.read_tags(str(out)).get("title", "") == ""


def test_mp3_input(tmp_path):
    if "MP3" not in sf.available_formats():
        pytest.skip("libsndfile without MP3")
    src = _tone(tmp_path / "vo.mp3", fmt="MP3", subtype="MPEG_LAYER_III")
    out = tmp_path / "vo.wav"
    processing.radio_vo(str(src), str(out), processing.RadioSettings())
    assert _wav_params(out)[:3] == (1, 1, 22050)


def test_bad_input(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(ValueError):
        processing.radio_vo(str(bad), str(tmp_path / "o.wav"), processing.RadioSettings())


def test_compander_reduces_dynamic_range():
    rate = 22050
    t = np.arange(rate) / rate
    quiet_loud = np.where(t < 0.5, 0.01, 0.8) * np.sin(2 * np.pi * 300 * t)
    out = processing.compand(quiet_loud, rate, processing.INTENSITIES["medium"][2])
    ratio_in = np.abs(quiet_loud[-2000:]).max() / np.abs(quiet_loud[8000:10000]).max()
    ratio_out = np.abs(out[-2000:]).max() / np.abs(out[8000:10000]).max()
    assert ratio_out < ratio_in
