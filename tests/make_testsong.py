"""Erzeugt einen synthetischen Testsong mit bekannter Melodie und Akkordfolge.

8 Takte 4/4 bei 100 BPM, Akkorde: | C | G | Am | F | x2
Ausgabe: tests/data/{melody,accomp,mix}.wav
"""

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
TEMPO = 100.0
BEAT = 60.0 / TEMPO   # 0.6 s
BAR = 4 * BEAT

# Akkorde als (Grundton-MIDI, Moll?)
PROGRESSION = [(48, False), (55, False), (57, True), (53, False)] * 2  # C G Am F x2

# Melodie: 4 Viertelnoten pro Takt (MIDI-Nummern)
MELODY_BARS = [
    [64, 67, 72, 67],  # über C
    [74, 71, 67, 71],  # über G
    [72, 69, 76, 72],  # über Am
    [69, 65, 72, 69],  # über F
] * 2

EXPECTED_MELODY = [p for bar in MELODY_BARS for p in bar]
EXPECTED_CHORDS = ["C", "G", "Am", "F", "C", "G", "Am", "F"]

DATA_DIR = Path(__file__).parent / "data"


def midi_to_hz(m):
    return 440.0 * 2 ** ((np.asarray(m, dtype=float) - 69) / 12)


def tone(freq, duration, amp=0.5, harmonics=(1.0, 0.4, 0.2)):
    """Ton mit Obertönen und ADSR-artiger Hüllkurve."""
    t = np.arange(int(duration * SR)) / SR
    y = np.zeros_like(t)
    for i, h in enumerate(harmonics, start=1):
        y += h * np.sin(2 * np.pi * freq * i * t)
    n = len(t)
    env = np.ones(n)
    attack = min(int(0.01 * SR), n)
    release = min(int(0.05 * SR), n)
    env[:attack] = np.linspace(0, 1, attack)
    env[n - release :] = np.linspace(1, 0, release)
    return amp * y * env / max(sum(harmonics), 1e-9)


def render_melody():
    total = int(len(MELODY_BARS) * BAR * SR)
    y = np.zeros(total)
    for i, pitch in enumerate(EXPECTED_MELODY):
        start = int(i * BEAT * SR)
        seg = tone(midi_to_hz(pitch), BEAT * 0.95, amp=0.5)
        y[start : start + len(seg)] += seg
    return y


def render_chords():
    total = int(len(PROGRESSION) * BAR * SR)
    y = np.zeros(total)
    for i, (root, minor) in enumerate(PROGRESSION):
        start = int(i * BAR * SR)
        third = root + (3 if minor else 4)
        for p in (root, third, root + 7):
            seg = tone(midi_to_hz(p), BAR * 0.98, amp=0.25, harmonics=(1.0, 0.3))
            y[start : start + len(seg)] += seg
    return y


def render_drums():
    total = int(len(PROGRESSION) * BAR * SR)
    y = np.zeros(total)
    rng = np.random.default_rng(0)
    n_beats = int(len(PROGRESSION) * 4)
    for b in range(n_beats):
        start = int(b * BEAT * SR)
        length = int(0.03 * SR)
        burst = rng.standard_normal(length) * np.linspace(1, 0, length)
        amp = 0.30 if b % 4 == 0 else 0.15
        y[start : start + length] += amp * burst
    return y


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    melody = render_melody()
    accomp = render_chords()
    drums = render_drums()

    n = max(len(melody), len(accomp), len(drums))
    melody = np.pad(melody, (0, n - len(melody)))
    accomp = np.pad(accomp, (0, n - len(accomp)))
    drums = np.pad(drums, (0, n - len(drums)))

    mix = melody + accomp + drums
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.9

    sf.write(DATA_DIR / "melody.wav", melody, SR)
    sf.write(DATA_DIR / "accomp.wav", accomp, SR)
    sf.write(DATA_DIR / "mix.wav", np.stack([mix, mix], axis=1), SR)
    print(f"Testdaten geschrieben nach {DATA_DIR}")


if __name__ == "__main__":
    main()
