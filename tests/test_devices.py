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
