"""
Tests for silence skipping ("無音区間の自動スキップ"): VAD marks silence, SilenceSkipFilter
leaves long silences out of the file, and the level meter keeps seeing every chunk.
"""

import time

import numpy as np
import soundfile as sf

from src.core.engine import RecordingEngine
from src.core.event_bus import EventBus, EventType
from src.core.models import AudioChunk, AudioFormat, RecordingConfig
from src.core.pipeline import SilenceSkipFilter, VADFilter
from src.drivers.mock_driver import MockAudioDriver

RATE = 48000
FMT = AudioFormat(sample_rate=RATE, channels=2)
CHUNK = 4800  # 0.1 s


def _chunk(loud: bool) -> AudioChunk:
    if loud:
        t = np.arange(CHUNK) / RATE
        mono = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    else:
        mono = np.zeros(CHUNK, dtype=np.float32)
    return AudioChunk(data=np.column_stack([mono, mono]), timestamp=time.time(), format=FMT)


class _ManualDriver(MockAudioDriver):
    """Mock driver that emits nothing by itself; the test feeds chunks."""

    def start_capture(self, device, callback, audio_format=None):
        self._format = audio_format or self._format
        self.capturing_device = device or self.get_default_output_device()
        self._is_capturing = True
        self.callback = callback

    def stop_capture(self):
        self._is_capturing = False
        self.capturing_device = None


def test_vad_marks_but_never_drops():
    vad = VADFilter(threshold_db=-45.0)
    assert vad.process(_chunk(False)).is_silent
    assert not vad.process(_chunk(True)).is_silent


def test_silence_skip_keeps_hangover_then_drops_and_resets():
    vad, skip = VADFilter(threshold_db=-45.0), SilenceSkipFilter(hangover_seconds=0.3)

    def run(loud):
        return skip.process(vad.process(_chunk(loud))) is not None

    assert run(True)
    # 0.1, 0.2, 0.3 s of silence are kept (pause / tail), 0.4 s onward is dropped
    assert [run(False) for _ in range(5)] == [True, True, True, False, False]
    # Sound resumes: kept, and the silence counter starts over
    assert run(True)
    assert run(False)


def _record(tmp_path, pattern, **config):
    """Feed loud(True)/silent(False) 0.1 s chunks while recording; return (frames, meter count)."""
    driver = _ManualDriver()
    engine = RecordingEngine(driver=driver)
    meter_updates = []
    on_meter = lambda telemetry: meter_updates.append(telemetry)
    EventBus().subscribe(EventType.TELEMETRY_UPDATE, on_meter)
    try:
        path = engine.start_recording(
            RecordingConfig(output_dir=str(tmp_path), **config), include_time_shift=False
        )
        meter_updates.clear()
        for loud in pattern:
            driver.callback(_chunk(loud))
        duration = engine.current_recording_duration
        path = engine.stop_recording(keep_buffering=False)
    finally:
        EventBus().unsubscribe(EventType.TELEMETRY_UPDATE, on_meter)
        engine.shutdown()
    return sf.info(path).frames, duration, meter_updates


PATTERN = [True] * 5 + [False] * 30 + [True] * 5  # 0.5 s sound, 3 s silence, 0.5 s sound


def test_engine_leaves_long_silence_out_of_file(tmp_path):
    frames, duration, meter = _record(tmp_path, PATTERN, enable_vad=True, vad_hangover_seconds=1.0)
    # 0.5 + 1.0 (hangover) + 0.5 seconds written
    assert frames == 20 * CHUNK
    # Marker positions follow the file, not wall-clock time
    assert abs(duration - 2.0) < 1e-6
    # Meter saw every chunk, including the dropped silence, and showed it as silent
    assert len(meter) == len(PATTERN)
    assert not meter[-6].is_speaking


def test_engine_keeps_everything_without_vad(tmp_path):
    frames, _, _ = _record(tmp_path, PATTERN, enable_vad=False)
    assert frames == len(PATTERN) * CHUNK
