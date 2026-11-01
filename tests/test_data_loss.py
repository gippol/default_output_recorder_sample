"""
Tests for recording data-loss protections:
RF64 for >4 GB WAV, no overwriting, honest conversion fallback, device loss/reconnect.
"""

import os
import threading
import time

import numpy as np
import pytest
import soundfile as sf

from src.core.dsp import LinearResampler
from src.core.engine import RecordingEngine
from src.core.event_bus import EventBus, EventType
from src.core.models import AudioChunk, AudioFormat, OutputFormat, RecordingConfig
from src.drivers import wasapi_driver
from src.drivers.base import DeviceStatus
from src.drivers.mock_driver import MockAudioDriver
from src.encoders import audio_file_sink
from src.encoders.audio_file_sink import AudioFileSink

FMT = AudioFormat(sample_rate=48000, channels=2)


def _tone_chunk(seconds=0.5):
    t = np.arange(int(48000 * seconds)) / 48000
    data = np.column_stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)
    return AudioChunk(data=data, timestamp=time.time(), format=FMT)


# --- WAV 4 GB limit ------------------------------------------------------------------------

def test_wav_is_written_as_rf64_and_downgraded_when_small(tmp_path):
    path = str(tmp_path / "a.wav")
    sink = AudioFileSink()
    sink.open(path, FMT, OutputFormat.WAV)
    assert sink._sf_file.format == "RF64"  # no 4 GB ceiling while recording
    sink.write_chunk(_tone_chunk())
    sink.close()

    with open(path, "rb") as f:
        assert f.read(4) == b"RIFF"  # < 4 GB: ordinary WAV header for compatibility
    assert sf.info(path).frames == 24000


# --- Overwrite protection -------------------------------------------------------------------

def test_unique_filepath_adds_suffix_for_any_sibling(tmp_path):
    d = str(tmp_path)
    assert RecordingEngine._unique_filepath(d, "rec", "mp3") == os.path.join(d, "rec.mp3")
    (tmp_path / "rec.mp3").write_bytes(b"x")
    assert RecordingEngine._unique_filepath(d, "rec", "mp3") == os.path.join(d, "rec_2.mp3")
    (tmp_path / "rec_2.wav").write_bytes(b"x")  # e.g. a fallback WAV from a failed encode
    assert RecordingEngine._unique_filepath(d, "rec", "mp3") == os.path.join(d, "rec_3.mp3")


def test_two_recordings_with_same_name_do_not_overwrite(tmp_path):
    engine = RecordingEngine(driver=MockAudioDriver())
    config = RecordingConfig(output_dir=str(tmp_path), filename_template="same")
    try:
        paths = []
        for _ in range(2):
            paths.append(engine.start_recording(config, include_time_shift=False))
            time.sleep(0.1)
            engine.stop_recording()
    finally:
        engine.shutdown()
    assert [os.path.basename(p) for p in paths] == ["same.wav", "same_2.wav"]
    assert all(os.path.exists(p) for p in paths)


# --- Conversion failure ---------------------------------------------------------------------

def test_failed_conversion_returns_existing_wav_and_reports_why(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_file_sink, "find_ffmpeg", lambda: None)
    sink = AudioFileSink()
    sink.open(str(tmp_path / "a.mp3"), FMT, OutputFormat.MP3)
    sink.write_chunk(_tone_chunk())
    path = sink.close()

    assert path == str(tmp_path / "a.wav")  # was: the non-existent .mp3 path
    assert os.path.exists(path)
    assert not os.path.exists(tmp_path / "a.mp3")
    assert "ffmpeg" in sink.last_conversion_error


def test_engine_reports_conversion_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_file_sink, "find_ffmpeg", lambda: None)
    errors = []
    handler = lambda msg, exc: errors.append(msg)
    EventBus().subscribe(EventType.ERROR_OCCURRED, handler)
    engine = RecordingEngine(driver=MockAudioDriver())
    try:
        engine.start_recording(RecordingConfig(output_dir=str(tmp_path), format=OutputFormat.MP3))
        time.sleep(0.1)
        path = engine.stop_recording()
    finally:
        engine.shutdown()
        EventBus().unsubscribe(EventType.ERROR_OCCURRED, handler)
    assert path.endswith(".wav") and os.path.exists(path)
    assert any("WAV で保存しました" in m for m in errors)


