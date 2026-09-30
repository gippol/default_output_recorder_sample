"""
Central Recording Engine Orchestrator.
Coordinates Audio HAL Driver, Pipeline Filters, Ring Buffer, File Sinks, and State Machine.
"""

from datetime import datetime
import os
import threading
import time
from typing import List, Optional
from src.core.models import (
    AudioChunk,
    AudioFormat,
    Marker,
    OutputFormat,
    RecordingConfig,
    RecordingState,
)
from src.core.event_bus import EventBus, EventType
from src.core.ring_buffer import AudioRingBuffer
from src.core.pipeline import AudioPipeline, PeakMeterFilter, VADFilter, GainNormalizerFilter
from src.core.state_machine import RecordingStateMachine
from src.drivers.base import IAudioCaptureDriver, AudioDeviceInfo
from src.drivers.factory import get_audio_driver
from src.encoders.audio_file_sink import AudioFileSink


class RecordingEngine:
    """
    High-performance, event-driven audio recording controller.
    """

    def __init__(self, driver: Optional[IAudioCaptureDriver] = None):
        self.event_bus = EventBus()
        self.state_machine = RecordingStateMachine(RecordingState.IDLE)
        self.driver = driver or get_audio_driver()
        
        self.ring_buffer = AudioRingBuffer(capacity_seconds=30.0)
        self.file_sink = AudioFileSink()
        self.pipeline = AudioPipeline()

        self._active_config: Optional[RecordingConfig] = None
        self._markers: List[Marker] = []
        self._start_time: Optional[float] = None
        self._pause_start_time: Optional[float] = None
        self._total_paused_duration: float = 0.0
        self._lock = threading.RLock()
        self._current_filepath: Optional[str] = None

        # Build default pipeline
        self._rebuild_pipeline(RecordingConfig(output_dir="."))

    def _rebuild_pipeline(self, config: RecordingConfig) -> None:
        """Reconstruct the audio filter chain based on configuration."""
        self.pipeline.clear()

        # 1. Voice Activity Detection (if enabled)
        if config.enable_vad:
            self.pipeline.add_filter(VADFilter(threshold_db=config.vad_threshold_db, drop_silence=False))

        # 2. Auto Gain Normalization (if enabled)
        if config.auto_normalize:
            self.pipeline.add_filter(GainNormalizerFilter(target_peak_db=-1.0))

        # 3. Peak/RMS Meter (always active for UI telemetry)
        self.pipeline.add_filter(PeakMeterFilter(emit_event=True))

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        """List available output/loopback devices."""
        return self.driver.get_output_devices()

    def get_default_device(self) -> Optional[AudioDeviceInfo]:
        """Get default loopback device."""
        return self.driver.get_default_output_device()

    def start_buffering(self, device: Optional[AudioDeviceInfo] = None, time_shift_seconds: int = 30) -> None:
        """
        Start background audio capture into the RAM ring buffer (Time-Shift Mode).
        Does not write to disk yet.
        """
        with self._lock:
            if self.state_machine.is_recording():
                return

            self.ring_buffer.set_capacity(time_shift_seconds)
            self.ring_buffer.clear()

            if not self.driver.is_capturing():
                self.driver.start_capture(device=device, callback=self._on_audio_chunk)

            if self.state_machine.current_state == RecordingState.IDLE:
                self.state_machine.transition_to(RecordingState.BUFFERING)

    def start_recording(self, config: RecordingConfig, include_time_shift: bool = True) -> str:
        """
        Start active recording to disk.
        If include_time_shift is True, prepend buffered audio from RAM.
        """
        with self._lock:
            if self.state_machine.is_recording():
                return self._current_filepath or ""

            self._active_config = config
            self._rebuild_pipeline(config)
            self._markers.clear()
            self._start_time = time.time()
            self._total_paused_duration = 0.0

            # Generate output filename
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%H%M%S")
            filename = config.filename_template.format(date=date_str, time=time_str)
            ext = config.format.value if hasattr(config.format, "value") else str(config.format)
            filepath = os.path.join(config.output_dir, f"{filename}.{ext}")
            self._current_filepath = filepath

            audio_format = AudioFormat(
                sample_rate=config.sample_rate,
                channels=config.channels
            )

            # Open file sink
            fmt_enum = config.format if isinstance(config.format, OutputFormat) else OutputFormat(ext)
            self.file_sink.open(
                filepath=filepath,
                audio_format=audio_format,
                output_format=fmt_enum,
                bitrate_kbps=config.bitrate_kbps
            )

            # Write pre-recorded buffer if enabled
            if include_time_shift and not self.ring_buffer.is_empty:
                snapshot_chunks = self.ring_buffer.get_snapshot()
                for ch in snapshot_chunks:
                    self.file_sink.write_chunk(ch)

            # Ensure hardware capture is running
            if not self.driver.is_capturing():
                target_dev = None
                if config.device_id is not None:
                    devices = self.driver.get_output_devices()
                    target_dev = next((d for d in devices if str(d.id) == str(config.device_id)), None)
                self.driver.start_capture(device=target_dev, callback=self._on_audio_chunk, audio_format=audio_format)

            self.state_machine.transition_to(RecordingState.RECORDING)
            self.event_bus.publish(EventType.RECORDING_STARTED, {
                "filepath": filepath,
                "config": config,
                "start_time": self._start_time
            })

            return filepath

    def pause_recording(self) -> None:
        """Pause active recording."""
        with self._lock:
            if not self.state_machine.is_recording():
                return
            self._pause_start_time = time.time()
            self.state_machine.transition_to(RecordingState.PAUSED)
            self.event_bus.publish(EventType.RECORDING_PAUSED)

    def resume_recording(self) -> None:
        """Resume paused recording."""
        with self._lock:
            if not self.state_machine.is_paused():
                return
            if self._pause_start_time:
                self._total_paused_duration += (time.time() - self._pause_start_time)
                self._pause_start_time = None
            self.state_machine.transition_to(RecordingState.RECORDING)
            self.event_bus.publish(EventType.RECORDING_RESUMED)

    def stop_recording(self, keep_buffering: bool = True) -> Optional[str]:
        """
        Stop active recording and finalize audio file on disk.
        Returns the finalized file path.
        """
        with self._lock:
            if not (self.state_machine.is_recording() or self.state_machine.is_paused()):
                return None

            self.state_machine.transition_to(RecordingState.FINALIZING)

            final_filepath = self.file_sink.close()
            duration = self.current_recording_duration
            markers_copy = list(self._markers)

            if not keep_buffering:
                self.driver.stop_capture()
                self.state_machine.transition_to(RecordingState.IDLE)
            else:
                self.state_machine.transition_to(RecordingState.BUFFERING)

            self._start_time = None
            self._current_filepath = None

            self.event_bus.publish(EventType.RECORDING_STOPPED, final_filepath, duration, markers_copy)
            return final_filepath

    def add_marker(self, label: str = "Bookmark", note: str = "") -> Optional[Marker]:
        """Add a timestamp marker during recording."""
        with self._lock:
            if not self.state_machine.is_recording():
                return None

            offset = self.current_recording_duration
            marker = Marker(timestamp=offset, label=label, note=note)
            self._markers.append(marker)
            self.event_bus.publish(EventType.MARKER_ADDED, marker)
            return marker

    @property
    def current_recording_duration(self) -> float:
        """Elapsed recording time in seconds (excluding pauses)."""
        with self._lock:
            if not self._start_time:
                return 0.0
            now = time.time()
            if self.state_machine.is_paused() and self._pause_start_time:
                current_pause = now - self._pause_start_time
            else:
                current_pause = 0.0
            return max(0.0, now - self._start_time - self._total_paused_duration - current_pause)

    def _on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Audio capture callback from driver thread."""
        try:
            # 1. Pass chunk through filter pipeline (VAD, Normalizer, PeakMeter)
            processed_chunk = self.pipeline.process(chunk)
            if processed_chunk is None:
                return  # Dropped by VAD filter

            # 2. Always update time-shift ring buffer
            self.ring_buffer.push(processed_chunk)

            # 3. If currently recording to disk, stream chunk to file sink
            if self.state_machine.is_recording():
                self.file_sink.write_chunk(processed_chunk)

            self.event_bus.publish(EventType.CHUNK_PROCESSED, processed_chunk)

        except Exception as e:
            print(f"[RecordingEngine] Error in chunk processing: {e}")
            self.event_bus.publish(EventType.ERROR_OCCURRED, str(e), e)

    def shutdown(self) -> None:
        """Gracefully stop driver and close all files."""
        with self._lock:
            if self.state_machine.is_recording() or self.state_machine.is_paused():
                self.stop_recording(keep_buffering=False)
            self.driver.stop_capture()
            self.ring_buffer.clear()
            self.state_machine.transition_to(RecordingState.IDLE)
