"""
Mock Audio Capture Driver for Unit Testing and CI/CD environments.
Generates synthetic sine waves or silence without requiring real audio hardware.
"""

import threading
import time
from typing import Callable, List, Optional
import numpy as np
from src.core.models import AudioChunk, AudioFormat
from src.drivers.base import IAudioCaptureDriver, AudioDeviceInfo


class MockAudioDriver(IAudioCaptureDriver):
    """Generates continuous test audio stream in a background thread."""

    def __init__(self, frequency: float = 440.0, amplitude: float = 0.5):
        self.frequency = frequency
        self.amplitude = amplitude
        self._is_capturing = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._format = AudioFormat(sample_rate=48000, channels=2)

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        return [
            AudioDeviceInfo(
                id="mock_speakers",
                name="Mock System Speakers (Virtual)",
                host_api="MockAPI",
                is_default=True,
                is_loopback=True,
                max_channels=2,
                default_sample_rate=48000
            ),
            AudioDeviceInfo(
                id="mock_headphones",
                name="Mock Headphones (Virtual)",
                host_api="MockAPI",
                is_default=False,
                is_loopback=True,
                max_channels=2,
                default_sample_rate=48000
            )
        ]

    def get_default_output_device(self) -> Optional[AudioDeviceInfo]:
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

        self._format = audio_format or self._format
        self._is_capturing = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(callback,),
            daemon=True,
            name="MockAudioCaptureThread"
        )
        self._thread.start()

    def _capture_loop(self, callback: Callable[[AudioChunk], None]) -> None:
        sample_rate = self._format.sample_rate
        chunk_size = 1024  # ~21.3ms per chunk at 48kHz
        sleep_duration = chunk_size / sample_rate
        phase = 0.0

        while not self._stop_event.is_set():
            start_time = time.time()

            # Generate sine wave for each channel
            t = (np.arange(chunk_size) + phase) / sample_rate
            sine_wave = self.amplitude * np.sin(2.0 * np.pi * self.frequency * t)
            
            # Stereo: shape (chunk_size, 2)
            stereo_data = np.column_stack([sine_wave, sine_wave]).astype(np.float32)
            phase = (phase + chunk_size) % sample_rate

            chunk = AudioChunk(
                data=stereo_data,
                timestamp=time.time(),
                format=self._format
            )

            try:
                callback(chunk)
            except Exception as e:
                print(f"[MockAudioDriver] Error in capture callback: {e}")

            elapsed = time.time() - start_time
            remaining = sleep_duration - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def stop_capture(self) -> None:
        if not self._is_capturing:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._is_capturing = False

    def is_capturing(self) -> bool:
        return self._is_capturing
