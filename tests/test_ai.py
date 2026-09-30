"""
Unit Tests for AI Transcription, Translation, and Subtitle Exporters.
"""

import os
import tempfile
from src.core.models import SubtitleSegment
from src.ai.subtitle_writer import export_srt, export_vtt, export_markdown
from src.ai.transcription import MockTranscriptionEngine
from src.ai.translation import GeminiTranslationEngine


def test_mock_transcription_and_translation():
    engine = MockTranscriptionEngine()
    segments = engine.transcribe("dummy.wav", language="ja")
    assert len(segments) == 3
    assert "録音" in segments[0].text

    translator = GeminiTranslationEngine(api_key=None)
    translated_segments = translator.translate_segments(segments, target_lang="en")
    assert translated_segments[0].translated_text is not None


def test_subtitle_exporters():
    segments = [
        SubtitleSegment(0.0, 3.5, "こんにちは、世界！", "Hello, World!"),
        SubtitleSegment(4.0, 7.2, "システム音声を録音中。", "Recording system audio.")
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. SRT Export
        srt_path = os.path.join(tmpdir, "test.srt")
        export_srt(segments, srt_path, include_translation=True)
        assert os.path.exists(srt_path)
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "00:00:00,000 --> 00:00:03,500" in content
            assert "こんにちは、世界！" in content
            assert "Hello, World!" in content

        # 2. VTT Export
        vtt_path = os.path.join(tmpdir, "test.vtt")
        export_vtt(segments, vtt_path, include_translation=True)
        assert os.path.exists(vtt_path)
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "WEBVTT" in content
            assert "00:00:00.000 --> 00:00:03.500" in content

        # 3. Markdown Export
        md_path = os.path.join(tmpdir, "test.md")
        export_markdown(segments, md_path, summary="テスト音声の要約です。")
        assert os.path.exists(md_path)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# 📝 録音議事録 & 文字起こし" in content
            assert "テスト音声の要約です。" in content
            assert "こんにちは、世界！" in content
