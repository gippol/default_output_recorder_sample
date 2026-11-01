"""
Windows 11 WASAPI Loopback Capture Driver using PyAudioWPatch.
Captures system audio / speaker output directly with zero external drivers.
"""

import threading
import time
from typing import Callable, List, Optional, Tuple
import numpy as np
from src.core.dsp import LinearResampler, mix_to_channels
from src.core.models import AudioChunk, AudioFormat
from src.drivers.base import AudioDeviceInfo, DeviceStatus, IAudioCaptureDriver

try:
    import pyaudiowpatch as pyaudio
    HAS_PYAUDIOWPATCH = True
except ImportError:
    try:
        import pyaudio
        HAS_PYAUDIOWPATCH = hasattr(pyaudio, "paWASAPI")
    except ImportError:
        HAS_PYAUDIOWPATCH = False


def _match_channels(data: np.ndarray, channels: int) -> np.ndarray:
    """Convert a block to `channels` channels (downmix to mono/stereo, else pad/truncate)."""
    if data.shape[1] == channels:
        return data
    if channels in (1, 2):
        return mix_to_channels(data, channels)
    out = np.zeros((len(data), channels), dtype=np.float32)
    n = min(channels, data.shape[1])
    out[:, :n] = data[:, :n]
    return out


class WasapiLoopbackDriver(IAudioCaptureDriver):
    """
    High-fidelity Windows 11 WASAPI Loopback Driver.
    Captures speaker/headphone output streams directly from Windows Audio Engine.

    Resilience:
    - Silence: WASAPI loopback delivers nothing while no app plays; the gap is padded
      with silence so recordings stay in real time.
    - Device loss (headphones unplugged, Bluetooth dropped): capture keeps padding
      silence, retries once per RECONNECT_INTERVAL_SECONDS, and resumes on the same
      device or, if it is gone, on the current default output. The output format stays
      the one capture started with (reconnected audio is resampled/remixed), so a
      recording in progress never changes format mid-file.
    """

    _LOOPBACK_SUFFIX = " [Loopback]"
    # How long the loopback stream may deliver nothing before the gap is filled with silence.
    SILENCE_GAP_SECONDS = 0.1
    # How often to try reopening a lost capture device.
    RECONNECT_INTERVAL_SECONDS = 1.0
    FRAMES_PER_BUFFER = 1024

    def __init__(self):
        self._pa: Optional["pyaudio.PyAudio"] = None
        # Guards self._pa: the capture thread replaces it on reconnect while the UI thread
        # may be enumerating devices.
        self._pa_lock = threading.RLock()
        self._stream = None
        self._is_capturing = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_format: Optional[AudioFormat] = None
        self._device: Optional[AudioDeviceInfo] = None

    # ------------------------------------------------------------------ PyAudio access

    def _create_pyaudio(self) -> "pyaudio.PyAudio":
        """Create a PyAudio instance. A fresh one re-enumerates devices (PortAudio caches
        the device list at initialisation, so reconnecting needs a new instance)."""
        return pyaudio.PyAudio()

    def _get_pyaudio(self) -> "pyaudio.PyAudio":
        if not HAS_PYAUDIOWPATCH:
            raise RuntimeError(
                "pyaudiowpatch is not installed. Please install via 'pip install pyaudiowpatch'."
            )
        with self._pa_lock:
            if self._pa is None:
                self._pa = self._create_pyaudio()
            return self._pa

    # ------------------------------------------------------------------ Device listing

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

    def _wasapi_devices(self, pa) -> Tuple[List[dict], List[dict], int]:
        """(loopback devices, plain output devices, default output index) for WASAPI."""
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        wasapi_index = wasapi_info["index"]
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
        return loopbacks, outputs, wasapi_info.get("defaultOutputDevice", -1)

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        with self._pa_lock:
            pa = self._get_pyaudio()
            try:
                loopbacks, outputs, default_output_idx = self._wasapi_devices(pa)
            except Exception:
                return []
            default_loopback_idx = self._default_loopback_index(pa)

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

    def _resolve_dev_info(self, pa, device: AudioDeviceInfo) -> Optional[dict]:
        """
        Find the loopback device dict for `device` in `pa`. The index is tried first, but
        the name decides: indices change whenever PortAudio is re-initialised (e.g. after a
        reconnect), so a stale index must not silently select a different device.
        """
        loopbacks, outputs, _ = self._wasapi_devices(pa)
        candidates = loopbacks or outputs
        by_index = next((d for d in candidates if str(d["index"]) == str(device.id)), None)
        if by_index is not None and self._display_name(by_index["name"]) == device.name:
            return by_index
        by_name = next((d for d in candidates if self._display_name(d["name"]) == device.name), None)
        if by_name is not None:
            return by_name
        # An output (non-loopback) entry was passed: use its loopback counterpart
        if by_index is not None and not by_index.get("isLoopbackDevice", False):
            expected = by_index["name"] + self._LOOPBACK_SUFFIX
            return next((d for d in loopbacks if d["name"] == expected), by_index)
        return None

    def _open_stream(self, pa, dev_info: dict):
        """
        Open a loopback stream. WASAPI loopback (shared mode) only works at the device's
        mix format, so the native rate/channels are always used.
        """
        sample_rate = int(dev_info.get("defaultSampleRate", 48000))
        channels = int(dev_info.get("maxInputChannels", 0)) or int(dev_info.get("maxOutputChannels", 0)) or 2
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=dev_info["index"],
            frames_per_buffer=self.FRAMES_PER_BUFFER,
        )
        return stream, AudioFormat(sample_rate=sample_rate, channels=channels)

    # ------------------------------------------------------------------ Capture

    def start_capture(
        self,
        device: Optional[AudioDeviceInfo],
        callback: Callable[[AudioChunk], None],
        audio_format: Optional[AudioFormat] = None
    ) -> None:
        """`audio_format` is ignored: loopback always runs at the device's native format,
        which is reported via `current_format` and stamped on every chunk."""
        if self._is_capturing:
            return

        with self._pa_lock:
            pa = self._get_pyaudio()
            target = device or self.get_default_output_device()
            if not target:
                raise RuntimeError("No suitable audio output device found for loopback capture.")
            dev_info = self._resolve_dev_info(pa, target)
            if dev_info is None:
                raise RuntimeError(f"Audio output device not found: {target.name}")
            try:
                stream, native_format = self._open_stream(pa, dev_info)
            except Exception as e:
                raise RuntimeError(f"Failed to open WASAPI Loopback stream: {e}") from e

        self._stream = stream
        self._device = self._to_device_info(dev_info, target.is_default)
        self._current_format = native_format
        self._stop_event.clear()
        self._is_capturing = True

        self._thread = threading.Thread(
            target=self._capture_worker,
            args=(callback,),
            daemon=True,
            name="WasapiLoopbackWorker"
        )
        self._thread.start()

    @staticmethod
    def _close_stream(stream) -> None:
        try:
            if stream.is_active():
                stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception as e:
            print(f"[WasapiDriver] Warning during stream close: {e}")

    def _reconnect(self):
        """
        Try to reopen capture after the device was lost: the same device if it is back,
        otherwise the current default output. Returns (stream, native_format, device) or
        None. Runs on the capture thread.
        """
        try:
            new_pa = self._create_pyaudio()
        except Exception as e:
            print(f"[WasapiDriver] Reconnect: could not initialise PyAudio: {e}")
            return None

        try:
            dev_info = self._resolve_dev_info(new_pa, self._device) if self._device else None
            default_idx = self._default_loopback_index(new_pa)
            if dev_info is None and default_idx is not None:
                dev_info = new_pa.get_device_info_by_index(default_idx)
            if dev_info is None:
                new_pa.terminate()
                return None
            stream, native_format = self._open_stream(new_pa, dev_info)
        except Exception as e:
            print(f"[WasapiDriver] Reconnect attempt failed: {e}")
            try:
                new_pa.terminate()
            except Exception:
                pass
            return None

        with self._pa_lock:
            old_pa, self._pa = self._pa, new_pa
        if old_pa is not None:
            try:
                old_pa.terminate()
            except Exception:
                pass

        device = self._to_device_info(dev_info, dev_info["index"] == default_idx)
        self._device = device
        self._stream = stream
        return stream, native_format, device

    def _capture_worker(self, callback: Callable[[AudioChunk], None]) -> None:
        # Output format is fixed for the whole capture session (the format of the device
        # capture started on); audio from a reconnected device is converted to it.
        out_format = self._current_format
        out_rate, out_channels = out_format.sample_rate, out_format.channels
        frames_per_buffer = self.FRAMES_PER_BUFFER
        silence = np.zeros((frames_per_buffer, out_channels), dtype=np.float32)

        stream = self._stream
        src_format = out_format
        resampler: Optional[LinearResampler] = None

        # Stream clock: count frames emitted versus frames wall-clock time says should
        # exist, and pad with silence once the stream has been starved for
        # SILENCE_GAP_SECONDS (or the device is gone). While data is flowing nothing is
        # inserted, so device/system clock drift can never inject dropouts into audio.
        stream_start = time.monotonic()
        last_data_time = stream_start
        frames_emitted = 0
        next_reconnect = 0.0

        def emit(data: np.ndarray, is_silent: bool = False) -> None:
            nonlocal frames_emitted
            frames_emitted += len(data)
            try:
                callback(AudioChunk(data=data, timestamp=time.time(), format=out_format, is_silent=is_silent))
            except Exception as e:
                print(f"[WasapiDriver] Error in capture callback: {e}")

        def pad_silence(now: float) -> None:
            frames_due = int((now - stream_start) * out_rate) - frames_emitted
            while frames_due >= frames_per_buffer and not self._stop_event.is_set():
                emit(silence.copy(), is_silent=True)
                frames_due -= frames_per_buffer

        while not self._stop_event.is_set():
            now = time.monotonic()

            # ---- Device lost: keep the timeline going and retry periodically
            if stream is None:
                pad_silence(now)
                if now >= next_reconnect:
                    next_reconnect = now + self.RECONNECT_INTERVAL_SECONDS
                    reopened = self._reconnect()
                    if reopened is not None:
                        stream, src_format, device = reopened
                        resampler = (
                            LinearResampler(src_format.sample_rate, out_rate)
                            if src_format.sample_rate != out_rate else None
                        )
                        last_data_time = time.monotonic()
                        print(f"[WasapiDriver] Capture restored on: {device}")
                        self._notify_status(DeviceStatus.RESTORED, device)
                time.sleep(0.02)
                continue

            # ---- Normal capture
            try:
                if not stream.is_active():
                    raise IOError("stream is no longer active")
                # Only read what is ready: a plain read() blocks forever during silence,
                # which made stop_capture() close the stream under a pending read (crash).
                if stream.get_read_available() < frames_per_buffer:
                    if now - last_data_time >= self.SILENCE_GAP_SECONDS:
                        pad_silence(now)
                    time.sleep(0.005)
                    continue
                raw_data = stream.read(frames_per_buffer, exception_on_overflow=False)
            except Exception as e:
                if self._stop_event.is_set():
                    break
                print(f"[WasapiDriver] Capture device lost: {e}")
                self._close_stream(stream)
                stream = None
                self._stream = None
                next_reconnect = now + self.RECONNECT_INTERVAL_SECONDS
                self._notify_status(DeviceStatus.LOST, self._device)
                continue

            if not raw_data:
                continue
            audio_np = np.frombuffer(raw_data, dtype=np.float32)
            if len(audio_np) % src_format.channels != 0:
                continue
            audio_np = _match_channels(audio_np.reshape(-1, src_format.channels), out_channels)
            if resampler is not None:
                audio_np = resampler.process(audio_np)
                if len(audio_np) == 0:
                    continue

            last_data_time = time.monotonic()
            emit(np.ascontiguousarray(audio_np, dtype=np.float32))

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
            self._close_stream(self._stream)
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
