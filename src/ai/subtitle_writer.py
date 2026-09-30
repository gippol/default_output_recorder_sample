"""
Subtitle and Transcript Exporters for SRT, VTT, TXT, and Markdown formats.
"""

from datetime import timedelta
import os
from typing import List, Optional
from src.core.models import SubtitleSegment


def _format_timestamp_srt(seconds: float) -> str:
    """Format seconds into SRT timestamp: HH:MM:SS,mmm"""
    td = timedelta(seconds=max(0.0, seconds))
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Format seconds into WebVTT timestamp: HH:MM:SS.mmm"""
    return _format_timestamp_srt(seconds).replace(",", ".")


def export_srt(segments: List[SubtitleSegment], output_path: str, include_translation: bool = False) -> str:
    """Export subtitle segments as SubRip (.srt) file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, start=1):
            start_str = _format_timestamp_srt(seg.start_seconds)
            end_str = _format_timestamp_srt(seg.end_seconds)
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{seg.text}\n")
            if include_translation and seg.translated_text:
                f.write(f"{seg.translated_text}\n")
            f.write("\n")
    return output_path


def export_vtt(segments: List[SubtitleSegment], output_path: str, include_translation: bool = False) -> str:
    """Export subtitle segments as WebVTT (.vtt) file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for idx, seg in enumerate(segments, start=1):
            start_str = _format_timestamp_vtt(seg.start_seconds)
            end_str = _format_timestamp_vtt(seg.end_seconds)
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{seg.text}\n")
            if include_translation and seg.translated_text:
                f.write(f"{seg.translated_text}\n")
            f.write("\n")
    return output_path


def export_markdown(
    segments: List[SubtitleSegment],
    output_path: str,
    title: str = "録音議事録 & 文字起こし",
    summary: Optional[str] = None
) -> str:
    """Export transcript and AI summary as a formatted Markdown file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# 📝 {title}\n\n")
        if summary:
            f.write("## 💡 AI要約 (Summary)\n")
            f.write(f"{summary}\n\n")
            f.write("---\n\n")

        f.write("## 🕒 タイムライン文字起こし (Transcript)\n\n")
        for seg in segments:
            start_str = _format_timestamp_srt(seg.start_seconds)[:8] # HH:MM:SS
            speaker_tag = f"**[{seg.speaker}]** " if seg.speaker else ""
            f.write(f"- **`{start_str}`** {speaker_tag}{seg.text}\n")
            if seg.translated_text:
                f.write(f"  > 🌐 *{seg.translated_text}*\n")
            f.write("\n")
    return output_path
