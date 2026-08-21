"""מנוע האווטאר — HeyGen.

זה השלב היחיד בצינור שעולה כסף אמיתי בכל לחיצה, ולכן הוא האחרון
שנפתח: הקול חייב להיות נעול לפני שהכפתור כאן מגיב.
"""
from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, Callable

import httpx

from ..config import settings

API = "https://api.heygen.com"
UPLOAD = "https://upload.heygen.com"
TIMEOUT = httpx.Timeout(120.0, connect=15.0)

ENGINES = [
    {
        "id": "avatar_iv",
        "name": "Avatar IV",
        "he": "ברירת המחדל. עובד עם כל האווטארים, מחיר סטנדרטי.",
    },
    {
        "id": "avatar_v",
        "name": "Avatar V",
        "he": "האיכותי ביותר, עם תנועת גוף אמיתית. יקר יותר, ולא כל אווטאר תומך.",
    },
    {
        "id": "avatar_iii",
        "name": "Avatar III",
        "he": "הוותיק. הכי זול — בערך רבע מהמחיר. מספיק לטיוטות.",
    },
]

RESOLUTIONS = [
    {"id": "720p", "he": "מספיק לטיקטוק. הכי זול ומהיר."},
    {"id": "1080p", "he": "ברירת המחדל. חד ונקי לכל פלטפורמה."},
    {"id": "4k", "he": "רק אם הלקוח ביקש. יקר ואיטי, ובטלפון לא רואים הבדל."},
]


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    if not settings.heygen_api_key:
        raise RuntimeError("חסר HEYGEN_API_KEY — מנוע האווטאר מנוטרל")
    headers = {"X-Api-Key": settings.heygen_api_key}
    if extra:
        headers.update(extra)
    return headers


def _raise_for(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:400]
    try:
        body = response.json()
        err = body.get("error") or body.get("message") or body
        detail = err.get("message") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        pass
    raise RuntimeError(f"HeyGen ({response.status_code}): {detail}")


def _payload_error(body: dict[str, Any]) -> None:
    """HeyGen מחזיר גם שגיאות בתוך 200. צריך לבדוק את הגוף."""
    err = body.get("error")
    if err:
        message = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"HeyGen: {message}")


async def list_avatars() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(f"{API}/v2/avatars", headers=_headers())
        _raise_for(response)
    body = response.json()
    _payload_error(body)
    data = body.get("data") or {}

    avatars = [
        {
            "avatar_id": a.get("avatar_id"),
            "name": a.get("avatar_name") or a.get("name"),
            "preview": a.get("preview_image_url"),
            "gender": a.get("gender"),
            "kind": "avatar",
        }
        for a in (data.get("avatars") or [])
        if a.get("avatar_id")
    ]
    talking_photos = [
        {
            "avatar_id": p.get("talking_photo_id"),
            "name": p.get("talking_photo_name") or "תמונה מדברת",
            "preview": p.get("preview_image_url"),
            "gender": None,
            "kind": "talking_photo",
        }
        for p in (data.get("talking_photos") or [])
        if p.get("talking_photo_id")
    ]
    return {"avatars": avatars, "talking_photos": talking_photos}


async def upload_audio(path: Path) -> str:
    """מעלה את ה-MP3 ומחזיר asset_id לשימוש ביצירת הסרטון."""
    mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    raw = path.read_bytes()

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
        # הנתיב הוותיק והיציב — גוף גולמי עם סוג התוכן בכותרת
        response = await client.post(
            f"{UPLOAD}/v1/asset",
            headers=_headers({"Content-Type": mime}),
            content=raw,
        )
        if response.status_code == 404:
            # נפילה לנתיב החדש אם הישן הוסר
            with path.open("rb") as fh:
                response = await client.post(
                    f"{API}/v3/assets",
                    headers=_headers(),
                    files={"file": (path.name, fh, mime)},
                )
        _raise_for(response)

    body = response.json()
    _payload_error(body)
    data = body.get("data") or body
    asset_id = data.get("asset_id") or data.get("id")
    if not asset_id:
        raise RuntimeError("HeyGen לא החזיר מזהה קובץ")
    return asset_id


async def create_video(
    avatar_id: str,
    audio_asset_id: str,
    *,
    kind: str = "avatar",
    engine: str = "avatar_iv",
    resolution: str = "1080p",
    width: int | None = None,
    height: int | None = None,
    background: dict[str, Any] | None = None,
    motion_prompt: str = "",
    title: str = "",
) -> str:
    character: dict[str, Any] = (
        {"type": "talking_photo", "talking_photo_id": avatar_id}
        if kind == "talking_photo"
        else {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"}
    )
    if motion_prompt.strip():
        character["motion_prompt"] = motion_prompt.strip()

    video_input: dict[str, Any] = {
        "character": character,
        "voice": {"type": "audio", "audio_asset_id": audio_asset_id},
    }
    if background:
        video_input["background"] = background

    payload: dict[str, Any] = {
        "video_inputs": [video_input],
        "dimension": {
            "width": width or settings.canvas_width,
            "height": height or settings.canvas_height,
        },
    }
    if engine:
        payload["engine"] = {"type": engine}
    if resolution:
        payload["resolution"] = resolution
    if title:
        payload["title"] = title[:120]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{API}/v2/video/generate",
            headers=_headers({"Content-Type": "application/json"}),
            json=payload,
        )
        _raise_for(response)

    body = response.json()
    _payload_error(body)
    video_id = (body.get("data") or {}).get("video_id")
    if not video_id:
        raise RuntimeError("HeyGen לא החזיר מזהה סרטון")
    return video_id


async def wait_for_video(
    video_id: str,
    on_progress: Callable[[float, str], None] | None = None,
    poll_seconds: float = 6.0,
    max_wait: float = 2400.0,
) -> dict[str, Any]:
    """מושך את הסטטוס עד שהסרטון מוכן. עד 40 דקות."""
    waited = 0.0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while waited < max_wait:
            response = await client.get(
                f"{API}/v1/video_status.get",
                headers=_headers(),
                params={"video_id": video_id},
            )
            _raise_for(response)
            body = response.json()
            _payload_error(body)
            data = body.get("data") or {}
            status = data.get("status")

            if status == "completed":
                url = data.get("video_url")
                if not url:
                    raise RuntimeError("HeyGen סיים אבל לא נתן קישור להורדה")
                return {
                    "url": url,
                    "duration": data.get("duration"),
                    "thumbnail": data.get("thumbnail_url"),
                    "captions": data.get("caption_url"),
                }
            if status == "failed":
                err = data.get("error") or {}
                message = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"HeyGen נכשל: {message or 'ללא פירוט'}")

            if on_progress:
                # הרינדור לוקח בדרך כלל 2 עד 10 דקות
                on_progress(min(0.92, waited / 420.0), f"HeyGen מרנדר ({status or 'ממתין'})")
            await asyncio.sleep(poll_seconds)
            waited += poll_seconds
    raise RuntimeError("HeyGen לא סיים בזמן. הסרטון אולי עדיין נוצר — בדוק בלוח שלהם.")


async def download_video(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=15.0)) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in response.aiter_bytes(1 << 16):
                    fh.write(chunk)
    return dest
