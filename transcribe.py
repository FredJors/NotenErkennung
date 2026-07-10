"""Kommandozeilen-Einstieg: MP3 -> Klaviernoten.

Benutzung:
    python transcribe.py "C:\\Pfad\\zum\\song.mp3" [-o output] [--save-stems] [--skip-separation]
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Erzeugt Klaviernoten aus einer Audiodatei.")
    parser.add_argument("input", help="Pfad zur Audiodatei (MP3, WAV, FLAC, ...)")
    parser.add_argument("-o", "--output", default="output", help="Ausgabeordner (Standard: output)")
    parser.add_argument("--save-stems", action="store_true", help="Getrennte Spuren mit abspeichern")
    parser.add_argument(
        "--skip-separation",
        action="store_true",
        help="Instrumententrennung überspringen (nur für Tests mit sauberen Aufnahmen)",
    )
    parser.add_argument(
        "--modus",
        choices=["auto", "klavier", "gesang"],
        default="auto",
        help="klavier: Klavierspur isolieren und transkribieren; gesang: Gesangsmelodie + Akkorde; auto: nach Klavieranteil entscheiden",
    )
    args = parser.parse_args()

    from pathlib import Path

    if not Path(args.input).exists():
        print(f"Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    from noten.pipeline import transcribe

    transcribe(
        args.input,
        out_dir=args.output,
        skip_separation=args.skip_separation,
        save_stems=args.save_stems,
        mode=args.modus,
    )


if __name__ == "__main__":
    main()
