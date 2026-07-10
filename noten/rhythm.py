"""Tempo- und Beat-Erkennung sowie Quantisierung auf ein Achtel-Raster."""

from dataclasses import dataclass

import numpy as np


@dataclass
class BeatGrid:
    """Beat-Raster eines Songs. Beats gelten als Viertelnoten (4/4 angenommen)."""

    tempo: float          # BPM
    beat_times: np.ndarray  # Zeitpunkte der Viertel (Sekunden)
    grid_times: np.ndarray  # Achtel-Raster (Sekunden), doppelt so fein

    def time_to_quarter(self, t: float, subdiv: int = 2) -> float:
        """Rechnet eine Zeit (s) in quantisierte Viertel-Offsets um.

        subdiv: Unterteilungen pro Beat (2 = Achtel, 4 = Sechzehntel).
        """
        beat_pos = float(np.interp(t, self.beat_times, np.arange(len(self.beat_times))))
        return round(beat_pos * subdiv) / subdiv

    @property
    def total_quarters(self) -> float:
        return (len(self.grid_times) - 1) * 0.5


def detect_beats(y: np.ndarray, sr: int, duration: float | None = None) -> BeatGrid:
    """Erkennt Tempo und Beats und baut daraus ein Achtel-Raster.

    Args:
        y: Mono-Audio des Gesamtmixes (Schlagzeug hilft der Beat-Erkennung).
        duration: Gesamtlänge in Sekunden; Raster wird bis dahin verlängert.
    """
    import librosa

    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.atleast_1d(tempo)[0])

    # Doppelt erkanntes Tempo (typisch bei Halftime-Grooves, z. B. Trap):
    # über ~140 BPM ist fast immer das gefühlte Tempo die Hälfte.
    if tempo > 140 and len(beat_times) >= 3:
        beat_times = beat_times[::2]
        tempo /= 2

    if duration is None:
        duration = len(y) / sr

    if len(beat_times) < 2:
        # Fallback: starres Raster mit erkanntem oder Standard-Tempo
        if tempo <= 0:
            tempo = 120.0
        beat_times = np.arange(0, duration, 60.0 / tempo)

    beat_times = _extend_beats(np.asarray(beat_times, dtype=float), duration)

    # Achtel-Raster: Mittelpunkte zwischen den Beats einfügen
    mids = (beat_times[:-1] + beat_times[1:]) / 2
    grid = np.sort(np.concatenate([beat_times, mids]))

    return BeatGrid(tempo=tempo, beat_times=beat_times, grid_times=grid)


def _extend_beats(beat_times: np.ndarray, duration: float) -> np.ndarray:
    """Verlängert die Beat-Folge mit dem Median-Abstand bis zum Anfang und Ende."""
    step = float(np.median(np.diff(beat_times)))

    before = []
    t = beat_times[0] - step
    while t > 0:
        before.append(t)
        t -= step
    after = []
    t = beat_times[-1] + step
    while t < duration:
        after.append(t)
        t += step

    return np.concatenate([np.array(before[::-1]), beat_times, np.array(after)])
