"""Akkord-Erkennung aus der Begleitspur über Chroma-Vektoren und Template-Matching."""

from dataclasses import dataclass

import numpy as np

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

NO_CHORD = "N"


@dataclass
class ChordSegment:
    start_quarter: float  # Offset in Vierteln
    end_quarter: float
    label: str            # z. B. "C", "Am", "N" (kein Akkord)
    root: int             # Pitch-Class 0-11, -1 bei "N"
    minor: bool


def _templates(allowed: set[tuple[int, bool]] | None = None) -> tuple[np.ndarray, list[tuple[int, bool]]]:
    """Dur/Moll-Dreiklang-Templates (Chroma-Raum).

    allowed: optionale Einschränkung auf (Grundton, Moll?)-Paare, z. B. die
    leitereigenen Akkorde der erkannten Tonart. None = alle 24.
    """
    maj = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=float)
    min_ = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float)
    templates = []
    meta = []
    for minor, base in ((False, maj), (True, min_)):
        for root in range(12):
            if allowed is not None and (root, minor) not in allowed:
                continue
            templates.append(np.roll(base, root))
            meta.append((root, minor))
    t = np.array(templates)
    t = t / np.linalg.norm(t, axis=1, keepdims=True)
    return t, meta


def detect_chords(
    y: np.ndarray,
    sr: int,
    beat_times: np.ndarray,
    hop_length: int = 512,
    min_energy: float = 0.02,
    allowed: set[tuple[int, bool]] | None = None,
) -> list[str]:
    """Erkennt pro Beat-Intervall einen Akkord.

    Args:
        y: Mono-Audio der Begleitung (idealerweise ohne Schlagzeug).
        beat_times: Beat-Zeitpunkte (Viertel) in Sekunden.
        allowed: nur diese Akkorde zulassen (typisch: leitereigene der Tonart).

    Returns:
        Liste der Akkord-Labels, ein Eintrag pro Beat-Intervall
        (len == len(beat_times), letztes Intervall reicht bis zum Songende).
    """
    import librosa

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]

    boundaries = librosa.time_to_frames(beat_times, sr=sr, hop_length=hop_length)
    boundaries = np.clip(boundaries, 0, chroma.shape[1] - 1)

    templates, meta = _templates(allowed)

    labels: list[str] = []
    n_frames = chroma.shape[1]
    for i in range(len(boundaries)):
        a = boundaries[i]
        b = boundaries[i + 1] if i + 1 < len(boundaries) else n_frames
        if b <= a:
            b = a + 1
        seg = np.median(chroma[:, a:b], axis=1)
        energy = float(np.median(rms[a:min(b, len(rms))])) if a < len(rms) else 0.0

        norm = np.linalg.norm(seg)
        if norm < 1e-6 or energy < min_energy:
            labels.append(NO_CHORD)
            continue
        scores = templates @ (seg / norm)
        best = int(np.argmax(scores))
        root, minor = meta[best]
        labels.append(PITCH_NAMES[root] + ("m" if minor else ""))

    return _smooth(labels)


def _smooth(labels: list[str], width: int = 3) -> list[str]:
    """Entfernt Einzel-Ausreißer: Mehrheitsentscheid im gleitenden Fenster."""
    if len(labels) < width:
        return labels
    out = list(labels)
    half = width // 2
    for i in range(half, len(labels) - half):
        window = labels[i - half : i + half + 1]
        counts = {l: window.count(l) for l in set(window)}
        best = max(counts, key=counts.get)
        if counts[best] > width // 2:
            out[i] = best
    return out


def pc_lookup(segments: list[ChordSegment]):
    """Liefert eine Funktion Viertel-Offset -> Pitch-Classes des Akkords dort."""

    def lookup(q: float) -> set[int] | None:
        for seg in segments:
            if seg.start_quarter <= q < seg.end_quarter:
                if seg.label == NO_CHORD:
                    return None
                third = seg.root + (3 if seg.minor else 4)
                return {seg.root % 12, third % 12, (seg.root + 7) % 12}
        return None

    return lookup


def to_segments(labels: list[str], quarters_per_chord: float = 2.0) -> list[ChordSegment]:
    """Fasst Beat-Labels zu Akkord-Segmenten auf Halbtakt-Raster zusammen.

    Pro Halbtakt (2 Beats) wird der häufigste Akkord gewählt; gleiche
    aufeinanderfolgende Segmente werden verschmolzen.
    """
    group = int(quarters_per_chord)
    segments: list[ChordSegment] = []

    for i in range(0, len(labels), group):
        window = [l for l in labels[i : i + group]]
        candidates = [l for l in window if l != NO_CHORD] or window
        label = max(set(candidates), key=candidates.count)
        start_q = float(i)
        end_q = float(min(i + group, len(labels)))

        if segments and segments[-1].label == label:
            segments[-1].end_quarter = end_q
            continue

        if label == NO_CHORD:
            segments.append(ChordSegment(start_q, end_q, NO_CHORD, -1, False))
        else:
            minor = label.endswith("m")
            root = PITCH_NAMES.index(label[:-1] if minor else label)
            segments.append(ChordSegment(start_q, end_q, label, root, minor))

    return segments
