"""
Audio Hardware Abstraction Layer (HAL) base interfaces.
Enables seamless multi-platform support (Windows WASAPI, macOS ScreenCaptureKit, Mock).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional
from src.core.models import AudioChunk, AudioFormat


@dataclass
class AudioDeviceInfo:
    """Represents a system audio output/loopback device."""
    id: int | str
    name: str
    host_api: str
    is_default: bool = False
    is_loopback: bool = True
    max_channels: int = 2
    default_sample_rate: int = 48000

    def __str__(self) -> str:
        default_tag = " (Default)" if self.is_default else ""
        return f"{self.name} [{self.host_api}]{default_tag}"


class IAudioCaptureDriver(ABC):
    """Abstract interface for OS-level audio loopback capture drivers."""

    @abstractmethod
    def get_output_devices(self) -> List[AudioDeviceInfo]:
        """List all available system output devices that support loopback capture."""
        pass

    @abstractmethod
    def get_default_output_device(self) -> Optional[AudioDeviceInfo]:
        """Get the current default system output loopback device."""
        pass

    @abstractmethod
    def start_capture(
        self,
        device: Optional[AudioDeviceInfo],
        callback: Callable[[AudioChunk], None],
        audio_format: Optional[AudioFormat] = None
    ) -> None:
        """
        Start capturing audio loopback from the specified device.
        Calls `callback(chunk)` on every audio frame block.
        """
        pass

    @abstractmethod
    def stop_capture(self) -> None:
        """Stop capturing and release hardware/API resources."""
        pass

    @abstractmethod
    def is_capturing(self) -> bool:
        """Returns True if the driver is actively capturing audio."""
        pass
