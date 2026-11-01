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

    _LOOPBACK_SUFFIX = " [Loopback]"

    def _display_name(self, raw_name: str) -> str:
        """
        PyAudioWPatch already returns correctly decoded Unicode names, so no re-decoding is
        done here (re-decoding as cp932 used to destroy Japanese names like "ヘッドホン").
        Only the redundant " [Loopback]" suffix is stripped, since host_api already says so.
        """
        if raw_name.endswith(self._LOOPBACK_SUFFIX):
            return raw_name[: -len(self._LOOPBACK_SUFFIX)]
        return raw_name

    def _to_device_info(self, dev: dict, is_default: bool) -> AudioDeviceInfo:
        return AudioDeviceInfo(
            id=dev["index"],
            name=self._display_name(dev["name"]),
            host_api="WASAPI Loopback",
            is_default=is_default,
            is_loopback=True,
            max_channels=max(int(dev.get("maxInputChannels", 0)), int(dev.get("maxOutputChannels", 0)), 1),
            default_sample_rate=int(dev.get("defaultSampleRate", 48000)),
        )

    def _default_loopback_index(self, pa) -> Optional[int]:
        """Index of the loopback device that mirrors the current default output, if any."""
        if hasattr(pa, "get_default_wasapi_loopback"):
            try:
                default_loopback = pa.get_default_wasapi_loopback()
                if default_loopback:
                    return int(default_loopback["index"])
            except Exception as e:
                print(f"[WasapiDriver] Warning: Could not query default WASAPI loopback: {e}")
        return None

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        pa = self._get_pyaudio()

        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:
            return []

        wasapi_index = wasapi_info["index"]
        default_output_idx = wasapi_info.get("defaultOutputDevice", -1)
        default_loopback_idx = self._default_loopback_index(pa)

        loopbacks: List[dict] = []
        outputs: List[dict] = []
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev["hostApi"] != wasapi_index:
                continue
            if dev.get("isLoopbackDevice", False):
                loopbacks.append(dev)
            elif dev.get("maxOutputChannels", 0) > 0:
                outputs.append(dev)

        # PyAudioWPatch exposes one loopback device per output device. Listing only those
        # avoids every speaker appearing twice. Plain PyAudio has no loopback devices, so
        # fall back to the output devices there.
        if loopbacks:
            return [self._to_device_info(d, d["index"] == default_loopback_idx) for d in loopbacks]
        return [self._to_device_info(d, d["index"] == default_output_idx) for d in outputs]

    def get_default_output_device(self) -> Optional[AudioDeviceInfo]:
        devices = self.get_output_devices()
        default = next((d for d in devices if d.is_default), None)
        return default or (devices[0] if devices else None)

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
            expected_name = dev_info["name"] + self._LOOPBACK_SUFFIX
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice", False) and d["name"] == expected_name:
                    dev_info = d
                    break

        # WASAPI loopback (shared mode) only works at the device's mix format, so the stream
        # is always opened at the native rate/channels. `audio_format` cannot change that;
        # the real format is reported via `current_format` and stamped on every chunk.
        sample_rate = int(dev_info.get("defaultSampleRate", 48000))
        channels = int(dev_info.get("maxInputChannels", 0)) or int(dev_info.get("maxOutputChannels", 0)) or 2

        self._current_format = AudioFormat(sample_rate=sample_rate, channels=channels)
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
        stream = self._stream
        audio_format = self._current_format
        while not self._stop_event.is_set():
            try:
                if not stream or not stream.is_active():
                    time.sleep(0.01)
                    continue

                # WASAPI loopback delivers no packets while nothing is playing, so a plain
                # read() can block forever. That made stop_capture() time out and close the
                # stream under a pending read -> access violation. Only read what is ready.
                if stream.get_read_available() < frames_per_buffer:
                    time.sleep(0.005)
                    continue

                raw_data = stream.read(frames_per_buffer, exception_on_overflow=False)
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
                    format=audio_format
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

        if self._thread and self._thread.is_alive():
            # Never close a stream the worker may still be reading: that crashes the process.
            # Leaking one stream handle is the lesser evil.
            print("[WasapiDriver] Warning: capture worker did not stop; leaving stream open.")
            self._stream = None
        elif self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                print(f"[WasapiDriver] Warning during stream close: {e}")
            finally:
                self._stream = None

        self._is_capturing = False
        self._current_format = None

    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def current_format(self) -> Optional[AudioFormat]:
        return self._current_format if self._is_capturing else None

    def __del__(self):
        self.stop_capture()
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
