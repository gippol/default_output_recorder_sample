"""
Windows 11 WASAPI Loopback Capture Driver using PyAudioWPatch.
Captures system audio / speaker output directly with zero external drivers.
"""

import threading
import time
from typing import Callable, List, Optional
import numpy as np
from src.core.models import AudioChunk, AudioFormat
from src.drivers.base import IAudioCaptureDriver, AudioDeviceInfo

try:
    import pyaudiowpatch as pyaudio
    HAS_PYAUDIOWPATCH = True
except ImportError:
    try:
        import pyaudio
        HAS_PYAUDIOWPATCH = hasattr(pyaudio, "paWASAPI")
    except ImportError:
        HAS_PYAUDIOWPATCH = False


class WasapiLoopbackDriver(IAudioCaptureDriver):
    """
    High-fidelity Windows 11 WASAPI Loopback Driver.
    Captures speaker/headphone output streams directly from Windows Audio Engine.
    """

    def __init__(self):
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream = None
        self._is_capturing = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_format: Optional[AudioFormat] = None

    def _get_pyaudio(self) -> pyaudio.PyAudio:
        if not HAS_PYAUDIOWPATCH:
            raise RuntimeError(
                "pyaudiowpatch is not installed. Please install via 'pip install pyaudiowpatch'."
            )
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        return self._pa

    def _clean_name(self, raw_name: str) -> str:
        """Fix Shift-JIS / CP932 encoding artifacts from PortAudio on Windows."""
        try:
            # If string was incorrectly decoded as utf-8 or latin-1
            encoded = raw_name.encode("utf-8", errors="ignore")
            # Try decoding cp932
            return encoded.decode("cp932")
        except Exception:
            try:
                return raw_name.encode("latin-1", errors="ignore").decode("cp932")
            except Exception:
                return raw_name

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        pa = self._get_pyaudio()
        devices: List[AudioDeviceInfo] = []

        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:
            return devices

        wasapi_index = wasapi_info["index"]
        default_output_idx = wasapi_info.get("defaultOutputDevice", -1)

        # Iterate all devices on the system
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev["hostApi"] != wasapi_index:
                continue

            # In PyAudioWPatch, loopback devices are marked with isLoopbackDevice = True
            is_loopback = dev.get("isLoopbackDevice", False)
            # Or standard output devices that can be loopback-captured
            is_output = dev.get("maxOutputChannels", 0) > 0

            if is_loopback or is_output:
                is_default = (i == default_output_idx)
                device_info = AudioDeviceInfo(
                    id=i,
                    name=self._clean_name(dev["name"]),
                    host_api="WASAPI Loopback",
                    is_default=is_default,
                    is_loopback=True,
                    max_channels=max(dev.get("maxInputChannels", 0), dev.get("maxOutputChannels", 0), 2),
                    default_sample_rate=int(dev.get("defaultSampleRate", 48000))
                )
                devices.append(device_info)

        return devices

    def get_default_output_device(self) -> Optional[AudioDeviceInfo]:
        pa = self._get_pyaudio()
        try:
            # Try PyAudioWPatch dedicated helper first
            if hasattr(pa, "get_default_wasapi_loopback"):
                default_loopback = pa.get_default_wasapi_loopback()
                if default_loopback:
                    return AudioDeviceInfo(
                        id=default_loopback["index"],
                        name=self._clean_name(default_loopback["name"]),
                        host_api="WASAPI Loopback",
                        is_default=True,
                        is_loopback=True,
                        max_channels=max(default_loopback.get("maxInputChannels", 2), 2),
                        default_sample_rate=int(default_loopback.get("defaultSampleRate", 48000))
                    )

            # Fallback to standard WASAPI default output
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out_idx = wasapi_info.get("defaultOutputDevice", -1)
            if default_out_idx >= 0:
                dev = pa.get_device_info_by_index(default_out_idx)
                return AudioDeviceInfo(
                    id=default_out_idx,
                    name=self._clean_name(dev["name"]),
                    host_api="WASAPI Loopback",
                    is_default=True,
                    is_loopback=True,
                    max_channels=max(dev.get("maxOutputChannels", 2), 2),
                    default_sample_rate=int(dev.get("defaultSampleRate", 48000))
                )
        except Exception as e:
            print(f"[WasapiDriver] Warning: Could not find default WASAPI loopback: {e}")

        # Fallback to first available device
        devices = self.get_output_devices()
        return devices[0] if devices else None

    def start_capture(
        self,
        device: Optional[AudioDeviceInfo],
        callback: Callable[[AudioChunk], None],
        audio_format: Optional[AudioFormat] = None
    ) -> None:
        if self._is_capturing:
            return

        pa = self._get_pyaudio()
        target_device = device or self.get_default_output_device()
        if not target_device:
            raise RuntimeError("No suitable audio output device found for loopback capture.")

        # Ensure we have the actual loopback device info from PyAudioWPatch
        dev_info = pa.get_device_info_by_index(int(target_device.id))
        
        # If the device is not marked as loopback, find its loopback counterpart
        if not dev_info.get("isLoopbackDevice", False):
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False) and dev_info["name"] in d["name"]:
                    dev_info = d
                    break

        sample_rate = int(dev_info.get("defaultSampleRate", 48000))
        channels = int(dev_info.get("maxInputChannels", 2))
        if channels == 0:
            channels = int(dev_info.get("maxOutputChannels", 2))
        channels = max(channels, 2)  # Typically stereo

        format_spec = audio_format or AudioFormat(sample_rate=sample_rate, channels=channels)
        self._current_format = format_spec
        self._stop_event.clear()
        self._is_capturing = True

        frames_per_buffer = 1024

        try:
            self._stream = pa.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=sample_rate,
                input=True,
                input_device_index=dev_info["index"],
                frames_per_buffer=frames_per_buffer
            )
        except Exception as e:
            self._is_capturing = False
            raise RuntimeError(f"Failed to open WASAPI Loopback stream: {e}") from e

        self._thread = threading.Thread(
            target=self._capture_worker,
            args=(callback, frames_per_buffer, channels, sample_rate),
            daemon=True,
            name="WasapiLoopbackWorker"
        )
        self._thread.start()

    def _capture_worker(
        self,
        callback: Callable[[AudioChunk], None],
        frames_per_buffer: int,
        channels: int,
        sample_rate: int
    ) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._stream or not self._stream.is_active():
                    time.sleep(0.01)
                    continue

                # Read raw bytes from WASAPI stream (non-blocking overflow handling)
                raw_data = self._stream.read(frames_per_buffer, exception_on_overflow=False)
                if not raw_data:
                    continue

                # Convert bytes to numpy float32 [-1.0, 1.0]
                audio_np = np.frombuffer(raw_data, dtype=np.float32)
                # Reshape to (frames, channels)
                if len(audio_np) % channels == 0:
                    audio_np = audio_np.reshape(-1, channels)
                else:
                    continue

                chunk = AudioChunk(
                    data=audio_np,
                    timestamp=time.time(),
                    format=self._current_format or AudioFormat(sample_rate=sample_rate, channels=channels)
                )

                callback(chunk)

            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"[WasapiDriver] Stream read error: {e}")
                    time.sleep(0.01)

    def stop_capture(self) -> None:
        if not self._is_capturing:
            return

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                print(f"[WasapiDriver] Warning during stream close: {e}")
            finally:
                self._stream = None

        self._is_capturing = False

    def is_capturing(self) -> bool:
        return self._is_capturing

    def __del__(self):
        self.stop_capture()
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
