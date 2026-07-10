"""Gesamtablauf: MP3 -> Spuren -> Melodie + Akkorde -> Klaviersatz."""

import json
import time
from pathlib import Path

import numpy as np

from . import arrange, chords, keys, melody, piano, rhythm, separate
from .audio_io import load_audio, save_audio

ANALYSIS_SR = 22050  # Samplerate für Melodie-/Akkord-Analyse (schneller als 44100)

# Ab diesem Energieanteil der Klavierspur wählt "auto" den Klavier-Modus
PIANO_SHARE_THRESHOLD = 0.05


def transcribe(
    input_path: str | Path,
    out_dir: str | Path = "output",
    skip_separation: bool = False,
    save_stems: bool = False,
    progress: bool = True,
    on_progress=None,
    mode: str = "auto",
) -> dict:
    """Transkribiert einen Song zu Klaviernoten.

    Args:
        on_progress: optionaler Callback (schritt, gesamt, meldung) für UIs.
        mode: "klavier" (Klavierspur isolieren und direkt transkribieren),
              "gesang" (Gesangsmelodie + Begleitakkorde) oder "auto"
              (Klavier-Modus, wenn der Song genug Klavier enthält).

    Returns:
        Zusammenfassung (Pfade, Tempo, Tonart, Akkordfolge).
    """
    input_path = Path(input_path)
    name = input_path.stem
    song_out = Path(out_dir) / name
    song_out.mkdir(parents=True, exist_ok=True)

    def log(*args, **kwargs):
        if progress:
            print(*args, **kwargs)

    def report(step, message):
        if on_progress:
            on_progress(step, 5, message)

    report(1, "Lade Audio ...")
    log(f"[1/5] Lade Audio: {input_path.name}")
    y, sr = load_audio(input_path)
    duration = y.shape[-1] / sr

    stems_dir = song_out / "stems"
    stem_names = separate.STEM_NAMES
    stems = None

    if skip_separation:
        log("[2/5] Instrumententrennung übersprungen")
        mono = y.mean(axis=0) if y.ndim == 2 else y
        vocals, accomp, mix = mono, mono, mono
        stem_sr = sr
    elif all((stems_dir / f"{n}.wav").exists() for n in stem_names):
        report(2, "Verwende zwischengespeicherte Spuren ...")
        log("[2/5] Verwende zwischengespeicherte Spuren aus " + str(stems_dir))
        stem_sr = 44100
        stems = {n: load_audio(stems_dir / f"{n}.wav", sr=stem_sr, mono=True)[0] for n in stem_names}
        vocals = stems["vocals"]
        accomp = separate.accompaniment(stems)
        mix = np.sum(list(stems.values()), axis=0)
    else:
        report(2, "Trenne Instrumente (KI-Modell, dauert einige Minuten) ...")
        log("[2/5] Trenne Instrumente (Demucs, kann einige Minuten dauern) ...")
        t0 = time.time()
        stems = separate.separate(y, sr, progress=progress)
        stem_sr = 44100
        vocals = stems["vocals"]
        accomp = separate.accompaniment(stems)
        mix = np.sum(list(stems.values()), axis=0)
        log(f"      fertig in {time.time() - t0:.0f}s")
        # Spuren zwischenspeichern: erneute Läufe überspringen dann Demucs
        for n in stem_names:
            save_audio(stems_dir / f"{n}.wav", stems[n], stem_sr)
        if save_stems:
            save_audio(song_out / "begleitung.wav", accomp, stem_sr)

    # Modus wählen: Klavier-Transkription nur, wenn eine Klavierspur da ist
    if stems is None:
        mode_used = "gesang"
    elif mode == "auto":
        share = piano.piano_energy_share(stems)
        mode_used = "klavier" if share >= PIANO_SHARE_THRESHOLD else "gesang"
        log(f"      Klavier-Energieanteil: {share:.1%} -> Modus: {mode_used}")
    else:
        mode_used = mode

    # Für die Analyse auf 22050 Hz heruntertakten
    import librosa

    vocals_a = librosa.resample(vocals, orig_sr=stem_sr, target_sr=ANALYSIS_SR)
    accomp_a = librosa.resample(accomp, orig_sr=stem_sr, target_sr=ANALYSIS_SR)
    mix_a = librosa.resample(mix, orig_sr=stem_sr, target_sr=ANALYSIS_SR)

    report(3, "Erkenne Tempo und Beats ...")
    log("[3/5] Erkenne Tempo und Beats ...")
    grid = rhythm.detect_beats(mix_a, ANALYSIS_SR, duration=duration)
    log(f"      Tempo: {grid.tempo:.0f} BPM, {len(grid.beat_times)} Beats")

    # Erst die allgemeinen Tatsachen des Stücks: Tonart (Dur/Moll, Grundton).
    # Die Akkorderkennung darf danach nur noch leitereigene Akkorde wählen.
    song_key = keys.detect_key_from_audio(accomp_a, ANALYSIS_SR)
    log(f"      Tonart: {song_key.name} (Konfidenz {song_key.confidence:.2f})")
    labels = chords.detect_chords(
        accomp_a, ANALYSIS_SR, grid.beat_times, allowed=song_key.allowed_chords()
    )
    segments = chords.to_segments(labels)

    if mode_used == "klavier":
        report(4, "Transkribiere Klavierspur (KI-Modell) ...")
        events_cache = song_out / "klavier_noten.json"
        if events_cache.exists():
            log("[4/5] Verwende zwischengespeicherte Klavier-Transkription")
            events = [tuple(e) for e in json.loads(events_cache.read_text(encoding="utf-8"))]
        else:
            log("[4/5] Transkribiere Klavierspur (ByteDance-Modell) ...")
            t0 = time.time()
            events = piano.transcribe_piano(
                stems["piano"], stem_sr, midi_out=song_out / "klavier_roh.mid"
            )
            events_cache.write_text(json.dumps(events), encoding="utf-8")
            log(f"      {len(events)} Klavier-Noten in {time.time() - t0:.0f}s")

        right_groups, left_groups = arrange.quantize_piano(
            events,
            grid,
            chord_lookup=chords.pc_lookup(segments),
            key_pcs=song_key.scale_pcs(),
        )

        # Gesangsmelodie hat Vorrang in der rechten Hand; Klavier füllt Pausen
        vocal_notes = melody.extract_melody(vocals_a, ANALYSIS_SR)
        vocal_notes = melody.normalize_octave(vocal_notes)
        vocal_events = arrange.quantize_melody(vocal_notes, grid)
        total_q = max(grid.total_quarters, 1.0)
        coverage = sum(e - s for s, e, _ in vocal_events) / total_q
        if coverage >= 0.10:
            right_groups = arrange.merge_melody_and_fills(vocal_events, right_groups)
            log(f"      Hybrid: Gesangsmelodie ({coverage:.0%} des Stücks) + Klavier-Füllungen")
        else:
            log("      Kein nennenswerter Gesang -> reines Klavier-Arrangement")

        report(5, "Baue Klaviersatz ...")
        log("[5/5] Baue Klaviersatz ...")
        score, detected_key = arrange.build_piano_score(
            right_groups, left_groups, segments, grid.tempo,
            title=name, key_name=song_key.music21_name,
        )
        n_notes = len(events)
        data_args = ("klavier", right_groups, left_groups)
        easy_source = right_groups
    else:
        report(4, "Extrahiere Gesangsmelodie ...")
        log("[4/5] Extrahiere Gesangsmelodie ...")
        notes = melody.extract_melody(vocals_a, ANALYSIS_SR)
        notes = melody.normalize_octave(notes)
        log(f"      {len(notes)} Melodie-Noten, {len(segments)} Akkord-Segmente")

        report(5, "Baue Klaviersatz ...")
        log("[5/5] Baue Klaviersatz ...")
        score, detected_key = arrange.build_score(
            notes, segments, grid, title=name, key_name=song_key.music21_name
        )
        n_notes = len(notes)
        data_args = ("gesang", notes, None)
        easy_source = [
            (s, e - s, [p], 92) for s, e, p in arrange.quantize_melody(notes, grid)
        ]

    paths = arrange.write_outputs(score, song_out, name)

    # Vereinfachte Fassung: einstimmige Melodie + Grundton/Quinte-Begleitung
    easy_score, _, easy_right, easy_left = arrange.build_easy_score(
        easy_source, segments, grid.tempo, title=name, key_name=song_key.music21_name
    )
    arrange.write_outputs(easy_score, song_out, name + "_einfach")

    chords_txt = _format_chords(segments)
    (song_out / "chords.txt").write_text(chords_txt, encoding="utf-8")

    _write_data_json(song_out, name, data_args, segments, grid, detected_key)
    _write_data_json(
        song_out, name, ("klavier", easy_right, easy_left), segments, grid,
        detected_key, fname="data_einfach.json", mode_label=mode_used,
    )

    summary = {
        "musicxml": str(paths["musicxml"]),
        "midi": str(paths["midi"]),
        "tempo": round(grid.tempo),
        "key": str(detected_key) if detected_key else "unbekannt",
        "mode": mode_used,
        "n_notes": n_notes,
        "chords": [s.label for s in segments if s.label != "N"],
    }
    log(f"\nFertig! Modus: {mode_used}, Tonart: {summary['key']}, Tempo: {summary['tempo']} BPM")
    log(f"Noten:  {summary['musicxml']}")
    log(f"MIDI:   {summary['midi']}")
    return summary


