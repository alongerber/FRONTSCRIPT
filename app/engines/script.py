"""מנוע התסריט — מכונת ניסוחים.

העיקרון: הכלי לא בוחר לך טון ולא מציע קטגוריות. הוא מייצר **מילים** —
ניסוחים חלופיים, פאנצ'ים, פתיחות וסופים — ותמיד יודע מה כבר הצעת לך,
כדי שלחיצה על "עוד" תביא באמת משהו חדש ולא וריאציה על אותו דבר.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from ..config import settings
from ..storage import new_id

# קצב דיבור עברי ממוצע, תווים לשנייה. משמש להערכת אורך בלי לשאול את המודל.
CHARS_PER_SECOND = 13.5
PAUSE_SECONDS = 0.45


def estimate_seconds(lines: list[str]) -> float:
    """הערכת אורך הקראה. כל שורה מקבלת נשימה קטנה בסוף."""
    if not lines:
        return 0.0
    chars = sum(len(line) for line in lines)
    return round(chars / CHARS_PER_SECOND + PAUSE_SECONDS * len(lines), 1)


SYSTEM = """אתה כותב תסריטים לסרטוני וידאו קצרים בעברית, עבור סוכנות פרסום ישראלית.

תפקידך הוא לייצר ניסוחים — מילים מדויקות שייאמרו בקול. לא הסברים, לא
תיאורי טון, לא הערות במאי. רק הטקסט עצמו, כפי שהוא ייאמר.

עקרונות עבודה:

1. ספציפיות מנצחת הכללה. "המקרר לא נכנס בדלת" חזק מ"היו לי בעיות עם
   הרהיטים". שמות, מספרים, מותגים, פרטים קטנים — הם מה שעושה את זה אמיתי.

2. הכיוון שהמשתמש נותן הוא חוק. אם הוא ביקש מופרע — תהיה מופרע באמת,
   בלי לרכך. אם ביקש הומור עצמי — הוא הפתטי בסיפור. אם ביקש יבש —
   אל תוסיף אנרגיה שהוא לא ביקש.

3. גיוון אמיתי בין אפשרויות. אפשרויות שונות חייבות להיות שונות במבנה
   ובזווית, לא רק בבחירת מילה. אם כולן נשמעות אותו דבר — נכשלת.

4. שורה = יחידת דיבור אחת. משפט או שניים, מה שנאמר בנשימה אחת.

5. עברית מדוברת. כמו שמדברים, לא כמו שכותבים. בלי מליצות.

6. אסור לחזור על ניסוח שכבר הוצע. תקבל רשימה של מה שכבר ראה המשתמש —
   כל פריט חדש חייב להיות שונה ממנה במהות, לא בניסוח.

