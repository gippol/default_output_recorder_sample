"""
Diagnostic script to test Windows 11 WASAPI Loopback devices on the local machine.
"""

from src.drivers.factory import get_audio_driver


def main():
    driver = get_audio_driver()
    print(f"Driver type: {type(driver).__name__}")
    print("\n--- Available Output / Loopback Devices ---")
    devices = driver.get_output_devices()
    for d in devices:
        default_str = " *** DEFAULT ***" if d.is_default else ""
        print(f"[{d.id}] {d.name} ({d.host_api}) - Rate: {d.default_sample_rate}Hz, Ch: {d.max_channels}{default_str}")

    default_dev = driver.get_default_output_device()
    print(f"\nDefault Device: {default_dev}")


if __name__ == "__main__":
    main()
