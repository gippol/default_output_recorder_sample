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
from src.core.pipeline import AudioPipeline, PeakMeterFilter, VADFilter, GainNormalizerFilter, SilenceSkipFilter
from src.core.state_machine import RecordingStateMachine
from src.drivers.base import IAudioCaptureDriver, AudioDeviceInfo, DeviceStatus
from src.drivers.factory import get_audio_driver
from src.encoders.audio_file_sink import AudioFileSink, output_channels_for
from src.encoders.marker_writer import export_cue


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
        # Sample rate of the file being written; positions are derived from frames written
        self._file_sample_rate: Optional[int] = None
        self._lock = threading.RLock()
        # Serialises "push to ring buffer + write to file" (audio thread) against
        # "write pre-roll + switch to RECORDING" (start_recording), so no chunk is lost or
        # duplicated at the seam. Kept separate from _lock: switch_device() joins the
        # capture thread while holding _lock, so the audio thread must never wait on it.
        self._write_lock = threading.Lock()
        self._current_filepath: Optional[str] = None
        # Device the driver is currently capturing from (resolved, never None while capturing)
        self._capture_device: Optional[AudioDeviceInfo] = None

        # Device lost / restored notifications from the capture thread
        self.driver.status_callback = self._on_driver_status

        # Build default pipeline
        self._rebuild_pipeline(RecordingConfig(output_dir="."))

    def _on_driver_status(self, status: str, device: Optional[AudioDeviceInfo]) -> None:
        """Called on the capture thread. Must not take self._lock: switch_device() holds it
        while joining that thread, so waiting here could deadlock."""
        if status == DeviceStatus.RESTORED and device is not None:
            self._capture_device = device  # may be a different device (new default)
        self.event_bus.publish(EventType.DEVICE_STATUS, status, device)

    def _rebuild_pipeline(self, config: RecordingConfig) -> None:
        """Reconstruct the audio filter chain based on configuration."""
        self.pipeline.clear()

        # 1. Voice Activity Detection (if enabled): only marks chunks as silent
        if config.enable_vad:
            self.pipeline.add_filter(VADFilter(threshold_db=config.vad_threshold_db))

        # 2. Auto Gain Normalization (if enabled)
        if config.auto_normalize:
            self.pipeline.add_filter(GainNormalizerFilter(target_peak_db=-1.0))

        # 3. Peak/RMS Meter (always active for UI telemetry). Runs before silence is
        #    dropped, so the meter keeps falling to silence instead of freezing.
        self.pipeline.add_filter(PeakMeterFilter(emit_event=True))

        # 4. Silence skip (if VAD enabled): leave long silences out of the file
        if config.enable_vad:
            self.pipeline.add_filter(SilenceSkipFilter(hangover_seconds=config.vad_hangover_seconds))

    def get_output_devices(self) -> List[AudioDeviceInfo]:
        """List available output/loopback devices."""
        return self.driver.get_output_devices()

    def get_default_device(self) -> Optional[AudioDeviceInfo]:
        """Get default loopback device."""
        return self.driver.get_default_output_device()

    @property
    def capture_device(self) -> Optional[AudioDeviceInfo]:
        """The device currently being captured, or None when the driver is stopped."""
        with self._lock:
            return self._capture_device if self.driver.is_capturing() else None

    @staticmethod
    def _same_device(a: Optional[AudioDeviceInfo], b: Optional[AudioDeviceInfo]) -> bool:
        if a is None or b is None:
            return a is b
        return str(a.id) == str(b.id)

    def _find_device(self, device_id: Optional[str]) -> Optional[AudioDeviceInfo]:
        if device_id is None:
            return None
        return next((d for d in self.driver.get_output_devices() if str(d.id) == str(device_id)), None)

    def _ensure_capturing(self, device: Optional[AudioDeviceInfo]) -> None:
        """
        Make sure the driver captures from `device` (None = system default).
        If it is capturing from a different device, the stream is reopened and the
        time-shift buffer is cleared, since its audio came from the old device.
        """
        target = device or self.driver.get_default_output_device()
        if self.driver.is_capturing():
            if target is None or self._same_device(target, self._capture_device):
                return
            self.driver.stop_capture()
            self.ring_buffer.clear()

        self.driver.start_capture(device=target, callback=self._on_audio_chunk)
        self._capture_device = target

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

            self._ensure_capturing(device)

            if self.state_machine.current_state == RecordingState.IDLE:
                self.state_machine.transition_to(RecordingState.BUFFERING)

    def switch_device(self, device: Optional[AudioDeviceInfo]) -> None:
        """
        Switch the capture device while idle/buffering. Not allowed during recording,
        because a single file cannot change source format mid-stream.
        """
        with self._lock:
            if self.state_machine.is_recording() or self.state_machine.is_paused():
                raise RuntimeError("Cannot switch audio device while recording.")
            if self.driver.is_capturing():
                self._ensure_capturing(device)

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

            # Generate output filename
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%H%M%S")
            filename = config.filename_template.format(date=date_str, time=time_str)
            ext = config.format.value if hasattr(config.format, "value") else str(config.format)
            filepath = self._unique_filepath(config.output_dir, filename, ext)
            self._current_filepath = filepath

            # 1. Make sure we capture from the requested device *before* opening the file,
            #    so the file can be created with the device's real format.
            #    device_id None = keep the current device (or the system default).
            requested = self._find_device(config.device_id) or self.capture_device
            self._ensure_capturing(requested)

            # 2. The file must use the format the device actually delivers; writing 44.1kHz
            #    samples into a 48kHz header would change pitch and speed.
            source_format = self.driver.current_format or AudioFormat(
                sample_rate=config.sample_rate, channels=config.channels
            )
            audio_format = AudioFormat(
                sample_rate=source_format.sample_rate,
                channels=output_channels_for(source_format.channels),
            )

            fmt_enum = config.format if isinstance(config.format, OutputFormat) else OutputFormat(ext)
            self.file_sink.open(
                filepath=filepath,
                audio_format=audio_format,
                output_format=fmt_enum,
                bitrate_kbps=config.bitrate_kbps
            )

            self._file_sample_rate = audio_format.sample_rate

            # 3. Write pre-recorded buffer if enabled (skip anything at a different rate),
            #    then go live atomically w.r.t. the audio thread.
            with self._write_lock:
                if include_time_shift and not self.ring_buffer.is_empty:
                    for ch in self.ring_buffer.get_snapshot():
                        if ch.format.sample_rate == audio_format.sample_rate:
                            self.file_sink.write_chunk(ch)

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
            self.state_machine.transition_to(RecordingState.PAUSED)
            self.event_bus.publish(EventType.RECORDING_PAUSED)

    def resume_recording(self) -> None:
        """Resume paused recording."""
        with self._lock:
            if not self.state_machine.is_paused():
                return
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

            duration = self.current_recording_duration
            final_filepath = self.file_sink.close()
            if self.file_sink.last_conversion_error:
                self.event_bus.publish(
                    EventType.ERROR_OCCURRED,
                    "圧縮形式への変換に失敗したため、WAV で保存しました:\n"
                    f"{final_filepath}\n\n原因: {self.file_sink.last_conversion_error}",
                    None,
                )
            markers_copy = list(self._markers)
            self._save_markers(final_filepath, markers_copy)

            if not keep_buffering:
                self.driver.stop_capture()
                self.state_machine.transition_to(RecordingState.IDLE)
            else:
                self.state_machine.transition_to(RecordingState.BUFFERING)

            self._start_time = None
            self._file_sample_rate = None
            self._current_filepath = None

            self.event_bus.publish(EventType.RECORDING_STOPPED, final_filepath, duration, markers_copy)
            return final_filepath

    @staticmethod
    def _unique_filepath(output_dir: str, stem: str, ext: str) -> str:
        """
        Return `<stem>.<ext>`, or `<stem>_2.<ext>`, `<stem>_3.<ext>`, ... so an existing
        recording is never overwritten (e.g. two recordings started in the same second).
        Sibling files this recording may create are checked too: the .wav written if
        compression fails, and the .cue marker sheet.
        """
        def taken(candidate_stem: str) -> bool:
            base = os.path.join(output_dir, candidate_stem)
            return any(os.path.exists(f"{base}.{e}") for e in {ext, "wav", "cue"})

        candidate, n = stem, 1
        while taken(candidate):
            n += 1
            candidate = f"{stem}_{n}"
        return os.path.join(output_dir, f"{candidate}.{ext}")

    def _save_markers(self, audio_path: str, markers: List[Marker]) -> Optional[str]:
        """Write markers as a CUE sheet next to the recording. Never fails the stop."""
        if not markers or not audio_path:
            return None
        if self._active_config is not None and not self._active_config.save_markers:
            return None
        try:
            return export_cue(markers, audio_path)
        except Exception as e:
            print(f"[RecordingEngine] Could not save markers: {e}")
            self.event_bus.publish(EventType.ERROR_OCCURRED, f"マーカーの保存に失敗しました: {e}", e)
            return None

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
        """
        Current position in the output file, in seconds.

        Derived from frames actually written rather than wall-clock time, so it includes
        the time-shift pre-roll at the start of the file and excludes paused periods.
        Marker timestamps use this, so they line up with the audio in the saved file.
        """
        with self._lock:
            if not self._file_sample_rate:
                return 0.0
            return self.file_sink.total_frames / self._file_sample_rate

    def _on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Audio capture callback from driver thread."""
        try:
            # 1. Pass chunk through filter pipeline (VAD, Normalizer, PeakMeter)
            processed_chunk = self.pipeline.process(chunk)
            if processed_chunk is None:
                return  # Long silence left out by SilenceSkipFilter

            # 2. Update the time-shift ring buffer and, if recording, the file — as one
            #    step, so start_recording's pre-roll snapshot sees each chunk exactly once.
            with self._write_lock:
                self.ring_buffer.push(processed_chunk)
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
