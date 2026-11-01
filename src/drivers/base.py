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


class DeviceStatus:
    """Values passed to IAudioCaptureDriver.status_callback."""
    LOST = "lost"          # capture device disappeared/failed; driver pads with silence
    RESTORED = "restored"  # capture resumed (same device, or the new default device)


class IAudioCaptureDriver(ABC):
    """Abstract interface for OS-level audio loopback capture drivers."""

    # Optional hook: status_callback(status: DeviceStatus.*, device: Optional[AudioDeviceInfo]).
    # Called from the capture thread when the device is lost or capture is restored.
    status_callback: Optional[Callable[[str, Optional[AudioDeviceInfo]], None]] = None

    def _notify_status(self, status: str, device: Optional[AudioDeviceInfo] = None) -> None:
        callback = self.status_callback
        if callback is None:
            return
        try:
            callback(status, device)
        except Exception as e:
            print(f"[{type(self).__name__}] Error in status callback: {e}")

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

    @property
    def current_format(self) -> Optional[AudioFormat]:
        """
        The actual format of the chunks being delivered (device-native rate/channels),
        or None if not capturing. Sinks must use this, not a requested format.
        """
        return None
