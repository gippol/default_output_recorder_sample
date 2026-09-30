"""
AI Translation & Summarization Engines.
"""

from abc import ABC, abstractmethod
import os
from typing import List, Optional
from src.core.models import SubtitleSegment


class ITranslationEngine(ABC):
    """Abstract interface for AI translation & summarization."""

    @abstractmethod
    def translate_segments(
        self,
        segments: List[SubtitleSegment],
        target_lang: str = "en"
    ) -> List[SubtitleSegment]:
        """Translate subtitle segments to target language."""
        pass

    @abstractmethod
    def generate_summary(self, segments: List[SubtitleSegment]) -> str:
        """Generate a concise meeting/audio summary."""
        pass


class GeminiTranslationEngine(ITranslationEngine):
    """
    LLM-powered translation and meeting summarization using Google Gemini API.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

    def translate_segments(
        self,
        segments: List[SubtitleSegment],
        target_lang: str = "en"
    ) -> List[SubtitleSegment]:
        if not self.api_key:
            # Fallback if no API key
            for seg in segments:
                seg.translated_text = f"[Translated to {target_lang}]: {seg.text}"
            return segments

        # If google-genai is installed
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            full_text = "\n".join([f"{i}: {s.text}" for i, s in enumerate(segments)])
            prompt = f"Translate the following numbered lines into {target_lang}. Keep line numbers.\n\n{full_text}"
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            # Parse responses
            lines = response.text.strip().split("\n")
            for line in lines:
                if ":" in line:
                    idx_str, trans = line.split(":", 1)
                    try:
                        idx = int(idx_str.strip())
                        if 0 <= idx < len(segments):
                            segments[idx].translated_text = trans.strip()
                    except ValueError:
                        pass
        except Exception as e:
            print(f"[GeminiTranslation] Translation error: {e}")
            for seg in segments:
                seg.translated_text = f"[{target_lang}]: {seg.text}"

        return segments

    def generate_summary(self, segments: List[SubtitleSegment]) -> str:
        full_text = " ".join([s.text for s in segments])
        if not self.api_key or len(full_text.strip()) == 0:
            return "録音データの文字起こしが完了しました。"

        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            prompt = f"以下の音声文字起こしテキストから、要点を箇条書きで分かりやすく要約してください：\n\n{full_text}"
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            return f"要約生成エラー: {e}"
