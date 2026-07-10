"""Baut aus Melodie/Klavier-Transkription und Akkorden einen zweihändigen Klaviersatz (music21)."""

from pathlib import Path

from .chords import ChordSegment, NO_CHORD
from .melody import MelodyNote
from .rhythm import BeatGrid

HAND_SPLIT = 60  # C4: darunter linke Hand, ab hier rechte


def _scaffold(title: str, tempo_bpm: float):
    """Leere Partitur mit zwei Klavier-Systemen (Violin-/Bassschlüssel)."""
    from music21 import clef, instrument, metadata, meter, stream, tempo

    score = stream.Score()
    md = metadata.Metadata()
    md.title = title
    md.composer = "NotenErkennung"
    score.insert(0, md)

    right = stream.Part()
    right.id = "RechteHand"
    right.insert(0, instrument.Piano())
    right.insert(0, clef.TrebleClef())
    right.insert(0, meter.TimeSignature("4/4"))
    right.insert(0, tempo.MetronomeMark(number=round(tempo_bpm)))

    left = stream.Part()
    left.id = "LinkeHand"
    left.insert(0, instrument.Piano())
    left.insert(0, clef.BassClef())
    left.insert(0, meter.TimeSignature("4/4"))

    return score, right, left


def _finish(score, right, left, key_name: str | None = None):
    """Systeme einhängen, Tonart als Vorzeichnung eintragen.

    key_name: bereits bestimmte Tonart im music21-Format (z. B. "D" oder "b");
    ohne Angabe wird music21s eigene Analyse als Rückfall benutzt.
    """
    from music21 import key

    score.insert(0, right)
    score.insert(0, left)
    detected = None
    if key_name:
        try:
            detected = key.Key(key_name)
        except Exception:
            detected = None
    if detected is None:
        try:
            detected = score.analyze("key")
        except Exception:
            detected = None
    if detected is not None:
        ks = key.KeySignature(detected.sharps)
        for part in (right, left):
            part.insert(0, ks)
    return score, detected


def build_score(
    melody: list[MelodyNote],
    chord_segments: list[ChordSegment],
    grid: BeatGrid,
    title: str = "Transkription",
    key_name: str | None = None,
):
    """Gesangs-Modus: rechte Hand Melodie, linke Hand Begleit-Akkorde."""
    score, right, left = _scaffold(title, grid.tempo)
    _fill_right_hand(right, melody, grid)
    _fill_left_hand(left, chord_segments)
    _add_chord_symbols(right, chord_segments)
    return _finish(score, right, left, key_name)


def build_piano_score(
    right_groups: list[tuple[float, float, list[int], int]],
    left_groups: list[tuple[float, float, list[int], int]],
    chord_segments: list[ChordSegment],
    tempo_bpm: float,
    title: str = "Transkription",
    key_name: str | None = None,
):
    """Klavier-Modus: beide Hände aus Klavier-Transkription (+ ggf. Gesangsmelodie)."""
    score, right, left = _scaffold(title, tempo_bpm)
    _fill_groups(right, right_groups)
    _fill_groups(left, left_groups)
    _add_chord_symbols(right, chord_segments)
    return _finish(score, right, left, key_name)


def quantize_piano(
    events: list[tuple[float, float, int, int]],
    grid: BeatGrid,
    chord_lookup=None,
    key_pcs: set[int] | None = None,
    max_chord_notes: int = 4,
) -> tuple[list, list]:
    """Quantisiert Klavier-Notenereignisse und teilt sie auf die Hände auf.

    Gleichzeitig angeschlagene Töne einer Hand werden zu Akkorden gruppiert
    und musikalisch aufgeräumt: Töne, die weder zum erkannten Akkord noch zur
    Tonart passen, fliegen raus (laute Ausnahmen bleiben – echte Chromatik),
    und Akkorde werden auf max_chord_notes begrenzt (Bass bleibt immer).
    Kleine Lücken zum nächsten Anschlag derselben Hand werden legato
    geschlossen (wie das Haltepedal des Pianisten).

    Args:
        chord_lookup: Funktion Viertel-Offset -> Menge der Akkord-Pitch-Classes.
        key_pcs: Pitch-Classes der Tonleiter der erkannten Tonart.

    Returns:
        (rechte, linke) Hand als Listen von (start, dauer, [midis], velocity)
        in Vierteln.
    """
    hands: dict[str, dict[float, list[tuple[float, int, int]]]] = {"r": {}, "l": {}}
    for start_s, end_s, midi, vel in events:
        if midi < 28:  # unter E1: fast immer Trennungs-Artefakt -> Oktave hoch
            midi += 12
        start_q = grid.time_to_quarter(start_s, MELODY_SUBDIV)
        end_q = max(grid.time_to_quarter(end_s, MELODY_SUBDIV), start_q + MIN_LEN)
        hand = "r" if midi >= HAND_SPLIT else "l"
        hands[hand].setdefault(start_q, []).append((end_q, midi, vel))

    result = []
    for hand in ("r", "l"):
        groups = []
        starts = sorted(hands[hand])
        for i, s in enumerate(starts):
            group = hands[hand][s]
            chord_pcs = chord_lookup(s) if chord_lookup else None
            kept = _clean_cluster(
                [(m, v, e) for e, m, v in group], chord_pcs, key_pcs, max_chord_notes
            )
            end = max(e for _, _, e in kept)
            if i + 1 < len(starts):
                nxt = starts[i + 1]
                if end > nxt or nxt - end <= LEGATO_GAP:
                    end = nxt  # Überlappung kappen bzw. Lücke legato schließen
            duration = min(max(end - s, MIN_LEN), 4.0)
            midis = sorted({m for m, _, _ in kept})
            velocity = int(sum(v for _, v, _ in kept) / len(kept))
            groups.append((s, duration, midis, velocity))
        result.append(groups)
    return result[0], result[1]


