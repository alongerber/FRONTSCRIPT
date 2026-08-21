"""הגדרות המערכת — נטענות מקובץ .env או ממשתני סביבה."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """טוען .env בלי תלות חיצונית. משתני סביבה קיימים גוברים."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


class Settings:
    # כניסה
    studio_password: str = os.environ.get("STUDIO_PASSWORD", "")
    secret_key: str = os.environ.get("SECRET_KEY", "dev-insecure-key")

    # מנועים
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    script_model: str = os.environ.get("SCRIPT_MODEL", "claude-opus-5")
    elevenlabs_api_key: str = os.environ.get("ELEVENLABS_API_KEY", "")
    heygen_api_key: str = os.environ.get("HEYGEN_API_KEY", "")
    fal_key: str = os.environ.get("FAL_KEY", "")

    # מדיה
    media_root: Path = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media")).resolve()
    ffmpeg_bin: str = os.environ.get("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin: str = os.environ.get("FFPROBE_BIN", "ffprobe")
    # מגבלת ליבות ל-FFmpeg. שרת קטן (512MB) יקרוס בלי זה,
    # כי libx264 מקצה חוצץ פריימים נפרד לכל ליבה.
    ffmpeg_threads: int = max(1, int(os.environ.get("FFMPEG_THREADS", "2")))

    # קנבס — אנכי לטיקטוק/רילס
    canvas_width: int = int(os.environ.get("CANVAS_WIDTH", "1080"))
    canvas_height: int = int(os.environ.get("CANVAS_HEIGHT", "1920"))

    @property
    def library_dir(self) -> Path:
        return self.media_root / "library"

    @property
    def projects_dir(self) -> Path:
        return self.media_root / "projects"

    @property
    def exports_dir(self) -> Path:
        return self.media_root / "exports"

    def ensure_dirs(self) -> None:
        for d in (self.library_dir, self.projects_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def engine_status(self) -> dict[str, bool]:
        """אילו מנועים מוגדרים — כדי שהממשק יסמן מה חסר."""
        return {
            "script": bool(self.anthropic_api_key),
            "voice": bool(self.elevenlabs_api_key),
            "broll": bool(self.fal_key),
            "avatar": bool(self.heygen_api_key),
        }


settings = Settings()
settings.ensure_dirs()