7. אל תסביר את הבדיחה ואל תוסיף פאנץ' אחרי הפאנץ'.
"""


def _client() -> anthropic.AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError("חסר ANTHROPIC_API_KEY — מנוע התסריט מנוטרל")
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def _ask(prompt: str, schema: dict[str, Any], max_tokens: int = 8000) -> dict[str, Any]:
    """קריאה אחת למודל שמחזירה JSON תקין לפי סכימה."""
    response = await _client().messages.create(
        model=settings.script_model,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise RuntimeError("המודל סירב לייצר את התוכן הזה")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("המודל לא החזיר תשובה")
    return json.loads(text)


def _brief_block(brief: dict[str, Any]) -> str:
    parts = [f"הנושא: {brief.get('topic') or '(לא צוין)'}"]
    if brief.get("direction"):
        parts.append(f"הכיוון שהמשתמש ביקש, במילים שלו: {brief['direction']}")
    if brief.get("reference"):
        parts.append(
            "דוגמה שהמשתמש הדביק כרפרנס לרוח הדברים. אל תעתיק ממנה, קלוט "
            f"ממנה את המקצב והחדות:\n---\n{brief['reference'][:4000]}\n---"
        )
    target = brief.get("target_seconds") or 40
    parts.append(f"אורך יעד: בערך {target} שניות דיבור (בערך {int(target * CHARS_PER_SECOND)} תווים סך הכל).")
    return "\n".join(parts)


def _avoid_block(avoid: list[str], noun: str = "ניסוחים") -> str:
    clean = [a.strip() for a in avoid if a and a.strip()][-160:]
    if not clean:
        return ""
    listed = "\n".join(f"- {a}" for a in clean)
    return (
        f"\n\nה{noun} הבאים כבר הוצעו למשתמש והוא לא בחר בהם. "
        f"אל תחזור עליהם ואל תציע וריאציה קרובה שלהם. לך למקום אחר:\n{listed}"
    )


# ---------------------------------------------------------------- טיוטות מלאות

_DRAFTS_SCHEMA = {
    "type": "object",
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {
                        "type": "string",
                        "description": "בשלוש-חמש מילים, מה הזווית של הגרסה הזאת",
                    },
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "שורות הדיבור, בעברית, כפי שייאמרו",
                    },
                },
                "required": ["angle", "lines"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["drafts"],
    "additionalProperties": False,
}


async def generate_drafts(
    brief: dict[str, Any], count: int = 6, avoid: list[str] | None = None
) -> list[dict[str, Any]]:
    """מייצר כמה תסריטים מלאים ושונים זה מזה."""
    prompt = (
        f"{_brief_block(brief)}\n\n"
        f"כתוב {count} תסריטים שלמים ושונים לחלוטין זה מזה.\n\n"
        "כל תסריט חייב להיות שונה מהאחרים ב**מבנה** ולא רק במילים: "
        "אחד יכול לפתוח בשורת מחץ ואז להסביר, אחד לבנות לאט לפאנץ' בסוף, "
        "אחד להיות רשימה, אחד דיאלוג עם עצמך, אחד להתחיל באמצע הסיפור. "
        "אם שניים מהם נשמעים כמו אותו תסריט — כתוב מחדש."
        + _avoid_block(avoid or [], "התסריטים")
    )
    data = await _ask(prompt, _DRAFTS_SCHEMA, max_tokens=12000)
    drafts = []
    for item in data.get("drafts", []):
        lines = [ln.strip() for ln in item.get("lines", []) if ln and ln.strip()]
        if not lines:
            continue
        drafts.append(
            {
                "id": new_id("d_"),
                "angle": item.get("angle", "").strip(),
                "lines": [{"id": new_id("l_"), "text": t} for t in lines],
                "seconds": estimate_seconds(lines),
            }
        )
    return drafts


# ------------------------------------------------------------ חלופות לשורה אחת

_OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "הניסוח עצמו, בעברית"},
                    "note": {
                        "type": "string",
                        "description": "עד ארבע מילים על מה שונה כאן. לא ניתוח.",
                    },
                },
                "required": ["text", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}


def _script_context(lines: list[dict[str, Any]], focus_id: str | None = None) -> str:
    rows = []
    for line in lines:
        marker = "  ← השורה שעליה עובדים" if line.get("id") == focus_id else ""
        rows.append(f"{line.get('text', '')}{marker}")
    return "התסריט המלא כרגע:\n" + "\n".join(rows) if rows else ""


async def line_alternatives(
    line_text: str,
    lines: list[dict[str, Any]],
    focus_id: str | None,
    count: int = 8,
    avoid: list[str] | None = None,
    instruction: str = "",
) -> list[dict[str, Any]]:
    """ניסוחים חלופיים לשורה בודדת — אותה כוונה, מילים אחרות."""
    extra = f"\n\nהמשתמש ביקש במפורש: {instruction}" if instruction.strip() else ""
    prompt = (
        f"{_script_context(lines, focus_id)}\n\n"
        f'השורה שצריך לנסח מחדש:\n"{line_text}"\n\n'
        f"כתוב {count} ניסוחים חלופיים לשורה הזאת.\n\n"
        "הם צריכים למלא את אותו תפקיד בתסריט, אבל להישמע אחרת: אורך אחר, "
        "מקצב אחר, מילה אחרת שנושאת את המשקל, סדר הפוך, קיצור אכזרי, "
        "הרחבה שמוסיפה פרט. לפחות אחד קצר בהרבה מהמקור ולפחות אחד ארוך יותר."
        f"{extra}"
        + _avoid_block(avoid or [])
    )
    data = await _ask(prompt, _OPTIONS_SCHEMA)
    return [
        {"id": new_id("o_"), "text": o["text"].strip(), "note": o.get("note", "").strip()}
        for o in data.get("options", [])
        if o.get("text", "").strip()
    ]


# ----------------------------------------------------------------- פאנצ'ים

async def punchlines(
    lines: list[dict[str, Any]],
    count: int = 10,
    avoid: list[str] | None = None,
    instruction: str = "",
) -> list[dict[str, Any]]:
    """שורות סיום לתסריט הקיים. זה הכפתור שנלחץ הכי הרבה."""
    body = [ln.get("text", "") for ln in lines]
    setup = "\n".join(body[:-1]) if len(body) > 1 else "\n".join(body)
    current = body[-1] if body else ""
    extra = f"\n\nהמשתמש ביקש במפורש: {instruction}" if instruction.strip() else ""
    prompt = (
        f"זה הסטאפ:\n{setup}\n\n"
        f'הסיום הנוכחי, שלא מספיק טוב:\n"{current}"\n\n'
        f"כתוב {count} שורות סיום חלופיות.\n\n"
        "כל אחת מסוג אחר: אחת שמפילה את הכל במילה אחת, אחת שחוזרת למשהו "
        "שנאמר בהתחלה, אחת שמודה במשהו קטן ומביך, אחת שמחליפה נושא כאילו "
        "כלום, אחת שהיא שאלה, אחת ארוכה מדי בכוונה, אחת שהיא שתיקה מתוארת "
        "במילים. אל תסביר אף אחת מהן."
        f"{extra}"
        + _avoid_block(avoid or [], "הסיומים")
    )
    data = await _ask(prompt, _OPTIONS_SCHEMA)
    return [
        {"id": new_id("o_"), "text": o["text"].strip(), "note": o.get("note", "").strip()}
        for o in data.get("options", [])
        if o.get("text", "").strip()
    ]


# ------------------------------------------------------------------- פתיחות

async def openers(
    lines: list[dict[str, Any]],
    count: int = 10,
    avoid: list[str] | None = None,
    instruction: str = "",
) -> list[dict[str, Any]]:
    """שלוש השניות הראשונות — מה שקובע אם ממשיכים לצפות."""
    body = "\n".join(ln.get("text", "") for ln in lines)
    extra = f"\n\nהמשתמש ביקש במפורש: {instruction}" if instruction.strip() else ""
    prompt = (
        f"התסריט:\n{body}\n\n"
        f"כתוב {count} שורות פתיחה חלופיות — מה שנאמר בשנייה הראשונה.\n\n"
        "בסרטון אנכי יש שלוש שניות לפני שגוללים הלאה. אחת שנכנסת באמצע "
        "המשפט, אחת שהיא הצהרה מוזרה, אחת שמודה במשהו מיד, אחת שהיא "
        "שאלה ישירה למצלמה, אחת שנשמעת כמו התנצלות. בלי 'היי חברים' "
        "ובלי 'אז ככה'."
        f"{extra}"
        + _avoid_block(avoid or [], "הפתיחות")
    )
    data = await _ask(prompt, _OPTIONS_SCHEMA)
    return [
        {"id": new_id("o_"), "text": o["text"].strip(), "note": o.get("note", "").strip()}
        for o in data.get("options", [])
        if o.get("text", "").strip()
    ]


# ------------------------------------------------------- פעולות על התסריט כולו

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["lines"],
    "additionalProperties": False,
}


async def rework(
    lines: list[dict[str, Any]], instruction: str, brief: dict[str, Any]
) -> list[str]:
    """שכתוב של התסריט כולו לפי הוראה חופשית של המשתמש."""
    body = "\n".join(ln.get("text", "") for ln in lines)
    prompt = (
        f"{_brief_block(brief)}\n\n"
        f"התסריט הנוכחי:\n{body}\n\n"
        f"מה שהמשתמש מבקש לשנות:\n{instruction}\n\n"
        "החזר את התסריט המלא אחרי השינוי. שנה רק מה שנדרש — שורות שלא "
        "קשורות לבקשה חייבות לחזור מילה במילה כפי שהן."
    )
    data = await _ask(prompt, _REWRITE_SCHEMA)
    return [ln.strip() for ln in data.get("lines", []) if ln.strip()]


async def fit_to_length(lines: list[dict[str, Any]], target_seconds: int) -> list[str]:
    """קיצור או הרחבה לאורך יעד, בלי לאבד את הפאנץ'."""
    body = "\n".join(ln.get("text", "") for ln in lines)
    current = estimate_seconds([ln.get("text", "") for ln in lines])
    direction = "קצר" if current > target_seconds else "הרחב"
    prompt = (
        f"התסריט הנוכחי (בערך {current} שניות):\n{body}\n\n"
        f"{direction} אותו כך שייקח בערך {target_seconds} שניות "
        f"(בערך {int(target_seconds * CHARS_PER_SECOND)} תווים).\n\n"
        "שורת הסיום היא הדבר הכי חשוב — אותה שומרים. אם צריך לחתוך, "
        "חותכים מהאמצע. אל תדחוס משפטים ואל תמחק פרטים ספציפיים שנושאים "
        "את ההומור."
    )
    data = await _ask(prompt, _REWRITE_SCHEMA)
    return [ln.strip() for ln in data.get("lines", []) if ln.strip()]


