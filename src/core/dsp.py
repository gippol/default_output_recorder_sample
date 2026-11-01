"""
Small, dependency-free DSP helpers shared by drivers and sinks.
"""

from typing import Optional
import numpy as np


_MINUS_3DB = 0.7071


def output_channels_for(source_channels: int) -> int:
    """Files are written as mono (for mono sources) or stereo (everything else)."""
    return 1 if source_channels == 1 else 2


def mix_to_channels(data: np.ndarray, target_channels: int) -> np.ndarray:
    """
    Convert a (frames, n) block to (frames, target_channels).

    Multichannel sources are downmixed to stereo instead of truncated, so the centre
    channel (where film/game dialogue lives) is not lost. Channel order follows the
    Windows WAVE_FORMAT_EXTENSIBLE default layout:
      3: FL FR FC | 4: FL FR BL BR | 5: FL FR FC BL BR | 6 (5.1): FL FR FC LFE BL BR
      8 (7.1): FL FR FC LFE BL BR SL SR
    Centre and surrounds are mixed in at -3 dB; LFE is dropped.
    """
    if data.ndim == 1:
        data = data[:, np.newaxis]
    n = data.shape[1]
    if n == target_channels:
        return data
    if target_channels == 1:
        return data.mean(axis=1, keepdims=True)
    if n == 1:
        return np.repeat(data, target_channels, axis=1)
    if target_channels != 2:
        raise ValueError(f"Unsupported target channel count: {target_channels}")

    left = data[:, 0].astype(np.float32, copy=True)
    right = data[:, 1].astype(np.float32, copy=True)
    if n == 4:
        surround = [2, 3]
    else:
        left += _MINUS_3DB * data[:, 2]
        right += _MINUS_3DB * data[:, 2]
        surround = list(range(4 if n >= 6 else 3, n))  # skip LFE at index 3
    for k, ch in enumerate(surround):
        if k % 2 == 0:
            left += _MINUS_3DB * data[:, ch]
        else:
            right += _MINUS_3DB * data[:, ch]
    return np.column_stack([left, right])


class LinearResampler:
    """
    Streaming linear-interpolation resampler for (frames, channels) float blocks.

    Keeps the fractional read position and the last input frame between calls, so a
    stream processed block by block has no discontinuity (and no clicks) at block
    boundaries, unlike resampling each block independently. Linear interpolation has
    no anti-alias filter; that is acceptable for the rare case it is used (a device
    reconnecting at a different rate) and inaudible for 44.1 <-> 48 kHz.
    """

    def __init__(self, src_rate: int, dst_rate: int):
        self.src_rate, self.dst_rate = int(src_rate), int(dst_rate)
        self._step = self.src_rate / self.dst_rate  # input frames per output frame
        self._pos = 0.0                              # read position, relative to buffer start
        self._prev: Optional[np.ndarray] = None      # last input frame of the previous block

    def process(self, block: np.ndarray) -> np.ndarray:
        if self.src_rate == self.dst_rate or len(block) == 0:
            return block
        buf = block if self._prev is None else np.concatenate([self._prev, block], axis=0)
        positions = np.arange(self._pos, len(buf) - 1, self._step)
        if len(positions):
            idx = positions.astype(np.int64)
            frac = (positions - idx)[:, np.newaxis].astype(np.float32)
            out = buf[idx] * (1.0 - frac) + buf[idx + 1] * frac
            next_pos = positions[-1] + self._step
        else:
            out = np.empty((0, buf.shape[1]), dtype=np.float32)
            next_pos = self._pos
        # The next buffer starts with this buffer's last frame (index len(buf) - 1).
        self._pos = next_pos - (len(buf) - 1)
        self._prev = buf[-1:]
        return out.astype(np.float32, copy=False)
