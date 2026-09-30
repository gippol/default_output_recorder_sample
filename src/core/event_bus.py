"""
Thread-safe, decoupled Event Bus for real-time telemetry and state events.
Enables Clean Architecture by avoiding direct dependencies between UI and Core.
"""

from collections import defaultdict
from enum import Enum, auto
import threading
from typing import Callable, Any, Dict, List


class EventType(Enum):
    """Event types broadcasted across the application."""
    STATE_CHANGED = auto()       # (old_state: RecordingState, new_state: RecordingState)
    TELEMETRY_UPDATE = auto()    # (telemetry: AudioTelemetry)
    CHUNK_PROCESSED = auto()     # (chunk: AudioChunk)
    RECORDING_STARTED = auto()   # (session_info: dict)
    RECORDING_STOPPED = auto()   # (filepath: str, duration: float, markers: list)
    RECORDING_PAUSED = auto()    # ()
    RECORDING_RESUMED = auto()   # ()
    MARKER_ADDED = auto()        # (marker: Marker)
    ERROR_OCCURRED = auto()      # (error_message: str, exception: Optional[Exception])
    SUBTITLE_CHUNK = auto()      # (segment: SubtitleSegment)


class EventBus:
    """Thread-safe event bus for publishing and subscribing to application events."""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._subscribers: Dict[EventType, List[Callable[..., Any]]] = defaultdict(list)
                cls._instance._lock = threading.RLock()
            return cls._instance

    def subscribe(self, event_type: EventType, handler: Callable[..., Any]) -> None:
        """Register an event handler for a specific event type."""
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[..., Any]) -> None:
        """Remove a previously registered handler."""
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def publish(self, event_type: EventType, *args: Any, **kwargs: Any) -> None:
        """Publish an event to all registered listeners."""
        with self._lock:
            handlers = list(self._subscribers[event_type])

        for handler in handlers:
            try:
                handler(*args, **kwargs)
            except Exception as e:
                # Avoid crashing the publisher thread if a listener fails
                print(f"[EventBus Error] Error in handler {handler} for event {event_type}: {e}")

    def clear(self) -> None:
        """Remove all subscriptions (useful for unit tests)."""
        with self._lock:
            self._subscribers.clear()
