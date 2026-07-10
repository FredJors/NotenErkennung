"""Melodie-Extraktion aus der (monophonen) Gesangsspur mit pYIN.

Ablauf: pYIN-Tonhöhenverlauf -> stimmhafte Abschnitte -> Segmente bilden
(Trennung erst bei anhaltender Tonhöhen-Abweichung, nicht bei Vibrato) ->
Tonhöhe pro Segment als Median -> Oktavfehler korrigieren -> leise
Geisternoten entfernen.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class MelodyNote:
    start: float  # Sekunden
    end: float    # Sekunden
    pitch: int    # MIDI-Nummer

    @property
    def duration(self) -> float:
        return self.end - self.start


def extract_melody(
    y: np.ndarray,
    sr: int,
    fmin_note: str = "C2",
    fmax_note: str = "C6",
    min_note_duration: float = 0.07,
    hop_length: int = 512,
    split_threshold: float = 0.9,   # Halbtöne Abweichung vom Segment-Median
    min_relative_level: float = 0.10,  # Lautstärke-Schwelle gegen Geisternoten
) -> list[MelodyNote]:
    """Extrahiert die Melodie als Notenliste aus einer Mono-Gesangsspur."""
    import librosa
    from scipy.signal import medfilt

    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz(fmin_note),
        fmax=librosa.note_to_hz(fmax_note),
        sr=sr,
        hop_length=hop_length,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)
    frame_dur = hop_length / sr

    semis = np.full(len(f0), np.nan)
    voiced = np.asarray(voiced_flag) & ~np.isnan(f0)
    semis[voiced] = librosa.hz_to_midi(f0[voiced])

    # Jitter glätten, Vibrato-Wackeln um Halbtongrenzen unterdrücken
    filled = np.where(np.isnan(semis), 0.0, semis)
    smooth = medfilt(filled, kernel_size=5)
    semis = np.where(voiced, np.where(smooth > 0, smooth, semis), np.nan)

    # Lautstärkeverlauf für den Geisternoten-Filter
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    level_threshold = float(np.percentile(rms[rms > 0], 90)) * min_relative_level if np.any(rms > 0) else 0.0

    segments = _segment(times, semis, voiced, rms, frame_dur, split_threshold)

    notes = []
    for seg_times, seg_semis, seg_level in segments:
        duration = seg_times[-1] - seg_times[0] + frame_dur
        if duration < min_note_duration:
            continue
        if seg_level < level_threshold:
            continue  # zu leise: Hall-Reste, Hintergrundgesang
        pitch = int(round(float(np.median(seg_semis))))
        notes.append(MelodyNote(start=float(seg_times[0]), end=float(seg_times[0]) + duration, pitch=pitch))

    notes = _fix_octave_errors(notes)
    notes = _merge_repeated(notes, max_gap=0.12)
    return notes


def _segment(times, semis, voiced, rms, frame_dur, split_threshold):
    """Zerlegt den Tonhöhenverlauf in Segmente konstanter Tonhöhe.

    Ein neues Segment beginnt bei Stimmlosigkeit oder wenn die Tonhöhe
    dauerhaft (>= 2 Frames) vom bisherigen Segment-Median abweicht --
    kurzes Vibrato-Zittern trennt also nicht.
    """
    segments = []
    cur_t, cur_s = [], []
    deviating = 0

    def close():
        nonlocal cur_t, cur_s, deviating
        if cur_t:
            idx_a = int(times.searchsorted(cur_t[0]))
            idx_b = int(times.searchsorted(cur_t[-1])) + 1
            level = float(np.mean(rms[min(idx_a, len(rms) - 1):max(idx_b, idx_a + 1)])) if len(rms) else 0.0
            segments.append((np.array(cur_t), np.array(cur_s), level))
        cur_t, cur_s, deviating = [], [], 0

    for t, s, v in zip(times, semis, voiced):
        if not v or np.isnan(s):
            close()
            continue
        if not cur_t:
            cur_t, cur_s = [t], [s]
            continue
        if abs(s - float(np.median(cur_s))) > split_threshold:
            deviating += 1
            if deviating >= 2:
                # Abweichung hält an -> die letzten Frames gehören zur neuen Note
                moved_t, moved_s = cur_t[-(deviating - 1):], cur_s[-(deviating - 1):]
                del cur_t[-(deviating - 1):], cur_s[-(deviating - 1):]
                close()
                cur_t, cur_s = moved_t + [t], moved_s + [s]
                continue
        else:
            deviating = 0
        cur_t.append(t)
        cur_s.append(s)
    close()
    return segments


def _fix_octave_errors(notes: list[MelodyNote]) -> list[MelodyNote]:
    """Faltet einzelne Oktav-Ausreißer zu ihren Nachbarn zurück.

    Springt eine Note >= 11 Halbtöne von beiden Nachbarn weg, während die
    Nachbarn nah beieinander liegen, ist es fast immer ein Tracker-Fehler.
    """
    fixed = list(notes)
    for i in range(1, len(fixed) - 1):
        prev_p, cur_p, next_p = fixed[i - 1].pitch, fixed[i].pitch, fixed[i + 1].pitch
        if abs(prev_p - next_p) <= 5:
            neighborhood = (prev_p + next_p) / 2
            offset = cur_p - neighborhood
            if abs(offset) >= 11:
                shift = int(round(offset / 12)) * 12
                fixed[i] = MelodyNote(fixed[i].start, fixed[i].end, cur_p - shift)
    return fixed


def _merge_repeated(notes: list[MelodyNote], max_gap: float) -> list[MelodyNote]:
    """Verschmilzt direkt aufeinanderfolgende gleiche Töne mit winziger Lücke."""
    merged: list[MelodyNote] = []
    for n in notes:
        if merged and merged[-1].pitch == n.pitch and n.start - merged[-1].end <= max_gap:
            merged[-1] = MelodyNote(start=merged[-1].start, end=n.end, pitch=n.pitch)
        else:
            merged.append(MelodyNote(n.start, n.end, n.pitch))
    return merged


def normalize_octave(notes: list[MelodyNote], target_low: int = 60, target_high: int = 84) -> list[MelodyNote]:
    """Verschiebt die gesamte Melodie oktavweise in eine klaviertaugliche Lage.

    Der Median der Tonhöhen soll im Bereich [target_low, target_high] liegen
    (relative Oktavlagen innerhalb der Melodie bleiben erhalten).
    """
    if not notes:
        return notes
    median = float(np.median([n.pitch for n in notes]))
    shift = 0
    while median + shift < target_low + 2:
        shift += 12
    while median + shift > target_high - 2:
        shift -= 12
    if shift == 0:
        return notes
    return [MelodyNote(n.start, n.end, n.pitch + shift) for n in notes]
