"""אחסון פרויקטים וספריית ה-B-roll. הכל קבצים על הדיסק — בלי בסיס נתונים."""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .config import settings

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac"}


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def safe_id(value: str) -> str:
    """מוודא שמזהה שהגיע מהדפדפן לא יכול לצאת מהתיקייה שלו."""
    if not _SAFE_ID.match(value or ""):
        raise ValueError("bad id")
    return value


def blank_project(name: str) -> dict[str, Any]:
    return {
        "id": new_id("p_"),
        "name": name or "סרטון ללא שם",
        "created_at": time.time(),
        "updated_at": time.time(),
        "stage": "script",
        "brief": {
            "topic": "",
            "direction": "",
            "reference": "",
            "target_seconds": 40,
        },
        # התסריט הנעול — רשימת שורות
        "script": {"lines": [], "locked": False},
        # כל מה שהמנוע הציע אי פעם בפרויקט הזה, כדי ש"עוד" יביא באמת חדש
        "seen_lines": [],
        "seen_drafts": [],
        "voice": {
            "voice_id": "",
            "model_id": "eleven_multilingual_v2",
            "settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
                "speed": 1.0,
            },
            "takes": [],
            "chosen_take": None,
            "locked": False,
        },
        "broll": {"shots": []},
        "avatar": {
            "avatar_id": "",
            "engine": "avatar_iv",
            "resolution": "1080p",
            "video_id": "",
            "file": None,
            "duration": None,
        },
        "captions": {
            "enabled": True,
            "words": [],
            "style": {
                "font": "Noto Sans Hebrew",
                "font_size": 74,
                "primary": "#FFFFFF",
                "highlight": "#FFE24A",
                "outline": "#000000",
                "outline_width": 5,
                "y_percent": 74,
                "words_per_screen": 3,
                "mode": "progressive",
            },
        },
        "export": {"file": None, "at": None},
    }


class Store:
    def __init__(self) -> None:
        settings.ensure_dirs()

    # ---------- פרויקטים ----------

    def project_dir(self, project_id: str) -> Path:
        return settings.projects_dir / safe_id(project_id)

    def _path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def create(self, name: str) -> dict[str, Any]:
        project = blank_project(name)
        d = self.project_dir(project["id"])
        for sub in ("voice", "avatar", "broll", "export"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        self.save(project)
        return project

    def save(self, project: dict[str, Any]) -> dict[str, Any]:
        project["updated_at"] = time.time()
        path = self._path(project["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return project

    def load(self, project_id: str) -> dict[str, Any]:
        path = self._path(project_id)
        if not path.exists():
            raise FileNotFoundError(project_id)
        project = json.loads(path.read_text(encoding="utf-8"))
        # מיזוג עם ברירות המחדל — כדי שפרויקט ישן לא ייפול אחרי עדכון
        base = blank_project(project.get("name", ""))
        base.update(project)
        for key in ("brief", "script", "voice", "broll", "avatar", "captions", "export"):
            merged = blank_project("")[key]
            if isinstance(merged, dict) and isinstance(project.get(key), dict):
                merged.update(project[key])
                base[key] = merged
        return base

    def list_projects(self) -> list[dict[str, Any]]:
        out = []
        for d in settings.projects_dir.iterdir() if settings.projects_dir.exists() else []:
            f = d / "project.json"
            if not f.is_file():
                continue
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append(
                {
                    "id": p.get("id", d.name),
                    "name": p.get("name", d.name),
                    "stage": p.get("stage", "script"),
                    "updated_at": p.get("updated_at", 0),
                    "has_export": bool((p.get("export") or {}).get("file")),
                }
            )
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def delete(self, project_id: str) -> None:
        shutil.rmtree(self.project_dir(project_id), ignore_errors=True)

    # ---------- ספריית B-roll ----------

    def library(self) -> list[dict[str, Any]]:
        items = []
        for f in sorted(settings.library_dir.glob("*")):
            if f.suffix.lower() not in VIDEO_EXTS or not f.is_file():
                continue
            items.append(
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "url": f"/media/library/{f.name}",
                }
            )
        return items

    def library_path(self, name: str) -> Path:
        """מונע יציאה מהתיקייה דרך שם קובץ זדוני."""
        p = (settings.library_dir / Path(name).name).resolve()
        if p.parent != settings.library_dir.resolve():
            raise ValueError("bad path")
        return p


store = Store()
