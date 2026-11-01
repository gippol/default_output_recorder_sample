"""
Marker exporters. Markers are written as a CUE sheet next to the recording, so players
such as foobar2000 / VLC can jump to each bookmark, and the file stays human-readable.
"""

import os
from typing import List
from src.core.models import Marker

# CUE INDEX positions are expressed in CD frames: 75 per second.
_CUE_FRAMES_PER_SECOND = 75

# FILE type keyword per audio extension. Players are lenient, but MP3 should say so.
_CUE_FILE_TYPES = {".mp3": "MP3"}


def _cue_timestamp(seconds: float) -> str:
    """Format seconds as CUE `mm:ss:ff` (minutes may exceed 99 for long recordings)."""
    total_frames = int(round(max(0.0, seconds) * _CUE_FRAMES_PER_SECOND))
    minutes, rem = divmod(total_frames, 60 * _CUE_FRAMES_PER_SECOND)
    secs, frames = divmod(rem, _CUE_FRAMES_PER_SECOND)
    return f"{minutes:02d}:{secs:02d}:{frames:02d}"


def _cue_quote(text: str) -> str:
    # CUE has no escape sequence for quotes; replace them so the line stays parseable.
    return '"' + text.replace('"', "'").replace("\r", " ").replace("\n", " ") + '"'


def cue_path_for(audio_path: str) -> str:
    return os.path.splitext(audio_path)[0] + ".cue"


def export_cue(markers: List[Marker], audio_path: str, output_path: str = "") -> str:
    """
    Write `markers` as a CUE sheet referencing `audio_path`. Each marker starts a track;
    a leading "Start" track is added unless a marker already sits at 0:00:00.
    Returns the path written.
    """
    output_path = output_path or cue_path_for(audio_path)
    ext = os.path.splitext(audio_path)[1].lower()
    file_type = _CUE_FILE_TYPES.get(ext, "WAVE")

    ordered = sorted(markers, key=lambda m: m.timestamp)
    tracks = [(m.label, m.note, m.timestamp) for m in ordered]
    if not tracks or _cue_timestamp(tracks[0][2]) != "00:00:00":
        tracks.insert(0, ("Start", "", 0.0))

    lines = [
        'REM COMMENT "System Output Audio Recorder markers"',
        f"FILE {_cue_quote(os.path.basename(audio_path))} {file_type}",
    ]
    for number, (label, note, timestamp) in enumerate(tracks, start=1):
        lines.append(f"  TRACK {number:02d} AUDIO")
        lines.append(f"    TITLE {_cue_quote(label)}")
        if note:
            lines.append(f"    REM NOTE {_cue_quote(note)}")
        lines.append(f"    INDEX 01 {_cue_timestamp(timestamp)}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    # UTF-8 with BOM: Windows players (foobar2000 etc.) otherwise assume the ANSI code page
    # and garble Japanese labels.
    with open(output_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return output_path
