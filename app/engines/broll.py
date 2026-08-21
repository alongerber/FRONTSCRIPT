"""מנוע ה-B-roll — fal.ai.

העיקרון הכלכלי של המסך הזה: **תמונה עולה אגורות, וידאו עולה דולרים.**
לכן מתעקשים על שני שלבים — משחקים בתמונות עד שהפריים מדויק, ורק אז
מנפישים פעם אחת. זה מוריד עשרה ניסיונות וידאו לאחד או שניים.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import anthropic
import httpx

from ..config import settings

QUEUE = "https://queue.fal.run"
TIMEOUT = httpx.Timeout(180.0, connect=15.0)

# --- מודלים לתמונה. זה השלב הזול, כאן מותר לנסות עשר פעמים. -------------
IMAGE_MODELS = [
    {
        "id": "fal-ai/flux/schnell",
        "name": "FLUX Schnell",
        "he": "הכי מהיר והכי זול — בערך 0.3 אגורות לתמונה. כאן מתחילים תמיד.",
        "tier": "cheap",
    },
    {
        "id": "fal-ai/flux/dev",
        "name": "FLUX Dev",
        "he": "איכות טובה יותר, עדיין זול. כשהקומפוזיציה כבר נכונה ורוצים ליטוש.",
        "tier": "mid",
    },
    {
        "id": "fal-ai/flux-pro/v1.1-ultra",
        "name": "FLUX Pro Ultra",
        "he": "הכי חד. לפריים המרכזי של הסרטון.",
        "tier": "max",
    },
]

# --- מודלים לווידאו. זה השלב היקר. שימו לב למחיר לפני שלוחצים. ----------
VIDEO_MODELS = [
    {
        "id": "fal-ai/wan-25-preview/image-to-video",
        "name": "Wan 2.5",
        "he": "בערך $0.05 לשנייה. מצוין לקטעי רקע ולתנועות פשוטות.",
        "per_second": 0.05,
        "tier": "cheap",
    },
    {
        "id": "fal-ai/kling-video/v2/master/image-to-video",
        "name": "Kling 2 Master",
        "he": "בערך $0.10 לשנייה. תנועה חלקה ואמינה — הבחירה הכי מאוזנת.",
        "per_second": 0.10,
        "tier": "mid",
    },
    {
        "id": "fal-ai/veo3/fast/image-to-video",
        "name": "Veo 3 Fast",
        "he": "בערך $0.15 לשנייה. איכות גוגל במחיר חצי.",
        "per_second": 0.15,
        "tier": "high",
    },
    {
        "id": "fal-ai/veo3/image-to-video",
        "name": "Veo 3",
        "he": "בערך $0.40 לשנייה — היקר ביותר. שמור אותו לקטע שנושא את הסרטון.",
        "per_second": 0.40,
        "tier": "max",
    },
]


def model_catalog() -> dict[str, Any]:
    return {"images": IMAGE_MODELS, "videos": VIDEO_MODELS}


def estimate_cost(model_id: str, seconds: float) -> float:
    for m in VIDEO_MODELS:
        if m["id"] == model_id:
            return round(m["per_second"] * max(1.0, seconds), 3)
    return 0.0


def _headers() -> dict[str, str]:
    if not settings.fal_key:
        raise RuntimeError("חסר FAL_KEY — מנוע ה-B-roll מנוטרל")
    return {"Authorization": f"Key {settings.fal_key}", "Content-Type": "application/json"}


def _raise_for(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:500]
    try:
        body = response.json()
        detail = body.get("detail") or body.get("error") or body
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)[:500]
    except ValueError:
        pass
    if response.status_code == 404:
        detail = (
            f"{detail}\nהמודל אולי שינה שם ב-fal.ai. בדוק ברשימה ב-fal.ai/models "
            "ועדכן את המזהה בהגדרות."
        )
    raise RuntimeError(f"fal.ai ({response.status_code}): {detail}")


async def _run(
    model_id: str,
    payload: dict[str, Any],
    on_progress: Callable[[float, str], None] | None = None,
    poll_seconds: float = 2.0,
    max_wait: float = 900.0,
) -> dict[str, Any]:
    """שולח לתור של fal ומחכה לתוצאה."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        submit = await client.post(f"{QUEUE}/{model_id}", headers=_headers(), json=payload)
        _raise_for(submit)
        queued = submit.json()
        status_url = queued.get("status_url")
        response_url = queued.get("response_url")
        if not status_url or not response_url:
            raise RuntimeError("fal.ai לא החזיר כתובת מעקב")

        waited = 0.0
        while waited < max_wait:
            await asyncio.sleep(poll_seconds)
            waited += poll_seconds
            check = await client.get(status_url, headers=_headers())
            _raise_for(check)
            state = check.json()
            status = state.get("status")
            if status == "COMPLETED":
                final = await client.get(response_url, headers=_headers())
                _raise_for(final)
                return final.json()
            if status in {"FAILED", "ERROR"}:
                raise RuntimeError(f"fal.ai נכשל: {json.dumps(state, ensure_ascii=False)[:400]}")
            if on_progress:
                # ההתקדמות לא ידועה מראש, אז מתקרבים לתשעים אחוז אסימפטוטית
                on_progress(min(0.9, waited / max(30.0, max_wait * 0.25)), "מייצר")
    raise RuntimeError("fal.ai לא סיים בזמן")


