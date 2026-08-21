"""מנוע הקול — ElevenLabs.

שלוש דרכים להגיע ל-MP3:
  1. טקסט→קול   — מקלידים, בוחרים קול
  2. קול→קול     — מקליטים את עצמך, המערכת ממירה. הכי מדויק להפסקות ולטון
  3. העלאה       — כבר יש לך קובץ מוכן
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import settings

BASE = "https://api.elevenlabs.io/v1"
TIMEOUT = httpx.Timeout(300.0, connect=15.0)

# המודלים שנחשפים בממשק. עברית רגישה — לכן שניהם זמינים ואפשר להשוות.
MODELS = [
    {
        "id": "eleven_v3",
        "name": "Eleven v3",
        "he": "המשחקי והחדש. מצוין לרגש ולדרמה, אבל בעברית לפעמים משתולל.",
        "stability_steps": [0.0, 0.5, 1.0],
    },
    {
        "id": "eleven_multilingual_v2",
        "name": "Multilingual v2",
        "he": "הוותיק והיציב. לרוב הכי נקי בעברית — ולכן הכי טוב לדדפאן.",
        "stability_steps": None,
    },
    {
        "id": "eleven_turbo_v2_5",
        "name": "Turbo v2.5",
        "he": "מהיר וחצי מחיר. טוב לבדיקות מהירות של ניסוח.",
        "stability_steps": None,
    },
    {
        "id": "eleven_flash_v2_5",
        "name": "Flash v2.5",
        "he": "הכי מהיר והכי זול. איכות נמוכה יותר — לטיוטות בלבד.",
        "stability_steps": None,
    },
]

OUTPUT_FORMATS = [
    {"id": "mp3_44100_128", "he": "רגיל — 128k. ברירת המחדל, מספיק לכל דבר."},
    {"id": "mp3_44100_192", "he": "גבוה — 192k. דורש מנוי בתשלום."},
    {"id": "mp3_44100_64", "he": "חסכוני — 64k."},
]


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("חסר ELEVENLABS_API_KEY — מנוע הקול מנוטרל")
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    if extra:
        headers.update(extra)
    return headers


def _raise_for(response: httpx.Response) -> None:
    """הופך שגיאת API להודעה שאפשר להראות למשתמש."""
    if response.status_code < 400:
        return
    detail = ""
    try:
        body = response.json()
        detail = body.get("detail") or body
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("status") or str(detail)
    except (ValueError, AttributeError):
        detail = response.text[:400]
    raise RuntimeError(f"ElevenLabs ({response.status_code}): {detail}")


def clamp_settings(model_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """מיישר את ההגדרות לטווח החוקי. ל-v3 יש אילוץ מיוחד על היציבות."""
    def _f(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    out = {
        "stability": _f("stability", 0.5, 0.0, 1.0),
        "similarity_boost": _f("similarity_boost", 0.75, 0.0, 1.0),
        "style": _f("style", 0.0, 0.0, 1.0),
        "use_speaker_boost": bool(raw.get("use_speaker_boost", True)),
        "speed": _f("speed", 1.0, 0.25, 4.0),
    }
    if model_id == "eleven_v3":
        # v3 מקבל רק שלושה ערכי יציבות. מעגלים לקרוב ביותר.
        out["stability"] = min([0.0, 0.5, 1.0], key=lambda s: abs(s - out["stability"]))
    return out


async def list_voices() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(f"{BASE}/voices", headers=_headers())
        _raise_for(response)
    voices = []
    for v in response.json().get("voices", []):
        voices.append(
            {
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "preview_url": v.get("preview_url"),
                "labels": v.get("labels") or {},
            }
        )
    voices.sort(key=lambda v: (v["category"] != "cloned", v["name"] or ""))
    return voices


async def text_to_speech(
    text: str,
    voice_id: str,
    model_id: str,
    voice_settings: dict[str, Any],
    dest: Path,
    output_format: str = "mp3_44100_128",
    seed: int | None = None,
    previous_text: str = "",
    next_text: str = "",
    normalization: str = "auto",
) -> Path:
    payload: dict[str, Any] = {
        "text": text,
        "model_id": model_id,
        "voice_settings": clamp_settings(model_id, voice_settings),
        "apply_text_normalization": normalization,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    if previous_text.strip():
        payload["previous_text"] = previous_text
    if next_text.strip():
        payload["next_text"] = next_text

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{BASE}/text-to-speech/{voice_id}",
            headers=_headers({"Content-Type": "application/json", "Accept": "audio/mpeg"}),
            params={"output_format": output_format},
            json=payload,
        )
        _raise_for(response)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
    return dest


async def speech_to_speech(
    source: Path,
    voice_id: str,
    voice_settings: dict[str, Any],
    dest: Path,
    model_id: str = "eleven_multilingual_sts_v2",
    output_format: str = "mp3_44100_128",
    seed: int | None = None,
    remove_noise: bool = True,
) -> Path:
    """ההקלטה שלך, הקול שלך — ההפסקות והטון נשמרים בדיוק כפי שאמרת."""
    import json as _json

    data: dict[str, Any] = {
        "model_id": model_id,
        "voice_settings": _json.dumps(clamp_settings(model_id, voice_settings)),
        "remove_background_noise": "true" if remove_noise else "false",
    }
    if seed is not None:
        data["seed"] = str(int(seed))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        with source.open("rb") as fh:
            response = await client.post(
                f"{BASE}/speech-to-speech/{voice_id}",
                headers=_headers({"Accept": "audio/mpeg"}),
                params={"output_format": output_format},
                data=data,
                files={"audio": (source.name, fh, "application/octet-stream")},
            )
        _raise_for(response)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
    return dest


# ------------------------------------------------------------ תזמון מילים

async def forced_alignment(audio: Path, text: str) -> list[dict[str, Any]] | None:
    """יישור מדויק: יודעים מה נאמר, מחפשים רק מתי.

    עברית לא ברשימת השפות הנתמכות רשמית, לכן זה עלול להיכשל —
    ואז נופלים ל-Scribe. מחזיר None אם לא הצליח.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            with audio.open("rb") as fh:
                response = await client.post(
                    f"{BASE}/forced-alignment",
                    headers=_headers(),
                    data={"text": text},
                    files={"file": (audio.name, fh, "application/octet-stream")},
                )
        if response.status_code >= 400:
            return None
        words = response.json().get("words") or []
        out = [
            {
                "w": w.get("text", "").strip(),
                "start": float(w.get("start", 0.0)),
                "end": float(w.get("end", 0.0)),
            }
            for w in words
            if w.get("text", "").strip()
        ]
        return out or None
    except (httpx.HTTPError, ValueError, KeyError, RuntimeError):
        return None


async def transcribe_words(audio: Path, language_code: str = "heb") -> list[dict[str, Any]]:
    """Scribe — תמלול עם חותמת זמן לכל מילה."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        with audio.open("rb") as fh:
            response = await client.post(
                f"{BASE}/speech-to-text",
                headers=_headers(),
                data={
                    "model_id": "scribe_v1",
                    "language_code": language_code,
                    "timestamps_granularity": "word",
                    "diarize": "false",
                },
                files={"file": (audio.name, fh, "application/octet-stream")},
            )
        _raise_for(response)
    words = response.json().get("words") or []
    return [
        {
            "w": w.get("text", "").strip(),
            "start": float(w.get("start", 0.0)),
            "end": float(w.get("end", 0.0)),
        }
        for w in words
        if w.get("type", "word") == "word" and w.get("text", "").strip()
    ]
