"""Polyphone Klavier-Transkription mit dem ByteDance-Modell.

Erwartet eine isolierte Klavierspur (aus der Instrumententrennung) und
liefert einzelne Notenereignisse mit Anschlagstärke.
"""

from pathlib import Path

import numpy as np


def transcribe_piano(
    y: np.ndarray,
    sr: int,
    midi_out: str | Path | None = None,
    device: str = "cpu",
    min_duration: float = 0.05,
    min_velocity: int = 12,
) -> list[tuple[float, float, int, int]]:
    """Transkribiert eine Klavierspur zu Notenereignissen.

    Args:
        y: Mono-Audio der Klavierspur.
        midi_out: optionaler Pfad für das rohe (unquantisierte) MIDI.

    Returns:
        Liste von (start_s, ende_s, midi, velocity), nach Startzeit sortiert.
    """
    import librosa
    from piano_transcription_inference import PianoTranscription, sample_rate

    if sr != sample_rate:
        y = librosa.resample(y, orig_sr=sr, target_sr=sample_rate)
    y = y.astype(np.float32)

    transcriptor = PianoTranscription(device=device)
    result = transcriptor.transcribe(y, str(midi_out) if midi_out else None)

    events = []
    for e in result["est_note_events"]:
        start, end = float(e["onset_time"]), float(e["offset_time"])
        velocity = int(e["velocity"])
        if end - start < min_duration or velocity < min_velocity:
            continue
        events.append((start, end, int(e["midi_note"]), velocity))
    events.sort(key=lambda e: e[0])
    return events


def piano_energy_share(stems: dict[str, np.ndarray]) -> float:
    """Energieanteil der Klavierspur am Gesamtmix (für die Modus-Wahl)."""
    piano = stems.get("piano")
    if piano is None:
        return 0.0
    total = np.sum([np.mean(s**2) for s in stems.values()])
    if total <= 0:
        return 0.0
    return float(np.mean(piano**2) / total)
