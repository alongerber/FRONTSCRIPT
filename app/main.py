"""פרונט סטודיו — שרת אחד שמגיש גם את הממשק וגם את כל הלוגיקה."""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import BASE_DIR, settings
from .engines import avatar as avatar_engine
from .engines import broll as broll_engine
from .engines import captions as captions_engine
from .engines import editor as editor_engine
from .engines import script as script_engine
from .engines import voice as voice_engine
from .jobs import Job, jobs
from .storage import AUDIO_EXTS, VIDEO_EXTS, new_id, safe_id, store

app = FastAPI(title="פרונט סטודיו", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

SESSION_COOKIE = "front_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
_signer = URLSafeTimedSerializer(settings.secret_key, salt="front-studio")

MAX_UPLOAD_BYTES = 512 * 1024 * 1024


# ============================================================ כניסה ואבטחה

def _is_authed(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        _signer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except BadSignature:
        return False
    except Exception:  # noqa: BLE001 — טוקן פגום או ישן, פשוט לא מחובר
        return False


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    public = path.startswith("/static") or path in {"/login", "/healthz"}
    if not public and not _is_authed(request):
        if path.startswith("/api/") or path.startswith("/media/"):
            return JSONResponse({"error": "לא מחובר"}, status_code=401)
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "ffmpeg": editor_engine.ffmpeg_available()}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_authed(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form("")):
    expected = settings.studio_password
    if not expected:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "לא הוגדרה סיסמה. מלא STUDIO_PASSWORD בקובץ .env."},
            status_code=500,
        )
    # השוואה בזמן קבוע כדי לא לדלוף מידע על אורך הסיסמה
    import hmac

    if not hmac.compare_digest(password, expected):
        await asyncio.sleep(0.6)
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "סיסמה שגויה"}, status_code=401
        )

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        _signer.dumps({"t": time.time()}),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ==================================================================== מדיה

@app.get("/media/{kind}/{rest:path}")
async def media(kind: str, rest: str):
    """מגיש קבצי מדיה, עם חסימת יציאה מהתיקייה."""
    roots = {
        "library": settings.library_dir,
        "projects": settings.projects_dir,
        "exports": settings.exports_dir,
    }
    root = roots.get(kind)
    if root is None:
        raise HTTPException(404)
    target = (root / rest).resolve()
    if not str(target).startswith(str(root.resolve())) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


# ============================================================== עזרי פרויקט

def _load(project_id: str) -> dict[str, Any]:
    try:
        return store.load(safe_id(project_id))
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "פרויקט לא נמצא")


def _project_url(project: dict[str, Any], path: Path) -> str:
    rel = path.relative_to(settings.projects_dir)
    return f"/media/projects/{rel.as_posix()}"


async def _save_upload(upload: UploadFile, dest: Path, allowed: set[str]) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"סוג קובץ לא נתמך: {suffix or 'ללא סיומת'}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(1 << 20):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "הקובץ גדול מדי (מקסימום 512MB)")
            fh.write(chunk)
    return dest


def _remember(project: dict[str, Any], key: str, values: list[str]) -> None:
    """שומר מה כבר הוצע, כדי ש'עוד' יביא באמת חדש."""
    seen = project.setdefault(key, [])
    for value in values:
        if value and value not in seen:
            seen.append(value)
    del seen[:-400]


# ============================================================ מידע התחלתי

@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, Any]:
    return {
        "engines": settings.engine_status(),
        "ffmpeg": editor_engine.ffmpeg_available(),
        "canvas": {"width": settings.canvas_width, "height": settings.canvas_height},
        "voice_models": voice_engine.MODELS,
        "output_formats": voice_engine.OUTPUT_FORMATS,
        "avatar_engines": avatar_engine.ENGINES,
        "resolutions": avatar_engine.RESOLUTIONS,
        "broll_models": broll_engine.model_catalog(),
        "projects": store.list_projects(),
        "library": store.library(),
    }


# ================================================================ פרויקטים

@app.get("/api/projects")
async def list_projects() -> dict[str, Any]:
    return {"projects": store.list_projects()}


@app.post("/api/projects")
async def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    return store.create((payload.get("name") or "").strip() or "סרטון ללא שם")


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = _load(project_id)
    project["jobs"] = jobs.for_project(project["id"])
    return project


