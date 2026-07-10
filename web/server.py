"""Lokaler Webserver für die Browser-Oberfläche.

Start (aus dem Projektordner):
    python -m uvicorn web.server:app --port 8765
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

OUTPUT_DIR = ROOT / "output"
STATIC_DIR = Path(__file__).resolve().parent / "static"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}

app = FastAPI(title="NotenErkennung")


@app.middleware("http")
async def no_cache(request, call_next):
    """Verhindert veraltete App-Dateien im Browser-Cache.

    Ohne das kann der Browser tagelang eine alte app.js benutzen, obwohl
    der Server längst eine neue ausliefert. Die große Noten-Bibliothek
    (vendor/) darf gecacht bleiben, wird aber weiterhin revalidiert.
    """
    response = await call_next(request)
    if "/vendor/" not in request.url.path:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _audio_files() -> list[Path]:
    return sorted(
        (p for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
        key=lambda p: p.name.lower(),
    )


def _transcribed() -> set[str]:
    done = set()
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if (d / "data.json").exists() and (d / f"{d.name}.musicxml").exists():
                done.add(d.name)
    return done


@app.get("/api/songs")
def list_songs():
    done = _transcribed()
    songs = []
    for p in _audio_files():
        job = _jobs.get(p.stem)
        songs.append(
            {
                "file": p.name,
                "name": p.stem,
                "transcribed": p.stem in done,
                "job": job,
            }
        )
    known = {s["name"] for s in songs}
    for name in sorted(done - known):
        songs.append({"file": None, "name": name, "transcribed": True, "job": None})
    return songs


@app.post("/api/transcribe/{file_name}")
def start_transcription(file_name: str):
    path = next((p for p in _audio_files() if p.name == file_name), None)
    if path is None:
        raise HTTPException(404, f"Audiodatei nicht gefunden: {file_name}")
    name = path.stem
    with _lock:
        job = _jobs.get(name)
        if job and job["state"] == "running":
            return job
        job = {"state": "running", "step": 0, "total": 5, "message": "Starte ..."}
        _jobs[name] = job
    threading.Thread(target=_run_job, args=(path, job), daemon=True).start()
    return job


def _run_job(path: Path, job: dict):
    from noten.pipeline import transcribe

    def on_progress(step, total, message):
        job.update(step=step, total=total, message=message)

    try:
        transcribe(path, out_dir=OUTPUT_DIR, progress=False, on_progress=on_progress)
        job.update(state="done", step=5, message="Fertig")
    except Exception as exc:  # Fehler in der UI anzeigen statt Thread-Absturz
        job.update(state="error", message=f"{type(exc).__name__}: {exc}")


@app.get("/api/status/{name}")
def status(name: str):
    return _jobs.get(name) or {"state": "none"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    filename = Path(file.filename or "upload.mp3").name
    if Path(filename).suffix.lower() not in AUDIO_EXTS:
        raise HTTPException(400, "Nur Audiodateien (mp3, wav, flac, ogg, m4a)")
    target = ROOT / filename
    data = await file.read()
    target.write_bytes(data)
    return {"file": filename, "name": target.stem}


@app.get("/api/result/{name}/{kind}")
def result(name: str, kind: str):
    song_dir = (OUTPUT_DIR / name).resolve()
    if not song_dir.is_relative_to(OUTPUT_DIR.resolve()) or not song_dir.is_dir():
        raise HTTPException(404, "Song nicht gefunden")
    files = {
        "data": (song_dir / "data.json", "application/json", None),
        "musicxml": (song_dir / f"{name}.musicxml", "application/xml", f"{name}.musicxml"),
        "midi": (song_dir / f"{name}.mid", "audio/midi", f"{name}.mid"),
        "chords": (song_dir / "chords.txt", "text/plain; charset=utf-8", None),
        "data_einfach": (song_dir / "data_einfach.json", "application/json", None),
        "musicxml_einfach": (
            song_dir / f"{name}_einfach.musicxml", "application/xml", f"{name}_einfach.musicxml",
        ),
        "midi_einfach": (
            song_dir / f"{name}_einfach.mid", "audio/midi", f"{name}_einfach.mid",
        ),
    }
    if kind not in files:
        raise HTTPException(404, "Unbekannter Ausgabetyp")
    path, media, download = files[kind]
    if not path.exists():
        raise HTTPException(404, f"Noch nicht vorhanden: {path.name}")
    kwargs = {"filename": download} if download else {}
    return FileResponse(path, media_type=media, **kwargs)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
