"""
Tests for device selection, WASAPI device listing, and device-native format handling.
"""

import time
import numpy as np
import pytest
import soundfile as sf

from src.core.engine import RecordingEngine
from src.core.models import OutputFormat, RecordingConfig
from src.drivers import wasapi_driver
from src.drivers.mock_driver import MockAudioDriver
from src.encoders.audio_file_sink import mix_to_channels


# --- 1. Device selection -----------------------------------------------------------

def test_switch_device_while_buffering_reopens_capture():
    driver = MockAudioDriver()
    engine = RecordingEngine(driver=driver)
    speakers, headphones = driver.get_output_devices()
    try:
        engine.start_buffering()
        assert driver.capturing_device.id == speakers.id

        engine.switch_device(headphones)
        assert driver.is_capturing()
        assert driver.capturing_device.id == headphones.id
        assert engine.capture_device.id == headphones.id
    finally:
        engine.shutdown()


def test_start_recording_uses_configured_device(tmp_path):
    """Regression: buffering on the default device used to make config.device_id ignored."""
    driver = MockAudioDriver()
    engine = RecordingEngine(driver=driver)
    _, headphones = driver.get_output_devices()
    try:
        engine.start_buffering()
        engine.start_recording(RecordingConfig(output_dir=str(tmp_path), device_id=headphones.id))
        assert driver.capturing_device.id == headphones.id
        engine.stop_recording(keep_buffering=False)
    finally:
        engine.shutdown()


def test_switch_device_rejected_while_recording(tmp_path):
    driver = MockAudioDriver()
    engine = RecordingEngine(driver=driver)
    _, headphones = driver.get_output_devices()
    try:
        engine.start_recording(RecordingConfig(output_dir=str(tmp_path)))
        with pytest.raises(RuntimeError):
            engine.switch_device(headphones)
        engine.stop_recording(keep_buffering=False)
    finally:
        engine.shutdown()


# --- 2. WASAPI device listing ----------------------------------------------------------

class _FakePyAudio:
    """Mimics what PyAudioWPatch reported on a real machine (one output + loopback pair each)."""

    def __init__(self):
        self.devices = [
            {"index": 0, "name": "MME Speakers", "hostApi": 0, "maxOutputChannels": 2},
            {"index": 1, "name": "ヘッドホン (REDMI Buds 8 Lite)", "hostApi": 1,
             "maxInputChannels": 0, "maxOutputChannels": 2, "defaultSampleRate": 48000.0},
            {"index": 2, "name": "スピーカー (Realtek(R) Audio)", "hostApi": 1,
             "maxInputChannels": 0, "maxOutputChannels": 6, "defaultSampleRate": 44100.0},
            {"index": 3, "name": "ヘッドホン (REDMI Buds 8 Lite) [Loopback]", "hostApi": 1,
             "maxInputChannels": 2, "maxOutputChannels": 0, "defaultSampleRate": 48000.0,
             "isLoopbackDevice": True},
            {"index": 4, "name": "スピーカー (Realtek(R) Audio) [Loopback]", "hostApi": 1,
             "maxInputChannels": 6, "maxOutputChannels": 0, "defaultSampleRate": 44100.0,
             "isLoopbackDevice": True},
        ]

    def get_host_api_info_by_type(self, _type):
        return {"index": 1, "defaultOutputDevice": 1}

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, i):
        return self.devices[i]

    def get_default_wasapi_loopback(self):
        return self.devices[3]


@pytest.fixture
def fake_wasapi(monkeypatch):
    if not wasapi_driver.HAS_PYAUDIOWPATCH:
        pytest.skip("pyaudiowpatch not installed")
    driver = wasapi_driver.WasapiLoopbackDriver()
    driver._pa = _FakePyAudio()
    yield driver
    driver._pa = None  # don't call terminate() on the fake


def test_wasapi_lists_only_loopbacks_with_intact_japanese_names(fake_wasapi):
    devices = fake_wasapi.get_output_devices()
    assert [d.id for d in devices] == [3, 4]
    assert [d.name for d in devices] == ["ヘッドホン (REDMI Buds 8 Lite)", "スピーカー (Realtek(R) Audio)"]


def test_wasapi_default_flag_points_at_default_loopback(fake_wasapi):
    default = fake_wasapi.get_default_output_device()
    assert default.id == 3
    assert [d.is_default for d in fake_wasapi.get_output_devices()] == [True, False]


# --- 2b. Silence gaps in WASAPI loopback ------------------------------------------------

class _FakeLoopbackStream:
    """
    Behaves like a WASAPI loopback stream: frames accrue in real time only inside the
    `playing` windows (seconds since creation); outside them nothing is delivered.
    """

    def __init__(self, sample_rate, channels, playing):
        self.rate, self.channels, self.playing = sample_rate, channels, playing
        self.t0 = time.monotonic()
        self.consumed = 0

    def _produced(self):
        now = time.monotonic() - self.t0
        return int(sum(max(0.0, min(now, end) - start) for start, end in self.playing) * self.rate)

    def is_active(self):
        return True

    def get_read_available(self):
        return self._produced() - self.consumed

    def read(self, frames, exception_on_overflow=False):
        self.consumed += frames
        return np.full((frames, self.channels), 0.5, dtype=np.float32).tobytes()


