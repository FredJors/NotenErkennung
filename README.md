# NotenErkennung

Ein Tool, das aus einer beliebigen MP3-Datei spielbare Klaviernoten erzeugt –
und (in einer späteren Etappe) eine Schritt-für-Schritt-Anleitung zum Lernen des Stücks.

## Wie es funktioniert

1. **Instrumententrennung** (Demucs htdemucs_6s): Der Song wird in sechs Spuren
   zerlegt – Gesang, Bass, Schlagzeug, Gitarre, **Klavier** und Rest.
2. Danach gibt es zwei Modi (`--modus`, Standard `auto`):
   - **klavier** – Die isolierte Klavierspur wird mit dem ByteDance-Modell
     (Spezial-KI für Klavier, gleiche Technik wie kommerzielle Klavier-Apps)
     polyphon transkribiert; die Noten werden bei C4 auf rechte/linke Hand
     aufgeteilt. Das rohe, unquantisierte MIDI liegt als `klavier_roh.mid` bei.
   - **gesang** – Gesangsmelodie (librosa/pYIN) → rechte Hand, erkannte
     Akkorde (Chroma-Analyse) → linke Hand, wie ein menschlicher Arrangeur.
   - **auto** wählt `klavier`, wenn die Klavierspur genug Energieanteil hat.
3. **Notensatz** (music21): Quantisierung aufs Sechzehntel-Raster, Akkordsymbole,
   Tonart – Ausgabe als MusicXML + MIDI.

## Setup

Die Python-Umgebung liegt bewusst **außerhalb** dieses OneDrive-Ordners
(damit OneDrive nicht Gigabytes an Bibliotheksdateien synchronisiert):

```
%USERPROFILE%\venvs\NotenErkennung
```

Einmalig einrichten (falls noch nicht vorhanden):

```powershell
python -m venv "$env:USERPROFILE\venvs\NotenErkennung"
& "$env:USERPROFILE\venvs\NotenErkennung\Scripts\python.exe" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
& "$env:USERPROFILE\venvs\NotenErkennung\Scripts\python.exe" -m pip install -r requirements.txt
```

## Benutzung

### Browser-Oberfläche (empfohlen)

**Doppelklick auf `NotenErkennung starten.bat`** im Projektordner – fertig.
Das schwarze Fenster offen lassen; zum Beenden einfach schließen.

Alternativ aus PowerShell (falls Skriptausführung erlaubt ist):

```powershell
.\web.ps1
```

Öffnet http://localhost:8765 – dort Songs hochladen (oder MP3s in den
Projektordner legen), Transkription starten, Noten ansehen, abspielen
(wahlweise nur rechte/linke Hand, Tempo regelbar) und als PDF speichern
(Knopf „Als PDF speichern“ → im Druckdialog „Als PDF speichern“ wählen).

### Kommandozeile

```powershell
.\noten.ps1 "C:\Pfad\zum\song.mp3"
```

Ergebnis landet in `output\<songname>\`:

- `<songname>.musicxml` – die Noten (öffnen mit MuseScore o. ä.)
- `<songname>.mid` – MIDI zum Anhören
- `chords.txt` – erkannte Akkordfolge pro Takt
- `data.json` – Noten/Akkorde für die Browser-Wiedergabe
- `stems\` – zwischengespeicherte Demucs-Spuren; erneute Läufe überspringen
  damit die langsame Instrumententrennung (Ordner löschen erzwingt Neutrennung)

Optionen:

- `--modus klavier|gesang|auto` – siehe oben (Standard: auto)
- `--skip-separation` – Instrumententrennung überspringen (nur für Tests)

### Schöneres PDF (optional)

Das kostenlose [MuseScore](https://musescore.org) öffnet die `.musicxml`
und exportiert Verlags-Qualität: Datei → Exportieren → PDF.

## Projektstruktur

```
noten/
  audio_io.py    Audio laden (MP3/WAV)
  separate.py    Instrumententrennung (Demucs)
  melody.py      Melodie-Extraktion aus der Gesangsspur
  rhythm.py      Tempo- und Beat-Erkennung, Quantisierung
  chords.py      Akkord-Erkennung aus der Begleitung
  arrange.py     Klaviersatz bauen (music21), Akkordsymbole
  pipeline.py    Gesamtablauf, Spuren-Cache, data.json
transcribe.py    Kommandozeilen-Einstieg
web/
  server.py      Lokaler Webserver (FastAPI)
  static/        Oberfläche (OpenSheetMusicDisplay, WebAudio-Wiedergabe)
tests/           synthetischer Testsong + Smoke-Tests
```

## Roadmap

- [x] Etappe 1: Kern-Pipeline MP3 → MusicXML/MIDI
- [x] Etappe 2: Browser-Oberfläche mit Notenanzeige, Wiedergabe, PDF-Druck
- [ ] Etappe 3: Lernplan-Generator (Akkorde üben → Passagen → Hände einzeln → zusammen)
- [ ] Etappe 4: Bessere Arrangements (Begleitmuster, Schwierigkeitsstufen)

## Bekannte Grenzen

- Taktart ist fest 4/4 angenommen (für Pop meist richtig).
- Tempo über 140 BPM wird halbiert (Halftime-Heuristik) – bei wirklich
  schnellen Stücken kann das falsch sein.
- Gerappte/gesprochene Passagen ergeben keine sinnvolle Melodie.
- Tonart-Erkennung kann zwischen verwandten Tonarten schwanken (z. B. D-/G-Dur).
