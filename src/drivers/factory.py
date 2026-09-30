"""
Audio Capture Driver Factory.
Selects and initializes the appropriate driver based on OS and availability.
"""

import sys
from typing import Optional
from src.drivers.base import IAudioCaptureDriver
from src.drivers.mock_driver import MockAudioDriver


def get_audio_driver(force_mock: bool = False) -> IAudioCaptureDriver:
    """
    Factory method to instantiate the optimal audio loopback capture driver.
    
    - On Windows: WasapiLoopbackDriver (PyAudioWPatch)
    - On macOS: ScreenCaptureKitDriver (or Mock fallback)
    - On test / fallback: MockAudioDriver
    """
    if force_mock:
        return MockAudioDriver()

    if sys.platform.startswith("win"):
        try:
            from src.drivers.wasapi_driver import WasapiLoopbackDriver, HAS_PYAUDIOWPATCH
            if HAS_PYAUDIOWPATCH:
                return WasapiLoopbackDriver()
        except Exception as e:
            print(f"[DriverFactory] Could not initialize WASAPI Driver: {e}")

    # Fallback to Mock driver if platform driver is unavailable
    print("[DriverFactory] Falling back to MockAudioDriver.")
    return MockAudioDriver()
