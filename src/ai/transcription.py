"""
Speech-to-Text Transcription interface and implementations (Whisper / faster-whisper / Mock).
"""

from abc import ABC, abstractmethod
from typing import Callable, List, Optional
from src.core.models import SubtitleSegment


class ITranscriptionEngine(ABC):
    """Abstract interface for speech transcription engines."""

    @abstractmethod
    def transcribe(
        self,
        audio_filepath: str,
        language: Optional[str] = "ja",
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[SubtitleSegment]:
        """Transcribe an audio file into timestamped subtitle segments."""
        pass


class WhisperTranscriptionEngine(ITranscriptionEngine):
    """
    Local GPU/CPU Whisper transcription using faster-whisper.
    """

    def __init__(self, model_size: str = "base", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                compute_type = "float16" if self.device == "cuda" else "int8"
                self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
            except ImportError:
                raise RuntimeError(
                    "faster-whisper is not installed. Please install via 'pip install faster-whisper' to enable local AI transcription."
                )

    def transcribe(
        self,
        audio_filepath: str,
        language: Optional[str] = "ja",
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[SubtitleSegment]:
        self._load_model()
        segments, info = self._model.transcribe(
            audio_filepath,
            language=language,
            beam_size=5,
            vad_filter=True
        )

        results: List[SubtitleSegment] = []
        total_duration = info.duration if info.duration > 0 else 1.0

        for seg in segments:
            results.append(SubtitleSegment(
                start_seconds=seg.start,
                end_seconds=seg.end,
                text=seg.text.strip(),
                confidence=float(seg.avg_logprob)
            ))
            if progress_callback:
                progress_callback(min(1.0, seg.end / total_duration))

        return results


class MockTranscriptionEngine(ITranscriptionEngine):
    """Fallback / Mock transcription for development and testing."""

    def transcribe(
        self,
        audio_filepath: str,
        language: Optional[str] = "ja",
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[SubtitleSegment]:
        if progress_callback:
            progress_callback(1.0)

        return [
            SubtitleSegment(start_seconds=0.0, end_seconds=3.5, text="システム音声の録音が正常に開始されました。"),
            SubtitleSegment(start_seconds=4.0, end_seconds=8.2, text="高音質WASAPI Loopbackによるキャプチャを実行中です。"),
            SubtitleSegment(start_seconds=9.0, end_seconds=14.5, text="AI文字起こし機能により、字幕が自動生成されます。"),
        ]
