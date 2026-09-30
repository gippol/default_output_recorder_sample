"""
Recording State Machine.
Enforces strict, predictable state transitions across the application.
"""

import threading
from typing import Set, Dict
from src.core.models import RecordingState
from src.core.event_bus import EventBus, EventType


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class RecordingStateMachine:
    """
    Manages the lifecycle of recording sessions with atomic transitions.
    """

    # Valid state transition graph
    _VALID_TRANSITIONS: Dict[RecordingState, Set[RecordingState]] = {
        RecordingState.IDLE: {RecordingState.BUFFERING, RecordingState.RECORDING, RecordingState.ERROR},
        RecordingState.BUFFERING: {RecordingState.RECORDING, RecordingState.IDLE, RecordingState.ERROR},
        RecordingState.RECORDING: {RecordingState.PAUSED, RecordingState.FINALIZING, RecordingState.ERROR},
        RecordingState.PAUSED: {RecordingState.RECORDING, RecordingState.FINALIZING, RecordingState.ERROR},
        RecordingState.FINALIZING: {RecordingState.IDLE, RecordingState.BUFFERING, RecordingState.ERROR},
        RecordingState.ERROR: {RecordingState.IDLE},
    }

    def __init__(self, initial_state: RecordingState = RecordingState.IDLE):
        self._current_state = initial_state
        self._lock = threading.Lock()
        self._event_bus = EventBus()

    @property
    def current_state(self) -> RecordingState:
        with self._lock:
            return self._current_state

    def transition_to(self, new_state: RecordingState) -> None:
        """
        Atomically transition to a new state if valid.
        Publishes STATE_CHANGED event.
        """
        with self._lock:
            if new_state == self._current_state:
                return

            valid_targets = self._VALID_TRANSITIONS.get(self._current_state, set())
            if new_state not in valid_targets:
                raise InvalidStateTransitionError(
                    f"Cannot transition from {self._current_state.name} to {new_state.name}. "
                    f"Valid transitions are: {[s.name for s in valid_targets]}"
                )

            old_state = self._current_state
            self._current_state = new_state

        # Publish event outside of internal lock to avoid deadlocks
        self._event_bus.publish(EventType.STATE_CHANGED, old_state, new_state)

    def is_recording(self) -> bool:
        with self._lock:
            return self._current_state == RecordingState.RECORDING

    def is_buffering(self) -> bool:
        with self._lock:
            return self._current_state == RecordingState.BUFFERING

    def is_paused(self) -> bool:
        with self._lock:
            return self._current_state == RecordingState.PAUSED

    def is_active(self) -> bool:
        """True if recording or buffering."""
        with self._lock:
            return self._current_state in (RecordingState.RECORDING, RecordingState.PAUSED, RecordingState.BUFFERING)