def _run_worker(playing, duration, rate=48000, channels=2):
    if not wasapi_driver.HAS_PYAUDIOWPATCH:
        pytest.skip("pyaudiowpatch not installed")
    import threading
    from src.core.models import AudioFormat

    driver = wasapi_driver.WasapiLoopbackDriver()
    driver._stream = _FakeLoopbackStream(rate, channels, playing)
    driver._current_format = AudioFormat(sample_rate=rate, channels=channels)
    chunks = []
    worker = threading.Thread(target=driver._capture_worker, args=(chunks.append,))
    worker.start()
    time.sleep(duration)
    driver._stop_event.set()
    worker.join(timeout=2)
    driver._stream = None
    return chunks


def test_wasapi_fills_pure_silence_in_real_time():
    """Nothing playing for 1s must still yield ~1s of (silent) audio, not 0s."""
    chunks = _run_worker(playing=[], duration=1.0)
    total = sum(c.num_frames for c in chunks) / 48000
    assert 0.8 <= total <= 1.05
    assert all(c.is_silent and not c.data.any() for c in chunks)


def test_wasapi_keeps_timeline_across_silence_gap():
    """Audio 0-0.3s, silence, audio 0.8-1.1s: the second burst must start ~0.8s in."""
    chunks = _run_worker(playing=[(0.0, 0.3), (0.8, 1.1)], duration=1.3)
    position, starts = 0, []
    prev_loud = False
    for c in chunks:
        loud = bool(c.data.any())
        if loud and not prev_loud:
            starts.append(position / 48000)
        prev_loud = loud
        position += c.num_frames
    assert len(starts) == 2
    assert starts[0] < 0.05
    assert 0.7 <= starts[1] <= 0.9
    assert 1.0 <= position / 48000 <= 1.35


def test_wasapi_inserts_no_silence_while_audio_flows():
    chunks = _run_worker(playing=[(0.0, 5.0)], duration=0.6)
    assert chunks and all(c.data.any() for c in chunks)


# --- 3. Device-native format ---------------------------------------------------------------

def test_mix_to_channels_51_keeps_centre_and_drops_lfe():
    frames = 4
    data = np.zeros((frames, 6), dtype=np.float32)
    data[:, 2] = 0.5  # centre (dialogue)
    data[:, 3] = 0.9  # LFE
    stereo = mix_to_channels(data, 2)
    assert stereo.shape == (frames, 2)
    np.testing.assert_allclose(stereo[:, 0], 0.5 * 0.7071, rtol=1e-4)
    np.testing.assert_allclose(stereo[:, 1], 0.5 * 0.7071, rtol=1e-4)


def test_mix_to_channels_mono_and_passthrough():
    mono = np.full((3, 1), 0.25, dtype=np.float32)
    assert mix_to_channels(mono, 2).shape == (3, 2)
    stereo = np.random.rand(3, 2).astype(np.float32)
    assert mix_to_channels(stereo, 2) is stereo


def test_recording_uses_device_sample_rate_and_downmixes(tmp_path):
    """A 44.1kHz 5.1 device must produce a 44.1kHz stereo file, not a 48kHz-labelled one."""
    driver = MockAudioDriver(sample_rate=44100, channels=6)
    engine = RecordingEngine(driver=driver)
    try:
        engine.start_buffering()
        time.sleep(0.1)
        path = engine.start_recording(
            RecordingConfig(output_dir=str(tmp_path), format=OutputFormat.WAV), include_time_shift=True
        )
        time.sleep(0.3)
        engine.stop_recording(keep_buffering=False)
    finally:
        engine.shutdown()

    info = sf.info(path)
    assert info.samplerate == 44100
    assert info.channels == 2
    assert info.duration > 0.2


# --- 4. Marker / duration alignment with the saved file ----------------------------------

def _record(tmp_path, steps, time_shift=True):
    """Run a mock recording; `steps` is a callable given the engine while recording."""
    engine = RecordingEngine(driver=MockAudioDriver())
    stopped = {}
    try:
        engine.start_buffering(time_shift_seconds=30)
        time.sleep(0.5)  # ~0.5s of pre-roll in the ring buffer
        path = engine.start_recording(RecordingConfig(output_dir=str(tmp_path)), include_time_shift=time_shift)
        markers = steps(engine)
        stopped["duration"] = engine.current_recording_duration
        engine.stop_recording(keep_buffering=False)
    finally:
        engine.shutdown()
    return path, markers, stopped["duration"]


def test_marker_offset_includes_time_shift_preroll(tmp_path):
    def steps(engine):
        time.sleep(0.3)
        return [engine.add_marker()]

    path, (marker,), _ = _record(tmp_path, steps)
    # Marker sits ~0.5s pre-roll + ~0.3s live into the file (old code reported ~0.3s)
    assert 0.65 <= marker.timestamp <= 0.95
    assert marker.timestamp <= sf.info(path).duration


def test_marker_offset_excludes_pause(tmp_path):
    def steps(engine):
        time.sleep(0.2)
        engine.pause_recording()
        time.sleep(0.5)
        engine.resume_recording()
        time.sleep(0.2)
        return [engine.add_marker()]

    _, (marker,), _ = _record(tmp_path, steps, time_shift=False)
    assert 0.3 <= marker.timestamp <= 0.55


def test_reported_duration_matches_file_and_has_no_seam_glitch(tmp_path):
    def steps(engine):
        time.sleep(0.4)
        return []

    path, _, duration = _record(tmp_path, steps)
    data, sr = sf.read(path)
    assert abs(duration - len(data) / sr) < 0.05

    # The mock emits one continuous sine; a dropped or duplicated chunk at the
    # pre-roll/live seam would show up as a jump far larger than one sample step.
    max_step = 2 * np.pi * 440 / sr * 0.5
    assert np.max(np.abs(np.diff(data[:, 0]))) <= max_step * 1.2