# --------------------------------------------------- חידוד הכיוון של המשתמש

_SHARPEN_SCHEMA = {
    "type": "object",
    "properties": {
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "ניסוח מחודד של הכיוון, במילים של המשתמש",
                    },
                    "sample": {
                        "type": "string",
                        "description": "שורה אחת לדוגמה שממחישה איך זה יישמע",
                    },
                },
                "required": ["direction", "sample"],
                "additionalProperties": False,
            },
        },
        "question": {
            "type": "string",
            "description": "שאלה אחת קצרה שבאמת אי אפשר לנחש. ריק אם אין.",
        },
    },
    "required": ["readings", "question"],
    "additionalProperties": False,
}


async def sharpen(brief: dict[str, Any], count: int = 4) -> dict[str, Any]:
    """לוקח כיוון כללי ומחזיר קריאות מחודדות שלו — עם דוגמת שורה לכל אחת.

    לא קטגוריות: הקריאות נגזרות מהמילים והנושא הספציפיים בכל פעם מחדש.
    """
    prompt = (
        f"{_brief_block(brief)}\n\n"
        f"הכיוון שהמשתמש כתב כללי מדי מכדי לכתוב ממנו. הצע {count} קריאות "
        "מחודדות שלו — כל אחת פרשנות אחרת ולגיטימית של מה שהוא אמר.\n\n"
        "לכל קריאה צרף **שורה אחת לדוגמה** מהתסריט העתידי, כדי שהוא ישמע "
        "את ההבדל ולא רק יקרא עליו. השורה היא העיקר.\n\n"
        "אם יש שאלה אחת שבאמת אי אפשר לנחש בלעדיה — שאל אותה. אם אין, "
        "החזר מחרוזת ריקה. אל תשאל שאלות מנומסות."
    )
    data = await _ask(prompt, _SHARPEN_SCHEMA, max_tokens=4000)
    return {
        "readings": [
            {
                "id": new_id("r_"),
                "direction": r["direction"].strip(),
                "sample": r.get("sample", "").strip(),
            }
            for r in data.get("readings", [])
            if r.get("direction", "").strip()
        ],
        "question": (data.get("question") or "").strip(),
    }


