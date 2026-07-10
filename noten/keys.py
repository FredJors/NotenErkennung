"""Tonart-Bestimmung (Krumhansl-Schmuckler) und leitereigene Akkorde.

Grundidee: Erst die allgemeinen Tatsachen des Stücks feststellen (Dur/Moll,
Grundton), dann darf die Akkorderkennung nur noch aus den typischen,
leitereigenen Akkorden dieser Tonart wählen.
"""

from dataclasses import dataclass

import numpy as np

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler-Tonprofile (empirisch ermittelte Tonhäufigkeiten)
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Leitereigene Dreiklänge als (Stufe, Moll?) relativ zum Grundton
_MAJOR_DEGREES = [(0, False), (2, True), (4, True), (5, False), (7, False), (9, True)]
# Moll: natürlich + harmonisch (v und V beide erlaubt)
_MINOR_DEGREES = [(0, True), (3, False), (5, True), (7, True), (7, False), (8, False), (10, False)]

_MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
_MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10, 11]  # natürlich + Leitton


# Gebräuchliche Schreibweise je Grundton (statt theoretischer Tonarten wie
# A#-Dur mit 10 Kreuzen die enharmonische Alternative, hier B♭-Dur mit 2 B).
_MAJOR_SPELLING = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_MINOR_SPELLING = ["c", "c#", "d", "eb", "e", "f", "f#", "g", "g#", "a", "bb", "b"]


@dataclass
class Key:
    tonic: int    # Pitch-Class 0-11
    minor: bool
    confidence: float  # Korrelationsabstand zur zweitbesten Tonart

    @property
    def name(self) -> str:
        if self.minor:
            return _MINOR_SPELLING[self.tonic].capitalize() + " minor"
        return _MAJOR_SPELLING[self.tonic] + " major"

    @property
    def music21_name(self) -> str:
        """Tonart im music21-Format (Moll = Kleinbuchstabe, b = '-')."""
        spelling = _MINOR_SPELLING[self.tonic] if self.minor else _MAJOR_SPELLING[self.tonic]
        return spelling[0] + spelling[1:].replace("b", "-")

    def allowed_chords(self) -> set[tuple[int, bool]]:
        """Leitereigene Dreiklänge als (Grundton-Pitch-Class, Moll?)."""
        degrees = _MINOR_DEGREES if self.minor else _MAJOR_DEGREES
        return {((self.tonic + step) % 12, minor) for step, minor in degrees}

    def scale_pcs(self) -> set[int]:
        scale = _MINOR_SCALE if self.minor else _MAJOR_SCALE
        return {(self.tonic + s) % 12 for s in scale}


def detect_key(chroma_mean: np.ndarray) -> Key:
    """Bestimmt die Tonart aus einem gemittelten Chroma-Vektor (12 Werte)."""
    chroma = np.asarray(chroma_mean, dtype=float)
    if chroma.sum() <= 0:
        return Key(tonic=0, minor=False, confidence=0.0)

    scores = []
    for minor, profile in ((False, _MAJOR_PROFILE), (True, _MINOR_PROFILE)):
        for tonic in range(12):
            rolled = np.roll(profile, tonic)
            r = np.corrcoef(chroma, rolled)[0, 1]
            scores.append((r, tonic, minor))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    return Key(tonic=best[1], minor=best[2], confidence=float(best[0] - second[0]))


def detect_key_from_audio(y: np.ndarray, sr: int) -> Key:
    """Bestimmt die Tonart direkt aus Audio (harmonische Begleitspur)."""
    import librosa

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    return detect_key(np.median(chroma, axis=1))
