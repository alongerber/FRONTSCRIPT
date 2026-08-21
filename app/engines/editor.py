"""מנוע העריכה — FFmpeg.

הכלל הקדוש של המסך הזה: **הקול של האווטאר לא זז.** ה-B-roll מחליף תמונה
בלבד, פס הקול המקורי עובר לקובץ הסופי כמו שהוא. אין דרך שהסנכרון יישבר.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from ..config import settings


class FFmpegMissing(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


def _require() -> None:
    if not ffmpeg_available():
        raise FFmpegMissing(
            "FFmpeg לא מותקן. במחשב: brew install ffmpeg (מאק) או "
            "apt install ffmpeg (לינוקס). בענן: הוא כבר בתוך ה-Dockerfile."
        )


async def probe(path: Path) -> dict[str, Any]:
    """אורך, רזולוציה, והאם יש פס קול."""
    process = await asyncio.create_subprocess_exec(
        settings.ffprobe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffprobe נכשל: {stderr.decode('utf-8', 'ignore')[:300]}")

    data = json.loads(stdout.decode("utf-8", "ignore") or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = data.get("format", {}).get("duration")
    return {
        "duration": float(duration) if duration else 0.0,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "has_audio": has_audio,
    }


def _escape_filter_path(path: Path) -> str:
    """נתיב בתוך filtergraph — נקודתיים ולוכסנים חייבים בריחה."""
    text = str(path)
    for old, new in (("\\", "\\\\"), (":", "\\:"), ("'", "\\'"), ("[", "\\["), ("]", "\\]")):
        text = text.replace(old, new)
    return text


async def _run(
    args: list[str],
    total_seconds: float,
    on_progress: Callable[[float, str], None] | None,
    label: str,
) -> None:
    """מריץ ffmpeg ומתרגם את הפלט שלו לאחוזי התקדמות."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def read_progress() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode("utf-8", "ignore").strip()
            if line.startswith("out_time_ms=") and total_seconds > 0 and on_progress:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000.0
                except ValueError:
                    continue
                on_progress(min(0.98, done / total_seconds), label)

    reader = asyncio.create_task(read_progress())
    stderr = await process.stderr.read() if process.stderr else b""
    await process.wait()
    reader.cancel()

    if process.returncode != 0:
        tail = stderr.decode("utf-8", "ignore").strip().splitlines()[-12:]
        raise RuntimeError("FFmpeg נכשל:\n" + "\n".join(tail))


