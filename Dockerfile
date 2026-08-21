# פרונט סטודיו — הכל בקונטיינר אחד, כולל FFmpeg.
FROM python:3.11-slim

# ffmpeg לעריכה, ופונט עברי כדי שהכתוביות הנצרבות ייראו נכון
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-core \
        fonts-noto-extra \
        fonts-dejavu-core \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

# בענן, MEDIA_ROOT צריך להצביע לדיסק קבוע (למשל /var/data),
# אחרת הפרויקטים ייעלמו בכל פריסה מחדש.
# ברירת מחדל בטוחה לשרת קטן. Render דורס אותה דרך render.yaml.
ENV MEDIA_ROOT=/var/data \
    FFMPEG_THREADS=2 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /var/data/library /var/data/projects /var/data/exports

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