# ------------------------------------------------------- הצעות B-roll לתסריט

_BROLL_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_index": {"type": "integer", "description": "מספר השורה, מ-0"},
                    "idea_he": {"type": "string", "description": "מה רואים, בעברית"},
                },
                "required": ["line_index", "idea_he"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["shots"],
    "additionalProperties": False,
}


async def suggest_broll(lines: list[dict[str, Any]], count: int = 4) -> list[dict[str, Any]]:
    """מציע איפה כדאי לחתוך ל-B-roll ומה לראות שם."""
    body = "\n".join(f"{i}. {ln.get('text','')}" for i, ln in enumerate(lines))
    prompt = (
        f"התסריט, ממוספר:\n{body}\n\n"
        f"הצע עד {count} מקומות לחתוך לקטע B-roll.\n\n"
        "ה-B-roll הכי טוב הוא לא איור של מה שנאמר — הוא סותר אותו, מקדים "
        "אותו, או מראה את הפרט המשעמם שאף אחד לא היה מצלם. תאר מה רואים "
        "בפריים, לא רעיון מופשט."
    )
    data = await _ask(prompt, _BROLL_SCHEMA, max_tokens=3000)
    return [
        {"line_index": int(s["line_index"]), "idea_he": s["idea_he"].strip()}
        for s in data.get("shots", [])
        if s.get("idea_he", "").strip()
    ]
