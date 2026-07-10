"""Audio laden und speichern (MP3, WAV, FLAC, ...)."""

from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio(path: str | Path, sr: int | None = None, mono: bool = False):
    """Lädt eine Audiodatei.

    Returns:
        (y, sr): y hat Form (samples,) bei mono=True, sonst (channels, samples).
    """
    data, file_sr = sf.read(str(path), always_2d=True, dtype="float32")
    y = data.T  # (channels, samples)

    if mono and y.shape[0] > 1:
        y = y.mean(axis=0, keepdims=True)

    if sr is not None and sr != file_sr:
        import librosa

        y = librosa.resample(y, orig_sr=file_sr, target_sr=sr)
        file_sr = sr

    if mono:
        y = y[0]
    return y, file_sr


def save_audio(path: str | Path, y: np.ndarray, sr: int):
    """Speichert Audio als WAV. y: (samples,) oder (channels, samples)."""
    if y.ndim == 2:
        y = y.T  # soundfile erwartet (samples, channels)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y, sr)