def _clean_cluster(
    notes: list[tuple[int, int, float]],
    chord_pcs: set[int] | None,
    key_pcs: set[int] | None,
    max_notes: int,
) -> list[tuple[int, int, float]]:
    """Filtert einen gleichzeitig angeschlagenen Notenhaufen musikalisch.

    notes: Liste von (midi, velocity, ende).
    Behalten wird ein Ton, wenn er zum Akkord gehört, oder zur Tonart gehört
    und nicht deutlich leiser als der lauteste Ton ist, oder selbst fast so
    laut wie der lauteste ist (bewusste Chromatik).
    """
    if len(notes) <= 1:
        return notes

    max_vel = max(v for _, v, _ in notes)
    kept = []
    for m, v, e in notes:
        pc = m % 12
        if chord_pcs and pc in chord_pcs:
            ok = True
        elif key_pcs and pc in key_pcs:
            ok = v >= 0.5 * max_vel
        elif chord_pcs is None and key_pcs is None:
            ok = True
        else:
            ok = v >= 0.85 * max_vel
        if ok:
            kept.append((m, v, e))
    if not kept:
        kept = [max(notes, key=lambda n: n[1])]

    if len(kept) > max_notes:
        bass = min(kept, key=lambda n: n[0])
        rest = sorted((n for n in kept if n is not bass), key=lambda n: -n[1])[: max_notes - 1]
        kept = sorted([bass] + rest, key=lambda n: n[0])
    return kept


def simplify_right(groups: list[tuple[float, float, list[int], int]]) -> list[tuple[float, float, list[int], int]]:
    """Reduziert die rechte Hand auf eine einstimmige Melodielinie.

    Nur der oberste Ton jedes Griffs bleibt, alles wird aufs Achtel-Raster
    vergröbert, Kollisionen werden aufgelöst und Lücken legato geschlossen.
    """
    events = []
    for s, d, midis, vel in groups:
        s8 = round(s * 2) / 2
        e8 = max(round((s + d) * 2) / 2, s8 + 0.5)
        events.append([s8, e8, max(midis), vel])
    events.sort(key=lambda e: e[0])

    deduped: list[list] = []
    for e in events:
        if deduped and deduped[-1][0] == e[0]:
            if e[1] - e[0] > deduped[-1][1] - deduped[-1][0]:
                deduped[-1] = e
        else:
            deduped.append(e)

    for cur, nxt in zip(deduped, deduped[1:]):
        if cur[1] > nxt[0] or nxt[0] - cur[1] <= LEGATO_GAP:
            cur[1] = nxt[0]

    return [(s, e - s, [m], vel) for s, e, m, vel in deduped if e > s]


def simplify_left(segments: list[ChordSegment]) -> list[tuple[float, float, list[int], int]]:
    """Linke Hand auf das Nötigste: ein Anschlag pro Akkordwechsel,
    nur Grundton + Quinte (zwei Töne, klingt in Dur wie Moll richtig)."""
    groups = []
    for seg in segments:
        length = seg.end_quarter - seg.start_quarter
        if length <= 0 or seg.label == NO_CHORD:
            continue
        root = seg.root + 36
        if root < 40:
            root += 12
        groups.append((seg.start_quarter, min(length, 4.0), [root, root + 7], 60))
    return groups


def build_easy_score(
    right_groups: list[tuple[float, float, list[int], int]],
    chord_segments: list[ChordSegment],
    tempo_bpm: float,
    title: str = "Transkription",
    key_name: str | None = None,
):
    """Vereinfachte Fassung: einstimmige Melodie + Grundton/Quinte-Begleitung."""
    easy_right = simplify_right(right_groups)
    easy_left = simplify_left(chord_segments)
    score, right, left = _scaffold(title + " (vereinfacht)", tempo_bpm)
    _fill_groups(right, easy_right)
    _fill_groups(left, easy_left)
    _add_chord_symbols(right, chord_segments)
    score, detected = _finish(score, right, left, key_name)
    return score, detected, easy_right, easy_left


