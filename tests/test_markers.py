"""
Tests for marker export (CUE sheet) and its integration with the recording engine.
"""

import os
import time

from src.core.engine import RecordingEngine
from src.core.models import Marker, OutputFormat, RecordingConfig
from src.drivers.mock_driver import MockAudioDriver
from src.encoders.marker_writer import _cue_timestamp, cue_path_for, export_cue


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def test_cue_timestamp_uses_75_frames_per_second():
    assert _cue_timestamp(0.0) == "00:00:00"
    assert _cue_timestamp(1.2) == "00:01:15"       # 0.2s = 15 frames
    assert _cue_timestamp(61.0) == "01:01:00"
    assert _cue_timestamp(6000.0) == "100:00:00"   # minutes are not capped at 99


def test_export_cue_layout(tmp_path):
    audio = str(tmp_path / "Recording_20261101_120000.wav")
    markers = [
        Marker(timestamp=75.2, label="Marker 2"),
        Marker(timestamp=12.0, label="Marker 1", note='says "hi"'),
    ]
    path = export_cue(markers, audio)
    assert path == cue_path_for(audio) == str(tmp_path / "Recording_20261101_120000.cue")

    text = _read(path)
    assert 'FILE "Recording_20261101_120000.wav" WAVE' in text
    # Implicit start track, then markers in time order
    assert text.index('TITLE "Start"') < text.index('TITLE "Marker 1"') < text.index('TITLE "Marker 2"')
    assert "TRACK 03 AUDIO" in text
    assert "INDEX 01 00:12:00" in text
    assert "INDEX 01 01:15:15" in text
    assert "REM NOTE \"says 'hi'\"" in text  # quotes can't be escaped in CUE


def test_export_cue_marker_at_zero_replaces_start_track_and_mp3_type(tmp_path):
    path = export_cue([Marker(timestamp=0.0, label="Intro")], str(tmp_path / "a.mp3"))
    text = _read(path)
    assert 'FILE "a.mp3" MP3' in text
    assert 'TITLE "Start"' not in text
    assert "TRACK 02" not in text


def test_export_cue_keeps_japanese_labels_with_bom(tmp_path):
    path = export_cue([Marker(timestamp=3.0, label="サビ")], str(tmp_path / "曲.wav"))
    with open(path, "rb") as f:
        raw = f.read()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "サビ" in raw.decode("utf-8-sig")


def _record_with_markers(tmp_path, n_markers, **config):
    engine = RecordingEngine(driver=MockAudioDriver())
    try:
        path = engine.start_recording(RecordingConfig(output_dir=str(tmp_path), **config))
        for i in range(n_markers):
            time.sleep(0.1)
            engine.add_marker(label=f"Marker {i + 1}")
        time.sleep(0.1)
        engine.stop_recording(keep_buffering=False)
    finally:
        engine.shutdown()
    return path


def test_engine_writes_cue_next_to_recording(tmp_path):
    path = _record_with_markers(tmp_path, 2, format=OutputFormat.FLAC)
    cue = cue_path_for(path)
    assert os.path.exists(cue)
    text = _read(cue)
    assert f'FILE "{os.path.basename(path)}" WAVE' in text
    assert 'TITLE "Marker 2"' in text


def test_engine_skips_cue_without_markers_or_when_disabled(tmp_path):
    no_markers = _record_with_markers(tmp_path / "a", 0)
    assert not os.path.exists(cue_path_for(no_markers))

    disabled = _record_with_markers(tmp_path / "b", 1, save_markers=False)
    assert not os.path.exists(cue_path_for(disabled))