def _write_data_json(
    song_out: Path, name: str, data_args, segments, grid, detected_key,
    fname: str = "data.json", mode_label: str | None = None,
):
    """Schreibt Noten/Akkorde als JSON für die Browser-Wiedergabe.

    Im Gesangs-Modus: Melodie + Begleit-Dreiklänge.
    Im Klavier-Modus (und für die vereinfachte Fassung): rechte Hand als
    "melody", linke Hand als "chords".
    """
    mode_used, first, second = data_args

    if mode_used == "klavier":
        right_groups, left_groups = first, second
        melody_json = [
            {"start": s, "duration": d, "midi": m, "velocity": v}
            for s, d, midis, v in right_groups
            for m in midis
        ]
        chords_json = [
            {"start": s, "duration": d, "label": "", "midis": midis, "velocity": v}
            for s, d, midis, v in left_groups
        ]
        ends = [s + d for s, d, _, _ in right_groups + left_groups]
    else:
        events = arrange.quantize_melody(first, grid)
        melody_json = [
            {"start": s, "duration": e - s, "midi": p} for s, e, p in events
        ]
        chords_json = [
            {
                "start": seg.start_quarter,
                "duration": seg.end_quarter - seg.start_quarter,
                "label": seg.label,
                "midis": arrange._voice_triad(seg.root, seg.minor),
            }
            for seg in segments
            if seg.label != "N"
        ]
        ends = [e for _, e, _ in events]

    total = max(ends + [s.end_quarter for s in segments] + [0.0])
    data = {
        "title": name,
        "mode": mode_label or mode_used,
        "tempo": round(grid.tempo),
        "key": str(detected_key).replace("-", "b") if detected_key else None,
        "totalQuarters": total,
        "melody": melody_json,
        "chords": chords_json,
    }
    (song_out / fname).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _format_chords(segments) -> str:
    """Akkordfolge taktweise als Text (4 Viertel pro Takt)."""
    lines = ["Akkordfolge (pro Takt, 4/4):", ""]
    by_bar: dict[int, list[str]] = {}
    for seg in segments:
        q = seg.start_quarter
        while q < seg.end_quarter:
            bar = int(q // 4)
            by_bar.setdefault(bar, [])
            if not by_bar[bar] or by_bar[bar][-1] != seg.label:
                by_bar[bar].append(seg.label)
            q += 2.0
    for bar in sorted(by_bar):
        lines.append(f"Takt {bar + 1:3d}: " + "  ".join(by_bar[bar]))
    return "\n".join(lines) + "\n"