@app.patch("/api/projects/{project_id}")
async def patch_project(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = _load(project_id)
    for key in ("name", "stage"):
        if key in payload:
            project[key] = payload[key]
    for key in ("brief", "script", "voice", "broll", "avatar", "captions"):
        if key in payload and isinstance(payload[key], dict):
            project[key].update(payload[key])
    return store.save(project)


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    store.delete(safe_id(project_id))
    return {"ok": True}


# =================================================== מנוע התסריט — ניסוחים

@app.post("/api/projects/{project_id}/script/sharpen")
async def script_sharpen(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """לוקח כיוון כללי ומחזיר קריאות מחודדות — כל אחת עם שורת דוגמה."""
    project = _load(project_id)
    project["brief"].update(
        {k: v for k, v in payload.items() if k in {"topic", "direction", "reference", "target_seconds"}}
    )
    store.save(project)
    return await script_engine.sharpen(project["brief"], count=int(payload.get("count", 4)))


@app.post("/api/projects/{project_id}/script/drafts")
async def script_drafts(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """מייצר תסריטים שלמים. לחיצה חוזרת תמיד מביאה חדשים."""
    project = _load(project_id)
    project["brief"].update(
        {k: v for k, v in payload.items() if k in {"topic", "direction", "reference", "target_seconds"}}
    )
    fresh = bool(payload.get("more"))
    avoid = project.get("seen_drafts", []) if fresh else []
    drafts = await script_engine.generate_drafts(
        project["brief"], count=int(payload.get("count", 6)), avoid=avoid
    )
    _remember(
        project,
        "seen_drafts",
        [" / ".join(l["text"] for l in d["lines"]) for d in drafts],
    )
    project["stage"] = "script"
    store.save(project)
    return {"drafts": drafts}


@app.post("/api/projects/{project_id}/script/options")
async def script_options(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """הכפתור המרכזי: ניסוחים חלופיים לשורה, פאנצ'ים, או פתיחות.

    kind = "line" | "punchline" | "opener"
    """
    project = _load(project_id)
    lines = project["script"]["lines"]
    kind = payload.get("kind", "line")
    count = int(payload.get("count", 8))
    instruction = (payload.get("instruction") or "").strip()
    avoid = project.get("seen_lines", []) if payload.get("more") else []

    if kind == "punchline":
        options = await script_engine.punchlines(lines, count, avoid, instruction)
    elif kind == "opener":
        options = await script_engine.openers(lines, count, avoid, instruction)
    else:
        line_id = payload.get("line_id")
        line = next((l for l in lines if l["id"] == line_id), None)
        if not line:
            raise HTTPException(400, "לא נמצאה השורה")
        options = await script_engine.line_alternatives(
            line["text"], lines, line_id, count, avoid, instruction
        )

    _remember(project, "seen_lines", [o["text"] for o in options])
    store.save(project)
    return {"options": options, "kind": kind}


@app.post("/api/projects/{project_id}/script/apply")
async def script_apply(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """שומר את התסריט — אחרי בחירת טיוטה, החלפת שורה, גרירה או עריכה ידנית."""
    project = _load(project_id)
    incoming = payload.get("lines")
    if not isinstance(incoming, list):
        raise HTTPException(400, "חסרות שורות")

    lines = []
    for item in incoming:
        text = (item.get("text") if isinstance(item, dict) else str(item)) or ""
        text = text.strip()
        if not text:
            continue
        line_id = item.get("id") if isinstance(item, dict) else None
        lines.append({"id": line_id or new_id("l_"), "text": text})

    project["script"]["lines"] = lines
    project["script"]["locked"] = bool(payload.get("locked", project["script"].get("locked")))
    store.save(project)
    return {
        "lines": lines,
        "seconds": script_engine.estimate_seconds([l["text"] for l in lines]),
        "locked": project["script"]["locked"],
    }


@app.post("/api/projects/{project_id}/script/rework")
async def script_rework(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """שכתוב חופשי של התסריט כולו, או התאמה לאורך יעד."""
    project = _load(project_id)
    lines = project["script"]["lines"]
    if not lines:
        raise HTTPException(400, "אין תסריט לשכתב")

    if payload.get("fit_seconds"):
        texts = await script_engine.fit_to_length(lines, int(payload["fit_seconds"]))
    else:
        instruction = (payload.get("instruction") or "").strip()
        if not instruction:
            raise HTTPException(400, "חסרה הוראה")
        texts = await script_engine.rework(lines, instruction, project["brief"])

    new_lines = [{"id": new_id("l_"), "text": t} for t in texts]
    project["script"]["lines"] = new_lines
    _remember(project, "seen_lines", texts)
    store.save(project)
    return {"lines": new_lines, "seconds": script_engine.estimate_seconds(texts)}


@app.post("/api/projects/{project_id}/script/broll-ideas")
async def script_broll_ideas(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = _load(project_id)
    lines = project["script"]["lines"]
    if not lines:
        raise HTTPException(400, "אין תסריט")
    ideas = await script_engine.suggest_broll(lines, int(payload.get("count", 4)))
    return {"ideas": ideas}


# ======================================================== מנוע הקול

@app.get("/api/voices")
async def api_voices() -> dict[str, Any]:
    return {"voices": await voice_engine.list_voices()}


def _take_entry(project: dict[str, Any], path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": new_id("t_"),
        "file": path.name,
        "url": _project_url(project, path),
        "at": time.time(),
        **meta,
    }


@app.post("/api/projects/{project_id}/voice/tts")
async def voice_tts(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """טקסט→קול. אחד עשר סנט לטייק — נסה כמה שבא לך."""
    project = _load(project_id)
    text = (payload.get("text") or "").strip()
    if not text:
        text = "\n".join(l["text"] for l in project["script"]["lines"])
    if not text.strip():
        raise HTTPException(400, "אין טקסט להקריא")

    voice_id = payload.get("voice_id") or project["voice"].get("voice_id")
    if not voice_id:
        raise HTTPException(400, "לא נבחר קול")

    model_id = payload.get("model_id") or project["voice"].get("model_id") or "eleven_multilingual_v2"
    vs = {**project["voice"].get("settings", {}), **(payload.get("settings") or {})}
    dest = store.project_dir(project["id"]) / "voice" / f"take_{int(time.time())}.mp3"

    await voice_engine.text_to_speech(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        voice_settings=vs,
        dest=dest,
        output_format=payload.get("output_format") or "mp3_44100_128",
        seed=payload.get("seed"),
        previous_text=payload.get("previous_text", ""),
        next_text=payload.get("next_text", ""),
        normalization=payload.get("normalization", "auto"),
    )

    take = _take_entry(
        project, dest,
        {"kind": "tts", "voice_id": voice_id, "model_id": model_id,
         "settings": voice_engine.clamp_settings(model_id, vs),
         "seed": payload.get("seed"), "text": text},
    )
    project["voice"]["takes"].insert(0, take)
    project["voice"]["voice_id"] = voice_id
    project["voice"]["model_id"] = model_id
    project["voice"]["settings"] = take["settings"]
    project["stage"] = "voice"
    store.save(project)
    return {"take": take}


@app.post("/api/projects/{project_id}/voice/compare")
async def voice_compare(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """אותו טקסט בשני מודלים, זה לצד זה. עברית רגישה — תשמע ותחליט."""
    project = _load(project_id)
    text = (payload.get("text") or "").strip() or "\n".join(
        l["text"] for l in project["script"]["lines"]
    )
    if not text.strip():
        raise HTTPException(400, "אין טקסט להקריא")
    voice_id = payload.get("voice_id") or project["voice"].get("voice_id")
    if not voice_id:
        raise HTTPException(400, "לא נבחר קול")

    models = payload.get("models") or ["eleven_v3", "eleven_multilingual_v2"]
    vs = {**project["voice"].get("settings", {}), **(payload.get("settings") or {})}
    takes = []
    for model_id in models[:3]:
        dest = store.project_dir(project["id"]) / "voice" / f"cmp_{model_id}_{int(time.time())}.mp3"
        await voice_engine.text_to_speech(
            text=text, voice_id=voice_id, model_id=model_id,
            voice_settings=vs, dest=dest,
            output_format=payload.get("output_format") or "mp3_44100_128",
        )
        take = _take_entry(
            project, dest,
            {"kind": "compare", "voice_id": voice_id, "model_id": model_id,
             "settings": voice_engine.clamp_settings(model_id, vs), "text": text},
        )
        takes.append(take)
        project["voice"]["takes"].insert(0, take)
    store.save(project)
    return {"takes": takes}


@app.post("/api/projects/{project_id}/voice/sts")
async def voice_sts(
    project_id: str,
    file: UploadFile,
    voice_id: str = Form(""),
    model_id: str = Form("eleven_multilingual_sts_v2"),
    remove_noise: str = Form("true"),
) -> dict[str, Any]:
    """קול→קול. אתה מקליט את ההפסקות והטון, המערכת מלבישה את הקול."""
    project = _load(project_id)
    target_voice = voice_id or project["voice"].get("voice_id")
    if not target_voice:
        raise HTTPException(400, "לא נבחר קול יעד")

    folder = store.project_dir(project["id"]) / "voice"
    source = await _save_upload(
        file, folder / f"rec_{int(time.time())}{Path(file.filename or '.webm').suffix.lower()}",
        AUDIO_EXTS,
    )
    dest = folder / f"sts_{int(time.time())}.mp3"
    await voice_engine.speech_to_speech(
        source=source, voice_id=target_voice,
        voice_settings=project["voice"].get("settings", {}),
        dest=dest, model_id=model_id,
        remove_noise=remove_noise == "true",
    )

    take = _take_entry(
        project, dest,
        {"kind": "sts", "voice_id": target_voice, "model_id": model_id,
         "source": source.name, "text": "\n".join(l["text"] for l in project["script"]["lines"])},
    )
    project["voice"]["takes"].insert(0, take)
    project["voice"]["voice_id"] = target_voice
    project["stage"] = "voice"
    store.save(project)
    return {"take": take}


@app.post("/api/projects/{project_id}/voice/upload")
async def voice_upload(project_id: str, file: UploadFile) -> dict[str, Any]:
    """כבר יש לך MP3 מוכן — עוקפים את ElevenLabs לגמרי."""
    project = _load(project_id)
    folder = store.project_dir(project["id"]) / "voice"
    suffix = Path(file.filename or ".mp3").suffix.lower()
    dest = await _save_upload(file, folder / f"upload_{int(time.time())}{suffix}", AUDIO_EXTS)
    take = _take_entry(
        project, dest,
        {"kind": "upload", "text": "\n".join(l["text"] for l in project["script"]["lines"])},
    )
    project["voice"]["takes"].insert(0, take)
    project["stage"] = "voice"
    store.save(project)
    return {"take": take}


@app.post("/api/projects/{project_id}/voice/choose")
async def voice_choose(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """בוחר טייק ונועל את הקול. זה מה שפותח את שלב האווטאר."""
    project = _load(project_id)
    take_id = payload.get("take_id")
    take = next((t for t in project["voice"]["takes"] if t["id"] == take_id), None)
    if not take:
        raise HTTPException(400, "לא נמצא טייק")
    project["voice"]["chosen_take"] = take_id
    project["voice"]["locked"] = bool(payload.get("locked", True))
    store.save(project)

    path = store.project_dir(project["id"]) / "voice" / take["file"]
    peaks = await editor_engine.extract_waveform(path, path.with_suffix(".peaks.json"))
    return {"chosen_take": take_id, "locked": project["voice"]["locked"], "peaks": peaks}


@app.delete("/api/projects/{project_id}/voice/takes/{take_id}")
async def voice_delete_take(project_id: str, take_id: str) -> dict[str, Any]:
    project = _load(project_id)
    take = next((t for t in project["voice"]["takes"] if t["id"] == take_id), None)
    if take:
        (store.project_dir(project["id"]) / "voice" / take["file"]).unlink(missing_ok=True)
        project["voice"]["takes"] = [t for t in project["voice"]["takes"] if t["id"] != take_id]
        if project["voice"].get("chosen_take") == take_id:
            project["voice"]["chosen_take"] = None
            project["voice"]["locked"] = False
        store.save(project)
    return {"ok": True}


def _chosen_audio(project: dict[str, Any]) -> Path:
    take_id = project["voice"].get("chosen_take")
    take = next((t for t in project["voice"]["takes"] if t["id"] == take_id), None)
    if not take:
        raise HTTPException(400, "עוד לא נבחר טייק קול")
    path = store.project_dir(project["id"]) / "voice" / take["file"]
    if not path.is_file():
        raise HTTPException(400, "קובץ הקול חסר")
    return path


# ===================================================== מנוע ה-B-roll

@app.get("/api/broll/library")
async def broll_library() -> dict[str, Any]:
    return {"library": store.library()}


@app.post("/api/broll/library")
async def broll_library_upload(file: UploadFile) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    name = Path(file.filename or f"clip{suffix}").name
    dest = store.library_path(name)
    if dest.exists():
        dest = store.library_path(f"{dest.stem}_{int(time.time())}{dest.suffix}")
    await _save_upload(file, dest, VIDEO_EXTS)
    return {"library": store.library()}


@app.delete("/api/broll/library/{name}")
async def broll_library_delete(name: str) -> dict[str, Any]:
    try:
        store.library_path(name).unlink(missing_ok=True)
    except ValueError:
        raise HTTPException(400, "שם קובץ לא תקין")
    return {"library": store.library()}


@app.post("/api/projects/{project_id}/broll/prompts")
async def broll_prompts(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """מתאר בעברית, מקבל פרומפטים טכניים באנגלית. כמה גרסאות, ו'עוד' תמיד עובד."""
    project = _load(project_id)
    idea = (payload.get("idea") or "").strip()
    if not idea:
        raise HTTPException(400, "חסר תיאור של הקטע")
    shot_id = payload.get("shot_id")
    shot = next((s for s in project["broll"]["shots"] if s["id"] == shot_id), None)
    avoid = [p["prompt"] for p in (shot or {}).get("prompt_options", [])] if payload.get("more") else []
    options = await broll_engine.prompt_options(idea, int(payload.get("count", 4)), avoid)

    if shot is not None:
        shot.setdefault("prompt_options", []).extend(options)
        shot["idea"] = idea
        store.save(project)
    return {"options": options}


@app.post("/api/projects/{project_id}/broll/shots")
async def broll_add_shot(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = _load(project_id)
    shot = {
        "id": new_id("s_"),
        "idea": (payload.get("idea") or "").strip(),
        "prompt": (payload.get("prompt") or "").strip(),
        "prompt_options": [],
        "images": [],
        "chosen_image": None,
        "motion_prompt": "",
        "video": None,
        "source": payload.get("source", "generated"),
        "file": payload.get("file"),
        "start": float(payload.get("start", 0.0)),
        "duration": float(payload.get("duration", 3.0)),
        "mode": payload.get("mode", "full"),
        "scale": float(payload.get("scale", 0.42)),
        "x": float(payload.get("x", 0.05)),
        "y": float(payload.get("y", 0.08)),
        "audio_mix": float(payload.get("audio_mix", 0.0)),
    }
    project["broll"]["shots"].append(shot)
    project["stage"] = "broll"
    store.save(project)
    return {"shot": shot}


@app.patch("/api/projects/{project_id}/broll/shots/{shot_id}")
async def broll_update_shot(project_id: str, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project = _load(project_id)
    shot = next((s for s in project["broll"]["shots"] if s["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, "קטע לא נמצא")
    for key in ("idea", "prompt", "motion_prompt", "chosen_image", "source", "file",
                "start", "duration", "mode", "scale", "x", "y", "audio_mix"):
        if key in payload:
            shot[key] = payload[key]
    store.save(project)
    return {"shot": shot}


@app.delete("/api/projects/{project_id}/broll/shots/{shot_id}")
async def broll_delete_shot(project_id: str, shot_id: str) -> dict[str, Any]:
    project = _load(project_id)
    project["broll"]["shots"] = [s for s in project["broll"]["shots"] if s["id"] != shot_id]
    store.save(project)
    return {"ok": True}


@app.post("/api/projects/{project_id}/broll/shots/{shot_id}/images")
async def broll_images(project_id: str, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """השלב הזול. עולה אגורות — כאן מותר לנסות עשר פעמים."""
    project = _load(project_id)
    shot = next((s for s in project["broll"]["shots"] if s["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, "קטע לא נמצא")
    prompt = (payload.get("prompt") or shot.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "חסר פרומפט")

    folder = store.project_dir(project["id"]) / "broll" / shot_id
    folder.mkdir(parents=True, exist_ok=True)

    def factory(job: Job):
        async def run():
            images = await broll_engine.generate_images(
                prompt=prompt,
                dest_dir=folder,
                model_id=payload.get("model_id") or "fal-ai/flux/schnell",
                count=int(payload.get("count", 4)),
                on_progress=lambda p, m: job.update(p, m),
            )
            fresh = _load(project_id)
            target = next((s for s in fresh["broll"]["shots"] if s["id"] == shot_id), None)
            if target is not None:
                for image in images:
                    image["url"] = f"/media/projects/{fresh['id']}/broll/{shot_id}/{image['file']}"
                    target["images"].append(image)
                target["prompt"] = prompt
                store.save(fresh)
            return {"images": images}
        return run()

    job = jobs.start("broll_images", project["id"], "מייצר תמונות", factory)
    return {"job": job.snapshot()}


@app.post("/api/projects/{project_id}/broll/shots/{shot_id}/animate")
async def broll_animate(project_id: str, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """השלב היקר. רץ פעם אחת, על תמונה שכבר אישרת."""
    project = _load(project_id)
    shot = next((s for s in project["broll"]["shots"] if s["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, "קטע לא נמצא")
    image_name = payload.get("image") or shot.get("chosen_image")
    if not image_name:
        raise HTTPException(400, "לא נבחרה תמונה. בחר פריים לפני שמשלמים על וידאו.")

    folder = store.project_dir(project["id"]) / "broll" / shot_id
    image_path = folder / Path(image_name).name
    if not image_path.is_file():
        raise HTTPException(400, "התמונה לא נמצאה")

    model_id = payload.get("model_id") or "fal-ai/kling-video/v2/master/image-to-video"
    seconds = int(payload.get("seconds") or max(3, round(shot.get("duration", 5))))
    motion = (payload.get("motion_prompt") or shot.get("motion_prompt") or "slow subtle camera push in").strip()
    dest = folder / f"clip_{int(time.time())}.mp4"

    def factory(job: Job):
        async def run():
            job.update(0.05, f"שולח ל-{model_id}")
            await broll_engine.animate_image(
                image_path=image_path, motion_prompt=motion, dest=dest,
                model_id=model_id, duration_seconds=seconds,
                on_progress=lambda p, m: job.update(p, m),
            )
            info = await editor_engine.probe(dest) if editor_engine.ffmpeg_available() else {"duration": seconds}
            fresh = _load(project_id)
            target = next((s for s in fresh["broll"]["shots"] if s["id"] == shot_id), None)
            if target is not None:
                target["video"] = dest.name
                target["file"] = str(dest)
                target["chosen_image"] = image_path.name
                target["motion_prompt"] = motion
                target["source"] = "generated"
                target["clip_seconds"] = info.get("duration") or seconds
                target["url"] = f"/media/projects/{fresh['id']}/broll/{shot_id}/{dest.name}"
                store.save(fresh)
            return {
                "video": dest.name,
                "url": f"/media/projects/{project['id']}/broll/{shot_id}/{dest.name}",
                "cost": broll_engine.estimate_cost(model_id, seconds),
            }
        return run()

    job = jobs.start("broll_animate", project["id"], "מנפיש (זה השלב שעולה כסף)", factory)
    return {"job": job.snapshot(), "estimated_cost": broll_engine.estimate_cost(model_id, seconds)}


# ======================================================= מנוע האווטאר

@app.get("/api/avatars")
async def api_avatars() -> dict[str, Any]:
    return await avatar_engine.list_avatars()


@app.post("/api/projects/{project_id}/avatar/render")
async def avatar_render(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """הכפתור האדום. נפתח רק אחרי שהקול נעול."""
    project = _load(project_id)
    if not project["voice"].get("locked"):
        raise HTTPException(400, "נעל קודם את הקול. רינדור אווטאר עולה כסף אמיתי.")
    audio_path = _chosen_audio(project)

    avatar_id = payload.get("avatar_id") or project["avatar"].get("avatar_id")
    if not avatar_id:
        raise HTTPException(400, "לא נבחר אווטאר")

    kind = payload.get("kind", "avatar")
    engine = payload.get("engine") or project["avatar"].get("engine") or "avatar_iv"
    resolution = payload.get("resolution") or project["avatar"].get("resolution") or "1080p"
    motion_prompt = (payload.get("motion_prompt") or "").strip()
    background = payload.get("background")
    dest = store.project_dir(project["id"]) / "avatar" / "avatar.mp4"

    def factory(job: Job):
        async def run():
            job.update(0.05, "מעלה את הקול ל-HeyGen")
            asset_id = await avatar_engine.upload_audio(audio_path)

            job.update(0.12, "פותח רינדור")
            video_id = await avatar_engine.create_video(
                avatar_id=avatar_id, audio_asset_id=asset_id, kind=kind,
                engine=engine, resolution=resolution,
                background=background, motion_prompt=motion_prompt,
                title=project.get("name", ""),
            )

            fresh = _load(project_id)
            fresh["avatar"].update({"video_id": video_id, "avatar_id": avatar_id,
                                    "engine": engine, "resolution": resolution})
            store.save(fresh)

            result = await avatar_engine.wait_for_video(
                video_id, on_progress=lambda p, m: job.update(0.12 + p * 0.75, m)
            )

            job.update(0.9, "מוריד את הסרטון")
            await avatar_engine.download_video(result["url"], dest)
            info = await editor_engine.probe(dest) if editor_engine.ffmpeg_available() else {}

            fresh = _load(project_id)
            fresh["avatar"].update({
                "file": dest.name,
                "url": f"/media/projects/{fresh['id']}/avatar/{dest.name}",
                "duration": info.get("duration") or result.get("duration"),
                "thumbnail": result.get("thumbnail"),
            })
            fresh["stage"] = "captions"
            store.save(fresh)
            return {
                "file": dest.name,
                "url": f"/media/projects/{project['id']}/avatar/{dest.name}",
                "duration": fresh["avatar"]["duration"],
            }
        return run()

    job = jobs.start("avatar", project["id"], "HeyGen מרנדר", factory)
    return {"job": job.snapshot()}


@app.post("/api/projects/{project_id}/avatar/upload")
async def avatar_upload(project_id: str, file: UploadFile) -> dict[str, Any]:
    """כבר יש לך סרטון אווטאר — עוקפים את HeyGen."""
    project = _load(project_id)
    folder = store.project_dir(project["id"]) / "avatar"
    dest = await _save_upload(file, folder / "avatar.mp4", VIDEO_EXTS)
    info = await editor_engine.probe(dest) if editor_engine.ffmpeg_available() else {}
    project["avatar"].update({
        "file": dest.name,
        "url": f"/media/projects/{project['id']}/avatar/{dest.name}",
        "duration": info.get("duration"),
    })
    project["stage"] = "captions"
    store.save(project)
    return {"avatar": project["avatar"]}


def _avatar_path(project: dict[str, Any]) -> Path:
    name = project["avatar"].get("file")
    if not name:
        raise HTTPException(400, "עוד אין סרטון אווטאר")
    path = store.project_dir(project["id"]) / "avatar" / name
    if not path.is_file():
        raise HTTPException(400, "קובץ האווטאר חסר")
    return path


# ======================================================== מנוע הכתוביות

@app.post("/api/projects/{project_id}/captions/build")
async def captions_build(project_id: str) -> dict[str, Any]:
    """מתזמן את מילות התסריט על האודיו. המילים מהתסריט — התזמון מהקול."""
    project = _load(project_id)
    audio_path = _chosen_audio(project)

    def factory(job: Job):
        async def run():
            job.update(0.2, "מתזמן מילים")
            words = await captions_engine.build_words(audio_path, project["script"]["lines"])
            fresh = _load(project_id)
            fresh["captions"]["words"] = words
            fresh["stage"] = "captions"
            store.save(fresh)
            job.update(0.95, f"{len(words)} מילים")
            return {"words": words}
        return run()

    job = jobs.start("captions", project["id"], "בונה כתוביות", factory)
    return {"job": job.snapshot()}


@app.patch("/api/projects/{project_id}/captions")
async def captions_patch(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """תיקון ידני של תזמון או שינוי סגנון."""
    project = _load(project_id)
    if isinstance(payload.get("words"), list):
        project["captions"]["words"] = [
            {"w": str(w.get("w", "")), "start": float(w.get("start", 0)), "end": float(w.get("end", 0))}
            for w in payload["words"]
        ]
    if isinstance(payload.get("style"), dict):
        project["captions"]["style"].update(payload["style"])
    if "enabled" in payload:
        project["captions"]["enabled"] = bool(payload["enabled"])
    store.save(project)
    return {"captions": project["captions"]}


@app.get("/api/projects/{project_id}/captions/srt")
async def captions_srt(project_id: str):
    project = _load(project_id)
    words = project["captions"].get("words") or []
    if not words:
        raise HTTPException(400, "אין כתוביות")
    dest = store.project_dir(project["id"]) / "export" / "captions.srt"
    captions_engine.write_srt(words, dest)
    return FileResponse(dest, filename=f"{project['name']}.srt", media_type="text/plain")


# ============================================================ עריכה וייצוא

def _shots_for_render(project: dict[str, Any]) -> list[dict[str, Any]]:
    """הופך את הקטעים למה ש-FFmpeg צריך, כולל פתרון נתיבים."""
    out = []
    for shot in project["broll"]["shots"]:
        if shot.get("source") == "library" and shot.get("file"):
            try:
                path = store.library_path(shot["file"])
            except ValueError:
                continue
        elif shot.get("file"):
            path = Path(shot["file"])
        else:
            continue
        if not path.is_file():
            continue
        out.append({**shot, "file": str(path)})
    return out


def _ass_for(project: dict[str, Any]) -> Path | None:
    caps = project.get("captions") or {}
    words = caps.get("words") or []
    if not caps.get("enabled") or not words:
        return None
    dest = store.project_dir(project["id"]) / "export" / "captions.ass"
    return captions_engine.write_ass(
        words, dest, caps.get("style", {}), settings.canvas_width, settings.canvas_height
    )


def _render_job(project_id: str, final: bool):
    project = _load(project_id)
    avatar_path = _avatar_path(project)
    shots = _shots_for_render(project)
    ass_file = _ass_for(project)

    folder = store.project_dir(project["id"]) / "export"
    dest = folder / ("final.mp4" if final else "preview.mp4")

    def factory(job: Job):
        async def run():
            runner = editor_engine.render if final else editor_engine.make_preview
            await runner(
                avatar_path, shots, dest,
                ass_file=ass_file,
                on_progress=lambda p, m: job.update(p, m),
            )
            url = f"/media/projects/{project['id']}/export/{dest.name}"
            if final:
                copy = settings.exports_dir / f"{project['id']}_{int(time.time())}.mp4"
                shutil.copy2(dest, copy)
                fresh = _load(project_id)
                fresh["export"] = {"file": dest.name, "url": url, "at": time.time(),
                                   "download": f"/media/exports/{copy.name}"}
                fresh["stage"] = "export"
                store.save(fresh)
                return {"url": url, "download": f"/media/exports/{copy.name}"}
            return {"url": f"{url}?t={int(time.time())}"}
        return run()

    label = "מרנדר סופי" if final else "תצוגה מקדימה"
    return jobs.start("render" if final else "preview", project["id"], label, factory)


@app.post("/api/projects/{project_id}/preview")
async def preview(project_id: str) -> dict[str, Any]:
    return {"job": _render_job(project_id, final=False).snapshot()}


@app.post("/api/projects/{project_id}/export")
async def export(project_id: str) -> dict[str, Any]:
    return {"job": _render_job(project_id, final=True).snapshot()}


@app.get("/api/projects/{project_id}/waveform")
async def waveform(project_id: str) -> dict[str, Any]:
    """צורת הגל לטיימליין. נלקח מהאווטאר אם קיים, אחרת מהקול."""
    project = _load(project_id)
    try:
        source = _avatar_path(project)
    except HTTPException:
        source = _chosen_audio(project)
    cache = source.with_suffix(".peaks.json")
    if cache.is_file():
        try:
            return {"peaks": json.loads(cache.read_text(encoding="utf-8"))}
        except (json.JSONDecodeError, OSError):
            pass
    peaks = await editor_engine.extract_waveform(source, cache)
    info = await editor_engine.probe(source) if editor_engine.ffmpeg_available() else {}
    return {"peaks": peaks, "duration": info.get("duration")}


# ==================================================================== עבודות

@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "עבודה לא נמצאה")
    return job.snapshot()


@app.post("/api/jobs/{job_id}/cancel")
async def job_cancel(job_id: str) -> dict[str, Any]:
    return {"cancelled": jobs.cancel(job_id)}


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str):
    """זרם התקדמות חי. אפשר לסגור את הלשונית ולחזור — העבודה ממשיכה."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "עבודה לא נמצאה")

    async def events():
        queue = job.subscribe()
        try:
            while True:
                try:
                    snapshot = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                if snapshot["status"] in {"done", "error", "cancelled"}:
                    break
        finally:
            job.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