async def render(
    avatar_video: Path,
    shots: list[dict[str, Any]],
    dest: Path,
    *,
    ass_file: Path | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    crf: int = 19,
    preset: str = "medium",
) -> Path:
    """מרכיב את הסרטון הסופי.

    כל פריט ב-shots:
        file      — נתיב לקובץ ה-B-roll
        start     — שנייה שבה הוא נכנס
        duration  — כמה זמן הוא נשאר. כל אורך, גמיש לגמרי.
        mode      — "full" (קאט על כל הפריים) או "pip" (חלון קטן)
        scale     — גודל החלון ב-pip, שבר מרוחב הפריים
        x, y      — מיקום החלון באחוזים
        audio_mix — 0 = מושתק (ברירת מחדל). מעל 0 = מתערבב מתחת לקול שלך.
    """
    _require()
    width, height = settings.canvas_width, settings.canvas_height
    base_info = await probe(avatar_video)
    total = base_info["duration"] or 0.0

    # מסננים כל קטע שאין לו קובץ או שהוא מחוץ לסרטון, ומקצצים לאורך האמיתי
    usable: list[dict[str, Any]] = []
    for shot in shots:
        raw_path = shot.get("file")
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        info = await probe(path)
        start = max(0.0, float(shot.get("start", 0.0)))
        if total and start >= total:
            continue
        requested = float(shot.get("duration") or info["duration"] or 0.0)
        duration = min(requested, info["duration"] or requested)
        if total:
            duration = min(duration, total - start)
        if duration <= 0.05:
            continue
        usable.append(
            {
                **shot,
                "path": path,
                "start": round(start, 3),
                "duration": round(duration, 3),
                "has_audio": info["has_audio"],
            }
        )
    usable.sort(key=lambda s: s["start"])

    args = [settings.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats", "-i", str(avatar_video)]
    for shot in usable:
        args += ["-i", str(shot["path"])]

    filters: list[str] = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30[base]"
    ]

    current = "base"
    audio_parts: list[str] = []

    for index, shot in enumerate(usable, start=1):
        start = shot["start"]
        end = round(start + shot["duration"], 3)
        label = f"bv{index}"

        if shot.get("mode") == "pip":
            scale = max(0.15, min(0.9, float(shot.get("scale", 0.42))))
            target_w = int(width * scale) // 2 * 2
            filters.append(
                f"[{index}:v]trim=start=0:duration={shot['duration']},"
                f"setpts=PTS-STARTPTS+{start}/TB,"
                f"scale={target_w}:-2,setsar=1,fps=30[{label}]"
            )
            x_pct = max(0.0, min(1.0, float(shot.get("x", 0.05))))
            y_pct = max(0.0, min(1.0, float(shot.get("y", 0.08))))
            x_expr = f"(W-w)*{x_pct:.4f}"
            y_expr = f"(H-h)*{y_pct:.4f}"
        else:
            filters.append(
                f"[{index}:v]trim=start=0:duration={shot['duration']},"
                f"setpts=PTS-STARTPTS+{start}/TB,"
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps=30[{label}]"
            )
            x_expr, y_expr = "0", "0"

        out_label = f"ov{index}"
        filters.append(
            f"[{current}][{label}]overlay={x_expr}:{y_expr}:"
            f"enable='between(t,{start},{end})':eof_action=pass[{out_label}]"
        )
        current = out_label

        mix = float(shot.get("audio_mix", 0.0) or 0.0)
        if mix > 0 and shot["has_audio"]:
            delay_ms = int(start * 1000)
            filters.append(
                f"[{index}:a]atrim=start=0:duration={shot['duration']},"
                f"asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms},"
                f"volume={min(1.0, mix):.3f}[ba{index}]"
            )
            audio_parts.append(f"[ba{index}]")

    # כתוביות נצרבות אחרונות, מעל הכל
    if ass_file and ass_file.is_file():
        filters.append(f"[{current}]ass='{_escape_filter_path(ass_file)}'[vout]")
        current = "vout"
    else:
        filters.append(f"[{current}]null[vout]")
        current = "vout"

    # --- קול --------------------------------------------------------------
    if audio_parts and base_info["has_audio"]:
        joined = "[0:a]" + "".join(audio_parts)
        filters.append(
            f"{joined}amix=inputs={len(audio_parts) + 1}:duration=first:"
            f"dropout_transition=0:normalize=0[aout]"
        )
        audio_args = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    elif base_info["has_audio"]:
        # המקרה הרגיל: פס הקול המקורי מועתק בלי נגיעה
        audio_args = ["-map", "0:a", "-c:a", "copy"]
    else:
        audio_args = ["-an"]

    args += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        *audio_args,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-r", "30",
        # מגבלת ליבות — בלעדיה שרת עם 512MB נופל באמצע הרינדור
        "-threads", str(settings.ffmpeg_threads),
        "-filter_complex_threads", str(settings.ffmpeg_threads),
        str(dest),
    ]

    dest.parent.mkdir(parents=True, exist_ok=True)
    await _run(args, total, on_progress, "מרנדר")
    return dest


async def make_preview(
    avatar_video: Path,
    shots: list[dict[str, Any]],
    dest: Path,
    ass_file: Path | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> Path:
    """תצוגה מקדימה מהירה — חצי רזולוציה, נועדה לבדיקה ולא לפרסום."""
    return await render(
        avatar_video, shots, dest,
        ass_file=ass_file, on_progress=on_progress,
        crf=28, preset="veryfast",
    )


async def extract_waveform(audio: Path, dest: Path, samples: int = 900) -> list[float]:
    """מוציא צורת גל לטיימליין. אם ffmpeg חסר — מחזיר רשימה ריקה בשקט."""
    if not ffmpeg_available():
        return []
    process = await asyncio.create_subprocess_exec(
        settings.ffmpeg_bin, "-v", "error", "-i", str(audio),
        "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    raw, _ = await process.communicate()
    if process.returncode != 0 or not raw:
        return []

    import array

    pcm = array.array("h")
    pcm.frombytes(raw[: len(raw) // 2 * 2])
    if not pcm:
        return []

    bucket = max(1, len(pcm) // samples)
    peaks = []
    for index in range(0, len(pcm), bucket):
        window = pcm[index : index + bucket]
        if window:
            peaks.append(min(1.0, max(abs(v) for v in window) / 32768.0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(peaks), encoding="utf-8")
    return peaks