def merge_melody_and_fills(
    vocal_events: list[tuple[float, float, int]],
    piano_right_groups: list[tuple[float, float, list[int], int]],
) -> list[tuple[float, float, list[int], int]]:
    """Hybrid-Arrangement für die rechte Hand.

    Die Gesangsmelodie hat Vorrang; das Klaviermaterial der rechten Hand
    füllt nur die Gesangspausen (Intro, Zwischenspiele, Outro). Füllungen,
    die in eine Melodienote hineinragen würden, werden gekürzt.
    """
    vocals = sorted(vocal_events)
    out: list[tuple[float, float, list[int], int]] = [
        (s, e - s, [p], 92) for s, e, p in vocals
    ]

    for s, d, midis, vel in piano_right_groups:
        end = s + d
        clipped_end = end
        inside_vocal = False
        for vs, ve, _ in vocals:
            if vs <= s < ve:
                inside_vocal = True  # Füllung beginnt mitten im Gesang -> weg
                break
            if s < vs < clipped_end:
                clipped_end = vs  # ragt in den Gesang hinein -> kürzen
        if inside_vocal or clipped_end - s < MIN_LEN:
            continue
        out.append((s, clipped_end - s, midis, vel))

    out.sort(key=lambda g: g[0])
    return out


def _fill_groups(part, groups):
    from music21 import chord as m21chord
    from music21 import note

    for start_q, duration, midis, _velocity in groups:
        el = note.Note(midis[0]) if len(midis) == 1 else m21chord.Chord(midis)
        el.quarterLength = duration
        part.insert(start_q, el)


MELODY_SUBDIV = 4       # Sechzehntel-Raster
MIN_LEN = 1.0 / MELODY_SUBDIV
LEGATO_GAP = 0.5        # Lücken bis zu einer Achtel werden verbunden


def quantize_melody(melody: list[MelodyNote], grid: BeatGrid) -> list[tuple[float, float, int]]:
    """Quantisiert Melodienoten aufs Sechzehntel-Raster, überlappungsfrei und legato.

    Statt kollidierende Noten zu verwerfen, wird gekürzt bzw. bei gleichem
    Startpunkt die längere Note behalten; kleine Lücken werden geschlossen,
    damit die Melodie fließt.

    Returns:
        Liste von (start, ende, midi) in Viertel-Offsets.
    """
    events = []
    for n in melody:
        start_q = grid.time_to_quarter(n.start, MELODY_SUBDIV)
        end_q = grid.time_to_quarter(n.end, MELODY_SUBDIV)
        events.append([start_q, max(end_q, start_q + MIN_LEN), n.pitch, n.duration])
    events.sort(key=lambda e: e[0])

    # Gleicher Startpunkt: nur die (im Original) längste Note behalten
    deduped = []
    for e in events:
        if deduped and deduped[-1][0] == e[0]:
            if e[3] > deduped[-1][3]:
                deduped[-1] = e
        else:
            deduped.append(e)

    # Überlappungen kürzen, kleine Lücken legato schließen
    for cur, nxt in zip(deduped, deduped[1:]):
        if cur[1] > nxt[0] or nxt[0] - cur[1] <= LEGATO_GAP:
            cur[1] = nxt[0]

    return [(s, e, p) for s, e, p, _ in deduped if e > s]


def _fill_right_hand(part, melody: list[MelodyNote], grid: BeatGrid):
    from music21 import note

    for start_q, end_q, pitch in quantize_melody(melody, grid):
        m21n = note.Note(pitch)
        m21n.quarterLength = end_q - start_q
        part.insert(start_q, m21n)


def _fill_left_hand(part, segments: list[ChordSegment]):
    from music21 import chord as m21chord
    from music21 import note

    for seg in segments:
        length = seg.end_quarter - seg.start_quarter
        if length <= 0:
            continue
        if seg.label == NO_CHORD:
            continue  # Lücke wird beim Notensatz automatisch zur Pause
        pitches = _voice_triad(seg.root, seg.minor)
        c = m21chord.Chord(pitches)
        c.quarterLength = length
        part.insert(seg.start_quarter, c)


def _add_chord_symbols(part, segments: list[ChordSegment]):
    """Akkordnamen (C, Am, ...) über dem oberen System eintragen."""
    from music21 import harmony

    previous = None
    for seg in segments:
        if seg.label == NO_CHORD or seg.label == previous:
            previous = seg.label if seg.label != NO_CHORD else previous
            continue
        try:
            symbol = harmony.ChordSymbol(seg.label)
            symbol.writeAsChord = False
            part.insert(seg.start_quarter, symbol)
            previous = seg.label
        except Exception:
            continue  # unbekanntes Label überspringen, Noten bleiben korrekt


def _voice_triad(root_pc: int, minor: bool) -> list[int]:
    """Dreiklang in Grundstellung, Grundton im Bereich E2(40)–D#3(51)."""
    root = root_pc + 36  # Oktave ab C2
    if root < 40:
        root += 12
    third = root + (3 if minor else 4)
    fifth = root + 7
    return [root, third, fifth]


def write_outputs(score, out_dir: str | Path, name: str) -> dict[str, Path]:
    """Schreibt MusicXML und MIDI, gibt die Pfade zurück."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    xml_path = out / f"{name}.musicxml"
    midi_path = out / f"{name}.mid"
    score.write("musicxml", fp=str(xml_path))
    score.write("midi", fp=str(midi_path))
    return {"musicxml": xml_path, "midi": midi_path}
