"""
Unified Audio File Sink supporting WAV and Compressed Formats (MP3, AAC, FLAC, OGG, Opus).
Uses direct streaming writes for minimal latency and memory footprint.
"""

import os
import shutil
import tempfile
import threading
from typing import Optional
import numpy as np
import soundfile as sf
from src.core.models import AudioChunk, AudioFormat, OutputFormat
from src.encoders.base import IAudioSink


class AudioFileSink(IAudioSink):
    """
    Writes incoming AudioChunks directly to disk.
    - WAV / FLAC / OGG: Written in real-time via libsndfile.
    - MP3 / AAC: Streamed to high-quality temp WAV, then converted at finalize.
    """

    def __init__(self):
        self._filepath: Optional[str] = None
        self._target_format: OutputFormat = OutputFormat.WAV
        self._audio_format: Optional[AudioFormat] = None
        self._bitrate_kbps: int = 320
        self._sf_file: Optional[sf.SoundFile] = None
        self._temp_wav_path: Optional[str] = None
        self._is_open = False
        self._lock = threading.Lock()
        self._total_frames = 0

    def open(
        self,
        filepath: str,
        audio_format: AudioFormat,
        output_format: OutputFormat = OutputFormat.WAV,
        bitrate_kbps: int = 320
    ) -> None:
        with self._lock:
            if self._is_open:
                self.close()

            self._filepath = filepath
            self._target_format = output_format
            self._audio_format = audio_format
            self._bitrate_kbps = bitrate_kbps
            self._total_frames = 0

            # Ensure destination directory exists
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

            # Native soundfile formats: WAV, FLAC, OGG
            if output_format == OutputFormat.WAV:
                self._sf_file = sf.SoundFile(
                    filepath,
                    mode="w",
                    samplerate=audio_format.sample_rate,
                    channels=audio_format.channels,
                    subtype="PCM_16",
                    format="WAV"
                )
                self._temp_wav_path = None
            elif output_format == OutputFormat.FLAC:
                self._sf_file = sf.SoundFile(
                    filepath,
                    mode="w",
                    samplerate=audio_format.sample_rate,
                    channels=audio_format.channels,
                    format="FLAC"
                )
                self._temp_wav_path = None
            elif output_format == OutputFormat.OGG:
                self._sf_file = sf.SoundFile(
                    filepath,
                    mode="w",
                    samplerate=audio_format.sample_rate,
                    channels=audio_format.channels,
                    format="OGG",
                    subtype="VORBIS"
                )
                self._temp_wav_path = None
            else:
                # MP3 / AAC / Opus: Write to temp WAV first, then convert on close
                temp_fd, self._temp_wav_path = tempfile.mkstemp(suffix=".wav")
                os.close(temp_fd)
                self._sf_file = sf.SoundFile(
                    self._temp_wav_path,
                    mode="w",
                    samplerate=audio_format.sample_rate,
                    channels=audio_format.channels,
                    subtype="PCM_16",
                    format="WAV"
                )

            self._is_open = True

    def write_chunk(self, chunk: AudioChunk) -> None:
        with self._lock:
            if not self._is_open or self._sf_file is None:
                return

            data = chunk.data
            if len(data) == 0:
                return

            # Ensure 2D float32 array
            if data.ndim == 1:
                data = data[:, np.newaxis]

            # Channel matching if needed
            expected_channels = self._audio_format.channels if self._audio_format else 2
            if data.shape[1] != expected_channels:
                if data.shape[1] == 1 and expected_channels == 2:
                    data = np.column_stack([data, data])
                elif data.shape[1] > expected_channels:
                    data = data[:, :expected_channels]

            self._sf_file.write(data)
            self._total_frames += len(data)

    def close(self) -> str:
        with self._lock:
            if not self._is_open:
                return self._filepath or ""

            if self._sf_file:
                self._sf_file.flush()
                self._sf_file.close()
                self._sf_file = None

            self._is_open = False
            final_path = self._filepath

            # If compression conversion is needed (MP3, AAC/M4A, Opus)
            if self._temp_wav_path and os.path.exists(self._temp_wav_path):
                try:
                    self._convert_temp_wav_to_target(self._temp_wav_path, self._filepath, self._target_format)
                finally:
                    if os.path.exists(self._temp_wav_path):
                        try:
                            os.remove(self._temp_wav_path)
                        except Exception:
                            pass
                    self._temp_wav_path = None

            return final_path or ""

    def _convert_temp_wav_to_target(self, src_wav: str, dst_file: str, fmt: OutputFormat) -> None:
        """Convert temporary WAV file to compressed format using pydub."""
        temp_encoded_path = None
        try:
            from pydub import AudioSegment
            audio_seg = AudioSegment.from_wav(src_wav)

            # Export to a temporary destination first to avoid leaving empty/corrupt files on failure
            ext = os.path.splitext(dst_file)[1]
            temp_fd, temp_encoded_path = tempfile.mkstemp(suffix=ext)
            os.close(temp_fd)

            if fmt == OutputFormat.MP3:
                audio_seg.export(temp_encoded_path, format="mp3", bitrate=f"{self._bitrate_kbps}k")
            elif fmt == OutputFormat.AAC:
                audio_seg.export(temp_encoded_path, format="ipod", bitrate=f"{self._bitrate_kbps}k") # m4a/aac container
            elif fmt == OutputFormat.OPUS:
                audio_seg.export(temp_encoded_path, format="opus", bitrate=f"{self._bitrate_kbps}k")
            else:
                shutil.copy2(src_wav, dst_file)
                return

            if os.path.exists(dst_file):
                os.remove(dst_file)
            shutil.move(temp_encoded_path, dst_file)
            temp_encoded_path = None

        except Exception as e:
            print(f"[AudioFileSink] Warning: Compression conversion failed ({e}). Saving as WAV fallback.")
            if os.path.exists(dst_file):
                try:
                    os.remove(dst_file)
                except Exception:
                    pass
            fallback_path = os.path.splitext(dst_file)[0] + ".wav"
            shutil.copy2(src_wav, fallback_path)
        finally:
            if temp_encoded_path and os.path.exists(temp_encoded_path):
                try:
                    os.remove(temp_encoded_path)
                except Exception:
                    pass

    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    @property
    def total_frames(self) -> int:
        with self._lock:
            return self._total_frames
