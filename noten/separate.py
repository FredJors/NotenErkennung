"""Instrumententrennung mit Demucs.

htdemucs_6s zerlegt einen Song in: drums, bass, other, vocals, guitar, piano.
"""

import numpy as np

STEM_NAMES = ("drums", "bass", "other", "vocals", "guitar", "piano")


def separate(y: np.ndarray, sr: int, device: str = "cpu", progress: bool = True) -> dict[str, np.ndarray]:
    """Trennt einen Song in Einzelspuren.

    Args:
        y: Audio als (channels, samples) oder (samples,), beliebige Samplerate.
        sr: Samplerate von y.

    Returns:
        Dict mit den Spuren aus STEM_NAMES;
        jede Spur mono als (samples,) bei der Original-Samplerate des Modells (44100).
    """
    import torch
    import torchaudio
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model("htdemucs_6s")
    model.eval()

    wav = torch.tensor(np.atleast_2d(y), dtype=torch.float32)
    if sr != model.samplerate:
        wav = torchaudio.functional.resample(wav, sr, model.samplerate)
    # Modell erwartet Stereo
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    elif wav.shape[0] > 2:
        wav = wav[:2]

    # Normalisierung wie in demucs.separate
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav_norm = (wav - mean) / std

    with torch.no_grad():
        sources = apply_model(
            model, wav_norm[None], device=device, progress=progress, split=True
        )[0]
    sources = sources * std + mean

    stems = {}
    for name, source in zip(model.sources, sources):
        stems[name] = source.mean(dim=0).cpu().numpy()  # mono
    return stems


def accompaniment(stems: dict[str, np.ndarray]) -> np.ndarray:
    """Harmonische Begleitung (alles außer Schlagzeug und Gesang) für die Akkord-Erkennung."""
    parts = [stems[n] for n in ("bass", "other", "guitar", "piano") if n in stems]
    return np.sum(parts, axis=0)
