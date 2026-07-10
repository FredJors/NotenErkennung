"""Smoke-Test der Pipeline auf dem synthetischen Testsong.

Aufruf (aus dem Projektordner):
    python tests/smoke_test.py            # ohne Demucs (schnell)
    python tests/smoke_test.py --demucs   # inkl. Instrumententrennung
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.make_testsong import DATA_DIR, EXPECTED_CHORDS, EXPECTED_MELODY, TEMPO

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'OK ' if ok else 'FEHLER'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    with_demucs = "--demucs" in sys.argv

    if not (DATA_DIR / "mix.wav").exists():
        from tests import make_testsong

        make_testsong.main()

    from noten import chords, melody, rhythm
    from noten.audio_io import load_audio

    sr = 22050
    melody_y, _ = load_audio(DATA_DIR / "melody.wav", sr=sr, mono=True)
    accomp_y, _ = load_audio(DATA_DIR / "accomp.wav", sr=sr, mono=True)
    mix_y, _ = load_audio(DATA_DIR / "mix.wav", sr=sr, mono=True)

    print("\n1. Beat-Erkennung")
    grid = rhythm.detect_beats(mix_y, sr)
    tempo_ok = abs(grid.tempo - TEMPO) < 5 or abs(grid.tempo - TEMPO / 2) < 3 or abs(grid.tempo - TEMPO * 2) < 6
    check("Tempo erkannt", tempo_ok, f"{grid.tempo:.1f} BPM (erwartet ~{TEMPO:.0f})")

    print("\n2. Melodie-Erkennung")
    notes = melody.extract_melody(melody_y, sr)
    pitches = [n.pitch for n in notes]
    matches = _sequence_overlap(pitches, EXPECTED_MELODY)
    ratio = matches / len(EXPECTED_MELODY)
    check(
        "Melodie-Noten stimmen",
        ratio >= 0.8,
        f"{matches}/{len(EXPECTED_MELODY)} Noten korrekt ({ratio:.0%}), erkannt: {len(pitches)}",
    )

    print("\n3. Tonart-Erkennung")
    from noten import keys

    song_key = keys.detect_key_from_audio(accomp_y, sr)
    check("Tonart korrekt", song_key.name == "C major", song_key.name)
    check(
        "Leitereigene Akkorde",
        (0, False) in song_key.allowed_chords() and (9, True) in song_key.allowed_chords(),
        "C-Dur und a-Moll enthalten",
    )

    print("\n4. Akkord-Erkennung (auf Tonart eingeschränkt)")
    labels = chords.detect_chords(accomp_y, sr, grid.beat_times, allowed=song_key.allowed_chords())
    segments = chords.to_segments(labels)
    detected = [s.label for s in segments if s.label != "N"]
    chord_matches = _sequence_overlap(detected, EXPECTED_CHORDS)
    check(
        "Akkordfolge stimmt",
        chord_matches >= len(EXPECTED_CHORDS) - 1,
        f"erkannt: {' '.join(detected)} (erwartet: {' '.join(EXPECTED_CHORDS)})",
    )

    print("\n5. Notensatz (music21)")
    from noten import arrange

    notes = melody.normalize_octave(notes)
    score, detected_key = arrange.build_score(notes, segments, grid, title="Smoke-Test")
    out = Path(__file__).parent / "output"
    paths = arrange.write_outputs(score, out, "smoketest")
    check("MusicXML geschrieben", paths["musicxml"].exists(), str(paths["musicxml"]))
    check("MIDI geschrieben", paths["midi"].exists(), str(paths["midi"]))
    check("Tonart plausibel", detected_key is not None and "C" in str(detected_key) or "a" in str(detected_key), str(detected_key))

    if with_demucs:
        print("\n6. Instrumententrennung (Demucs)")
        from noten import separate
        from noten.audio_io import load_audio as la

        y44, sr44 = la(DATA_DIR / "mix.wav")
        stems = separate.separate(y44, sr44, progress=False)
        check("4 Spuren erzeugt", set(stems.keys()) == {"drums", "bass", "other", "vocals"})
        lens = {len(v) for v in stems.values()}
        check("Spuren gleich lang", len(lens) == 1)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{'=' * 50}")
    if failed:
        print(f"{len(failed)} von {len(RESULTS)} Prüfungen fehlgeschlagen: {', '.join(failed)}")
        sys.exit(1)
    print(f"Alle {len(RESULTS)} Prüfungen bestanden.")


def _sequence_overlap(detected: list, expected: list) -> int:
    """Länge der längsten gemeinsamen Teilfolge (einfaches Ähnlichkeitsmaß)."""
    m, n = len(detected), len(expected)
    if m == 0 or n == 0:
        return 0
    dp = np.zeros((m + 1, n + 1), dtype=int)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if detected[i - 1] == expected[j - 1]:
                dp[i, j] = dp[i - 1, j - 1] + 1
            else:
                dp[i, j] = max(dp[i - 1, j], dp[i, j - 1])
    return int(dp[m, n])


if __name__ == "__main__":
    main()
