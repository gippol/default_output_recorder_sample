"""
Core domain models and entity definitions for the Audio Recording Engine.
Completely decoupled from UI and external framework implementations.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
import time
from typing import Optional, List
import numpy as np


class RecordingState(Enum):
    """Lifecycle states of the recording engine."""
    IDLE = auto()          # Engine is idle, no stream active
    BUFFERING = auto()     # Time-shift buffer is active (capturing in RAM only)
    RECORDING = auto()     # Active recording to storage
    PAUSED = auto()        # Stream active, but recording paused
    FINALIZING = auto()    # Writing file headers, closing streams, encoding
    ERROR = auto()         # Unrecoverable capture/storage error


class OutputFormat(str, Enum):
    """Supported output audio formats."""
    WAV = "wav"
    MP3 = "mp3"
    AAC = "m4a"
    FLAC = "flac"
    OGG = "ogg"
    OPUS = "opus"


@dataclass(frozen=True)
class AudioFormat:
    """Audio stream format specifications."""
    sample_rate: int = 48000
    channels: int = 2
    sample_width: int = 2  # 2 bytes = 16-bit PCM, 4 bytes = 32-bit float
    dtype: np.dtype = np.float32

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.sample_width

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.bytes_per_frame


@dataclass
class AudioChunk:
    """A discrete block of PCM audio data captured from the stream."""
    data: np.ndarray        # Shape: (frames, channels), float32 normalized [-1.0, 1.0]
    timestamp: float        # Capture timestamp (seconds since epoch)
    format: AudioFormat
    is_silent: bool = False

    @property
    def num_frames(self) -> int:
        return len(self.data)

    @property
    def duration(self) -> float:
        return self.num_frames / self.format.sample_rate if self.format.sample_rate > 0 else 0.0

    def to_int16(self) -> np.ndarray:
        """Convert float32 [-1.0, 1.0] to int16 PCM."""
        clamped = np.clip(self.data, -1.0, 1.0)
        return (clamped * 32767.0).astype(np.int16)


@dataclass
class AudioTelemetry:
    """Real-time audio signal metrics for UI visualizers."""
    peak_db: float          # Peak volume in dB (-60.0 to 0.0)
    rms_db: float           # Root Mean Square volume in dB
    channel_peaks: List[float] # Peak per channel (e.g. [Left, Right])
    is_clipping: bool       # True if peak >= 0.0 dB
    is_speaking: bool       # True if VAD detected voice activity


@dataclass
class Marker:
    """A timestamped bookmark added during recording."""
    timestamp: float        # Offset in seconds from recording start
    label: str
    created_at: float = field(default_factory=time.time)
    note: str = ""


@dataclass
class SubtitleSegment:
    """A transcribed/translated segment with timestamps."""
    start_seconds: float
    end_seconds: float
    text: str
    translated_text: Optional[str] = None
    speaker: Optional[str] = None
    confidence: float = 1.0


@dataclass
class RecordingConfig:
    """Configuration for a recording session."""
    output_dir: str
    filename_template: str = "Recording_{date}_{time}"
    format: OutputFormat = OutputFormat.WAV
    bitrate_kbps: int = 320         # For compressed formats (MP3/AAC/Opus)
    sample_rate: int = 48000
    channels: int = 2
    enable_time_shift: bool = True  # Pre-recording buffer
    time_shift_seconds: int = 30    # Seconds of pre-buffer to keep
    enable_vad: bool = False        # Auto skip silence
    vad_threshold_db: float = -45.0 # Silence threshold in dB
    auto_normalize: bool = False    # Peak/Loudness normalization
    device_id: Optional[str] = None # None = Default Output Device