async def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in response.aiter_bytes(1 << 16):
                    fh.write(chunk)
    return dest


# ------------------------------------------------------- בניית הפרומפט הקליני

_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "פרומפט טכני מלא באנגלית"},
                    "he": {"type": "string", "description": "מה רואים, במשפט בעברית"},
                },
                "required": ["prompt", "he"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}

_PROMPT_SYSTEM = """You write prompts for image generation models, for B-roll
inserts in short vertical comedy videos.

Rules:
- Output English only in the `prompt` field. Models understand English best.
- Be clinical and concrete: subject, action, setting, camera angle, lens,
  lighting, colour palette, film stock or render style, mood.
- Vertical 9:16 framing. Say so.
- No text or letters in the image — generators render them as garbage.
- Mundane and slightly off beats spectacular. These are comedy inserts, not
  stock footage. Fluorescent lighting, cheap tiles, an ugly plastic chair,
  a slightly wrong angle — that is the register.
- Each option must differ in a real way: different angle, different distance,
  different time of day, different thing in frame. Not synonyms.
"""


async def prompt_options(
    idea_he: str, count: int = 4, avoid: list[str] | None = None
) -> list[dict[str, str]]:
    """הופך תיאור בעברית לפרומפטים טכניים באנגלית — כמה גרסאות לבחירה."""
    if not settings.anthropic_api_key:
        # בלי מנוע התסריט עדיין אפשר לעבוד, רק בלי תרגום אוטומטי
        return [{"prompt": idea_he, "he": idea_he}]

    avoid_block = ""
    clean = [a for a in (avoid or []) if a.strip()][-40:]
    if clean:
        listed = "\n".join(f"- {a}" for a in clean)
        avoid_block = f"\n\nAlready shown and rejected — do not repeat or paraphrase:\n{listed}"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.script_model,
        max_tokens=3000,
        system=_PROMPT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"The shot, described in Hebrew by the director:\n{idea_he}\n\n"
                    f"Write {count} genuinely different prompts for it.{avoid_block}"
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": _PROMPT_SCHEMA}},
    )
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    data = json.loads(text)
    return [
        {"prompt": o["prompt"].strip(), "he": o.get("he", "").strip()}
        for o in data.get("options", [])
        if o.get("prompt", "").strip()
    ]


# ------------------------------------------------------------------ תמונות

async def generate_images(
    prompt: str,
    dest_dir: Path,
    model_id: str = "fal-ai/flux/schnell",
    count: int = 4,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[dict[str, Any]]:
    """השלב הזול. מייצר כמה תמונות בבת אחת כדי לבחור פריים."""
    payload = {
        "prompt": prompt,
        "num_images": max(1, min(4, count)),
        "image_size": {"width": settings.canvas_width, "height": settings.canvas_height},
        "enable_safety_checker": True,
    }
    result = await _run(model_id, payload, on_progress)
    out = []
    for index, image in enumerate(result.get("images", [])):
        url = image.get("url")
        if not url:
            continue
        name = f"img_{len(list(dest_dir.glob('img_*'))) + index}.jpg"
        path = await _download(url, dest_dir / name)
        out.append({"file": path.name, "prompt": prompt, "model": model_id})
    if not out:
        raise RuntimeError("לא התקבלו תמונות")
    return out


# ------------------------------------------------------------------- וידאו

async def animate_image(
    image_path: Path,
    motion_prompt: str,
    dest: Path,
    model_id: str = "fal-ai/kling-video/v2/master/image-to-video",
    duration_seconds: int = 5,
    on_progress: Callable[[float, str], None] | None = None,
) -> Path:
    """השלב היקר. רץ פעם אחת, על תמונה שכבר אישרת."""
    import base64
    import mimetypes

    mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "prompt": motion_prompt,
        "image_url": f"data:{mime};base64,{encoded}",
        "duration": str(int(duration_seconds)),
        "aspect_ratio": "9:16",
    }
    result = await _run(model_id, payload, on_progress, poll_seconds=4.0)

    video = result.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else None
    if not url:
        videos = result.get("videos") or []
        if videos and isinstance(videos[0], dict):
            url = videos[0].get("url")
    if not url:
        raise RuntimeError("fal.ai לא החזיר קובץ וידאו")
    return await _download(url, dest)