@pytest.mark.skipif(audio_file_sink.find_ffmpeg() is None, reason="ffmpeg not available")
def test_conversion_succeeds_with_project_ffmpeg(tmp_path):
    sink = AudioFileSink()
    sink.open(str(tmp_path / "a.mp3"), FMT, OutputFormat.MP3)
    sink.write_chunk(_tone_chunk())
    path = sink.close()
    assert path == str(tmp_path / "a.mp3") and os.path.getsize(path) > 1000
    assert sink.last_conversion_error is None


# --- Streaming resampler --------------------------------------------------------------------

def test_linear_resampler_is_continuous_across_blocks():
    src_rate, dst_rate = 44100, 48000
    t = np.arange(src_rate) / src_rate
    signal = np.column_stack([0.5 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)

    resampler = LinearResampler(src_rate, dst_rate)
    out = np.concatenate([resampler.process(signal[i:i + 1024]) for i in range(0, len(signal), 1024)])

    assert abs(len(out) - dst_rate) <= 2
    expected = 0.5 * np.sin(2 * np.pi * 440 * np.arange(len(out)) / dst_rate)
    assert np.max(np.abs(out[:, 0] - expected)) < 0.01  # no block-boundary glitches


# --- Device loss and reconnect --------------------------------------------------------------

class _FakeStream:
    """Delivers frames in real time at `rate`. Like a WASAPI stream whose device was
    invalidated, it raises once the world was unplugged after the stream was opened."""

    def __init__(self, rate, channels, world):
        self.rate, self.channels, self.world = rate, channels, world
        self.t0 = time.monotonic()
        self.consumed = 0

    def _check(self):
        unplugged_at = self.world.unplugged_at
        if unplugged_at is not None and self.t0 < unplugged_at <= time.monotonic():
            raise OSError("[Errno -9999] Unanticipated host error")

    def is_active(self):
        return True

    def get_read_available(self):
        self._check()
        return int((time.monotonic() - self.t0) * self.rate) - self.consumed

    def read(self, frames, exception_on_overflow=False):
        self._check()
        self.consumed += frames
        return np.full((frames, self.channels), 0.5, dtype=np.float32).tobytes()

    def stop_stream(self):
        pass

    def close(self):
        pass


class _World:
    """Which loopback devices exist right now (PortAudio sees a snapshot per PyAudio())."""

    def __init__(self):
        self.devices = []       # list of (name, rate)
        self.default = None       # name
        self.unplugged_at = None  # streams opened before this moment fail from then on


class _FakePyAudio:
    def __init__(self, world):
        self.world = world
        # Indices shift between snapshots, like real re-enumeration
        self.devs = [{"index": 0, "name": "MME dummy", "hostApi": 0}]
        for name, rate in world.devices:
            self.devs.append({
                "index": len(self.devs), "name": f"{name} [Loopback]", "hostApi": 1,
                "maxInputChannels": 2, "defaultSampleRate": float(rate), "isLoopbackDevice": True,
            })

    def get_host_api_info_by_type(self, _):
        return {"index": 1, "defaultOutputDevice": -1}

    def get_device_count(self):
        return len(self.devs)

    def get_device_info_by_index(self, i):
        return self.devs[i]

    def get_default_wasapi_loopback(self):
        return next((d for d in self.devs if d["name"] == f"{self.world.default} [Loopback]"), None)

    def open(self, format, channels, rate, input, input_device_index, frames_per_buffer):
        return _FakeStream(rate, channels, self.world)

    def terminate(self):
        pass


def _run_driver(world, schedule, duration):
    """Capture with a fake PyAudio; `schedule` is [(at_seconds, fn(world))] applied over time."""
    if not wasapi_driver.HAS_PYAUDIOWPATCH:
        pytest.skip("pyaudiowpatch not installed")
    driver = wasapi_driver.WasapiLoopbackDriver()
    driver._create_pyaudio = lambda: _FakePyAudio(world)
    driver.RECONNECT_INTERVAL_SECONDS = 0.15
    statuses, chunks = [], []
    driver.status_callback = lambda status, dev: statuses.append((status, dev.name if dev else None))

    start = time.monotonic()
    driver.start_capture(device=None, callback=chunks.append)
    for at, fn in schedule:
        time.sleep(max(0.0, start + at - time.monotonic()))
        fn(world, start)
    time.sleep(max(0.0, start + duration - time.monotonic()))
    driver.stop_capture()
    driver._pa = None
    return statuses, chunks


def _loud_spans(chunks, rate=48000):
    """[(start_s, end_s)] of consecutive non-silent chunks on the output timeline."""
    spans, pos, cur = [], 0, None
    for c in chunks:
        loud = bool(c.data.any())
        if loud and cur is None:
            cur = pos
        if not loud and cur is not None:
            spans.append((cur / rate, pos / rate))
            cur = None
        pos += c.num_frames
    if cur is not None:
        spans.append((cur / rate, pos / rate))
    return spans, pos / rate


def test_device_unplug_pads_silence_and_reconnects_same_device():
    world = _World()
    world.devices, world.default = [("ヘッドホン", 48000), ("スピーカー", 48000)], "ヘッドホン"

    def unplug(w, start):
        w.unplugged_at = time.monotonic()       # current stream starts failing
        w.devices = [("スピーカー", 48000)]      # headphones gone...
        w.default = "スピーカー"

    def replug(w, start):
        # ...and back, at a new index and a different native rate
        w.devices = [("スピーカー", 48000), ("ヘッドホン", 44100)]
        w.default = "ヘッドホン"

    statuses, chunks = _run_driver(world, [(0.3, unplug), (0.35, replug)], duration=1.2)

    assert statuses[0] == (DeviceStatus.LOST, "ヘッドホン")
    assert statuses[1] == (DeviceStatus.RESTORED, "ヘッドホン")
    # Output format never changes mid-session even though the device came back at 44.1 kHz
    assert all(c.format.sample_rate == 48000 and c.data.shape[1] == 2 for c in chunks)

    spans, total = _loud_spans(chunks)
    assert 1.0 <= total <= 1.3                      # timeline kept in real time
    assert len(spans) == 2                          # audio, silence while unplugged, audio
    assert spans[0][1] == pytest.approx(0.3, abs=0.08)
    assert spans[1][0] > spans[0][1]                # a silent gap was inserted


def test_device_gone_for_good_falls_back_to_new_default():
    world = _World()
    world.devices, world.default = [("ヘッドホン", 48000), ("スピーカー", 48000)], "ヘッドホン"

    def unplug(w, start):
        w.unplugged_at = time.monotonic()
        w.devices = [("スピーカー", 48000)]
        w.default = "スピーカー"

    statuses, chunks = _run_driver(world, [(0.2, unplug)], duration=0.8)
    assert statuses == [(DeviceStatus.LOST, "ヘッドホン"), (DeviceStatus.RESTORED, "スピーカー")]
    assert chunks[-1].data.any()


def test_engine_forwards_device_status_and_tracks_restored_device():
    driver = MockAudioDriver()
    engine = RecordingEngine(driver=driver)
    events = []
    handler = lambda status, dev: events.append((status, dev))
    EventBus().subscribe(EventType.DEVICE_STATUS, handler)
    _, headphones = driver.get_output_devices()
    try:
        engine.start_buffering()
        driver._notify_status(DeviceStatus.LOST, None)
        driver._notify_status(DeviceStatus.RESTORED, headphones)
        assert [e[0] for e in events] == [DeviceStatus.LOST, DeviceStatus.RESTORED]
        assert engine.capture_device.id == headphones.id
    finally:
        EventBus().unsubscribe(EventType.DEVICE_STATUS, handler)
        engine.shutdown()
