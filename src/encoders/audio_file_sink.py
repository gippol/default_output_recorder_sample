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
from src.core.dsp import mix_to_channels, output_channels_for  # noqa: F401 (re-exported)
from src.core.models import AudioChunk, AudioFormat, OutputFormat
from src.encoders.base import IAudioSink


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_ffmpeg() -> Optional[str]:
    """
    Absolute path to ffmpeg: from PATH, else an ffmpeg(.exe) in the project root.
    pydub only *checks* for ffmpeg and then launches the bare name "ffmpeg", which fails
    when the binary sits next to main.py but is not on PATH, so callers must set
    AudioSegment.converter to this path.
    """
    found = shutil.which("ffmpeg")
    if found:
        return os.path.abspath(found)
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = os.path.join(_PROJECT_ROOT, name)
        if os.path.isfile(candidate):
            return candidate
    return None


# libsndfile command: write RF64, but rewrite the header as plain RIFF/WAVE on close if the
# file stayed under 4 GB. Not exposed by soundfile's public API.
_SFC_RF64_AUTO_DOWNGRADE = 0x1210


def _open_wav_for_streaming(path: str, audio_format: AudioFormat) -> sf.SoundFile:
    """
    Open a 16-bit PCM WAV for streaming writes without the 4 GB RIFF limit (about 6 h at
    48 kHz/16-bit/stereo, after which plain WAV writes fail). The file is written as RF64
    and automatically downgraded to an ordinary WAV header on close when it is < 4 GB, so
    normal-length recordings stay compatible with every player.
    """
    f = sf.SoundFile(
        path,
        mode="w",
        samplerate=audio_format.sample_rate,
        channels=audio_format.channels,
        subtype="PCM_16",
        format="RF64",
    )
    try:
        sf._snd.sf_command(f._file, _SFC_RF64_AUTO_DOWNGRADE, sf._ffi.NULL, 1)
    except Exception as e:  # soundfile internals changed: still correct, just always RF64
        print(f"[AudioFileSink] Warning: RF64 auto-downgrade unavailable ({e}); writing RF64.")
    return f


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
        # Set when the last close() could not encode to the requested format and fell
        # back to WAV; close() then returns the .wav path that actually exists.
        self.last_conversion_error: Optional[str] = None

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
            self.last_conversion_error = None

            # Ensure destination directory exists
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

            # Native soundfile formats: WAV, FLAC, OGG
            if output_format == OutputFormat.WAV:
                self._sf_file = _open_wav_for_streaming(filepath, audio_format)
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
                self._sf_file = _open_wav_for_streaming(self._temp_wav_path, audio_format)

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

            expected_channels = self._audio_format.channels if self._audio_format else 2
            data = mix_to_channels(data, expected_channels)

            # Loopback float data can exceed ±1.0 (and the downmix adds energy); clip so
            # integer subtypes saturate instead of wrapping around.
            self._sf_file.write(np.clip(data, -1.0, 1.0))
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
                    final_path = self._convert_temp_wav_to_target(
                        self._temp_wav_path, self._filepath, self._target_format
                    )
                finally:
                    if os.path.exists(self._temp_wav_path):
                        try:
                            os.remove(self._temp_wav_path)
                        except Exception:
                            pass
                    self._temp_wav_path = None

            return final_path or ""

    def _convert_temp_wav_to_target(self, src_wav: str, dst_file: str, fmt: OutputFormat) -> str:
        """
        Convert temporary WAV file to compressed format using pydub.
        Returns the path actually written: `dst_file`, or a .wav fallback on failure.
        """
        temp_encoded_path = None
        try:
            from pydub import AudioSegment
            ffmpeg = find_ffmpeg()
            if ffmpeg is None:
                raise RuntimeError(
                    "ffmpeg が見つかりません。PATH に追加するか、プロジェクト直下に ffmpeg.exe を置いてください。"
                )
            AudioSegment.converter = ffmpeg
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
                return dst_file

            if os.path.exists(dst_file):
                os.remove(dst_file)
            shutil.move(temp_encoded_path, dst_file)
            temp_encoded_path = None
            return dst_file

        except Exception as e:
            print(f"[AudioFileSink] Warning: Compression conversion failed ({e}). Saving as WAV fallback.")
            if os.path.exists(dst_file):
                try:
                    os.remove(dst_file)
                except Exception:
                    pass
            fallback_path = os.path.splitext(dst_file)[0] + ".wav"
            shutil.copy2(src_wav, fallback_path)
            self.last_conversion_error = str(e)
            return fallback_path
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
