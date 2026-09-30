"""
Unit & Integration Tests for Audio Recording Core Engine.
Tests Ring Buffer, Pipeline Filters, Audio File Sinks, and State Machine.
"""

import os
import shutil
import tempfile
import time
import numpy as np
import pytest

from src.core.models import AudioChunk, AudioFormat, OutputFormat, RecordingConfig, RecordingState
from src.core.ring_buffer import AudioRingBuffer
from src.core.pipeline import AudioPipeline, PeakMeterFilter, VADFilter, GainNormalizerFilter
from src.core.state_machine import RecordingStateMachine, InvalidStateTransitionError
from src.core.engine import RecordingEngine
from src.drivers.mock_driver import MockAudioDriver
from src.encoders.audio_file_sink import AudioFileSink


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_chunk():
    # 48kHz, stereo, 1024 frames sine wave
    t = np.linspace(0, 1024 / 48000, 1024, endpoint=False)
    sine = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    stereo = np.column_stack([sine, sine])
    return AudioChunk(
        data=stereo,
        timestamp=time.time(),
        format=AudioFormat(sample_rate=48000, channels=2)
    )


def test_ring_buffer_capacity(sample_chunk):
    """Test that RingBuffer honors time capacity and drops oldest chunks."""
    # 1024 frames at 48000Hz is ~0.0213 seconds
    chunk_dur = sample_chunk.duration
    buffer = AudioRingBuffer(capacity_seconds=chunk_dur * 3.0)

    assert buffer.is_empty
    buffer.push(sample_chunk)
    buffer.push(sample_chunk)
    buffer.push(sample_chunk)
    buffer.push(sample_chunk)
    buffer.push(sample_chunk)

    # Should not exceed ~3-4 chunks
    snapshot = buffer.get_snapshot()
    assert len(snapshot) <= 4
    assert buffer.current_duration <= chunk_dur * 3.5


def test_pipeline_filters(sample_chunk):
    """Test audio filters in the pipeline chain."""
    pipeline = AudioPipeline()
    pipeline.add_filter(VADFilter(threshold_db=-60.0))
    pipeline.add_filter(GainNormalizerFilter(target_peak_db=-1.0))
    pipeline.add_filter(PeakMeterFilter(emit_event=False))

    processed = pipeline.process(sample_chunk)
    assert processed is not None
    assert not processed.is_silent
    # Peak should be amplified close to target
    max_val = np.max(np.abs(processed.data))
    assert max_val > 0.4


def test_state_machine():
    """Test state machine valid and invalid transitions."""
    sm = RecordingStateMachine()
    assert sm.current_state == RecordingState.IDLE

    sm.transition_to(RecordingState.BUFFERING)
    assert sm.is_buffering()

    sm.transition_to(RecordingState.RECORDING)
    assert sm.is_recording()

    sm.transition_to(RecordingState.PAUSED)
    assert sm.is_paused()

    sm.transition_to(RecordingState.RECORDING)
    sm.transition_to(RecordingState.FINALIZING)
    sm.transition_to(RecordingState.IDLE)

    with pytest.raises(InvalidStateTransitionError):
        # Cannot jump from IDLE to PAUSED directly
        sm.transition_to(RecordingState.PAUSED)


def test_wav_and_compressed_file_sink(temp_dir, sample_chunk):
    """Test writing audio to WAV and FLAC files."""
    fmt = AudioFormat(sample_rate=48000, channels=2)

    # 1. Test WAV
    wav_path = os.path.join(temp_dir, "test.wav")
    sink = AudioFileSink()
    sink.open(wav_path, fmt, OutputFormat.WAV)
    for _ in range(10):
        sink.write_chunk(sample_chunk)
    saved_wav = sink.close()

    assert os.path.exists(saved_wav)
    assert os.path.getsize(saved_wav) > 1000

    # 2. Test FLAC
    flac_path = os.path.join(temp_dir, "test.flac")
    sink.open(flac_path, fmt, OutputFormat.FLAC)
    for _ in range(10):
        sink.write_chunk(sample_chunk)
    saved_flac = sink.close()

    assert os.path.exists(saved_flac)
    assert os.path.getsize(saved_flac) > 500


def test_recording_engine_mock_integration(temp_dir):
    """End-to-end integration test with Mock Audio Driver."""
    mock_driver = MockAudioDriver(frequency=440.0)
    engine = RecordingEngine(driver=mock_driver)

    config = RecordingConfig(
        output_dir=temp_dir,
        filename_template="integration_test_{date}_{time}",
        format=OutputFormat.WAV,
        enable_time_shift=True,
        time_shift_seconds=5
    )

    # 1. Start buffering (time-shift)
    engine.start_buffering()
    time.sleep(0.1)
    assert not engine.ring_buffer.is_empty

    # 2. Start recording
    filepath = engine.start_recording(config, include_time_shift=True)
    assert engine.state_machine.is_recording()
    time.sleep(0.3)

    # 3. Add marker
    marker = engine.add_marker(label="Highlight Point")
    assert marker is not None

    # 4. Pause & Resume
    engine.pause_recording()
    assert engine.state_machine.is_paused()
    time.sleep(0.1)
    engine.resume_recording()
    assert engine.state_machine.is_recording()
    time.sleep(0.2)

    # 5. Stop recording
    final_path = engine.stop_recording(keep_buffering=False)
    assert final_path == filepath
    assert os.path.exists(final_path)
    assert os.path.getsize(final_path) > 1000

    engine.shutdown()
