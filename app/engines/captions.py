"""מנוע הכתוביות.

התובנה שחוסכת את כל התיקונים הידניים: אנחנו כבר יודעים מה נאמר בסרטון,
כי אנחנו כתבנו את התסריט. לכן המשימה היא לא "מה הוא אמר" אלא "מתי בדיוק"
— והתמלול משמש רק לתזמון. המילים עצמן נלקחות מהתסריט, אז אין שמות
משובשים ואין המצאות.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from . import voice

# ניקוד וסימני פיסוק מוסרים רק לצורך ההשוואה, לא מהטקסט המוצג
_STRIP = re.compile(r"[֑-ׇ\"'’“”.,!?;:()\[\]{}\-–—…]+")


def _norm(word: str) -> str:
    return _STRIP.sub("", word).strip().lower()


def script_words(lines: list[dict[str, Any]]) -> list[str]:
    words: list[str] = []
    for line in lines:
        words.extend(w for w in (line.get("text") or "").split() if w.strip())
    return words


def align(spoken: list[dict[str, Any]], target: list[str]) -> list[dict[str, Any]]:
    """מלביש את מילות התסריט על התזמונים שהתמלול מצא.

    התמלול טועה באיות, במיוחד בעברית ובשמות. אנחנו לוקחים ממנו רק את
    חותמות הזמן, ואת האותיות מהתסריט.
    """
    if not target:
        return list(spoken)
    if not spoken:
        return []

    heard = [_norm(w["w"]) for w in spoken]
    wanted = [_norm(w) for w in target]
    matcher = difflib.SequenceMatcher(a=heard, b=wanted, autojunk=False)

    out: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                out.append(
                    {
                        "w": target[j1 + offset],
                        "start": spoken[i1 + offset]["start"],
                        "end": spoken[i1 + offset]["end"],
                    }
                )
        elif tag in {"replace", "delete", "insert"}:
            # פורסים את מילות התסריט באופן שווה על פני חלון הזמן המקביל
            count = j2 - j1
            if count <= 0:
                continue
            if i2 > i1:
                start = spoken[i1]["start"]
                end = spoken[i2 - 1]["end"]
            else:
                start = spoken[i1 - 1]["end"] if i1 > 0 else spoken[0]["start"]
                end = spoken[i1]["start"] if i1 < len(spoken) else spoken[-1]["end"]
            if end <= start:
                end = start + 0.28 * count
            step = (end - start) / count
            for offset in range(count):
                out.append(
                    {
                        "w": target[j1 + offset],
                        "start": round(start + step * offset, 3),
                        "end": round(start + step * (offset + 1), 3),
                    }
                )

    # מוודאים שהזמנים עולים ואין חפיפות
    for index in range(1, len(out)):
        if out[index]["start"] < out[index - 1]["end"]:
            out[index]["start"] = out[index - 1]["end"]
        if out[index]["end"] <= out[index]["start"]:
            out[index]["end"] = out[index]["start"] + 0.12
    return out


async def build_words(audio: Path, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """מייצר את רשימת המילים המתוזמנת. מנסה יישור מדויק, ונופל לתמלול."""
    target = script_words(lines)
    text = " ".join(target)

    if text.strip():
        aligned = await voice.forced_alignment(audio, text)
        if aligned:
            return align(aligned, target)

    spoken = await voice.transcribe_words(audio)
    if not target:
        return spoken
    return align(spoken, target)


# ------------------------------------------------------------- ייצור קובץ ASS

def _ass_color(hex_color: str, alpha: str = "00") -> str:
    """ASS עובד ב-BGR ולא ב-RGB, ועם ערוץ שקיפות בהתחלה."""
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        value = "FFFFFF"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def write_ass(
    words: list[dict[str, Any]],
    dest: Path,
    style: dict[str, Any],
    width: int,
    height: int,
) -> Path:
    """כותב כתוביות מתקדמות מילה-מילה, בסגנון הסרטונים האנכיים."""
    font = (style.get("font") or "Noto Sans Hebrew").replace(",", " ")
    font_size = int(style.get("font_size", 74))
    primary = _ass_color(style.get("primary", "#FFFFFF"))
    highlight = _ass_color(style.get("highlight", "#FFE24A"))
    outline_color = _ass_color(style.get("outline", "#000000"))
    outline_width = int(style.get("outline_width", 5))
    per_screen = max(1, int(style.get("words_per_screen", 3)))
    mode = style.get("mode", "progressive")
    y_percent = float(style.get("y_percent", 74))
    margin_v = max(20, int(height * (1.0 - y_percent / 100.0)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Front,{font},{font_size},{primary},{primary},{outline_color},&H64000000,-1,0,0,0,100,100,0,0,1,{outline_width},2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []

    if mode == "single":
        # מילה אחת גדולה בכל רגע
        for word in words:
            text = _escape(word["w"])
            events.append(
                f"Dialogue: 0,{_ass_time(word['start'])},{_ass_time(word['end'])},"
                f"Front,,0,0,0,,{{\\c{highlight}}}{text}"
            )
    else:
        # קבוצת מילים, כשהמילה הנוכחית צבועה
        for index in range(0, len(words), per_screen):
            chunk = words[index : index + per_screen]
            for position, word in enumerate(chunk):
                parts = []
                for other_index, other in enumerate(chunk):
                    text = _escape(other["w"])
                    if other_index == position:
                        parts.append(f"{{\\c{highlight}}}{text}{{\\c{primary}}}")
                    else:
                        parts.append(text)
                line = " ".join(parts)
                end = word["end"] if position < len(chunk) - 1 else chunk[-1]["end"]
                events.append(
                    f"Dialogue: 0,{_ass_time(word['start'])},{_ass_time(end)},"
                    f"Front,,0,0,0,,{{\\c{primary}}}{line}"
                )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return dest


def write_srt(words: list[dict[str, Any]], dest: Path, per_cue: int = 6) -> Path:
    """קובץ SRT רגיל, למי שרוצה להעלות כתוביות בנפרד לפלטפורמה."""
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        hours, ms = divmod(ms, 3600000)
        minutes, ms = divmod(ms, 60000)
        secs, ms = divmod(ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    blocks = []
    for number, index in enumerate(range(0, len(words), per_cue), start=1):
        chunk = words[index : index + per_cue]
        if not chunk:
            continue
        text = " ".join(w["w"] for w in chunk)
        blocks.append(f"{number}\n{stamp(chunk[0]['start'])} --> {stamp(chunk[-1]['end'])}\n{text}\n")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(blocks), encoding="utf-8")
    return dest
