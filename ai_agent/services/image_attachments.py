"""שמירה וטעינת תמונות לבקשות AI."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings

ALLOWED_EXT = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.gif'})
MAX_IMAGES = 5
MAX_BYTES = 5 * 1024 * 1024


def request_images_dir(request_id: int) -> Path:
    d = Path(settings.BASE_DIR) / 'data' / 'ai_requests' / str(request_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_uploaded_images(request_id: int, files) -> list[str]:
    """שומר קבצים שהועלו; מחזיר רשימת שמות קבצים."""
    saved: list[str] = []
    dest = request_images_dir(request_id)
    for i, uploaded in enumerate(files[:MAX_IMAGES]):
        if not uploaded:
            continue
        if getattr(uploaded, 'size', 0) > MAX_BYTES:
            continue
        ext = Path(uploaded.name or '').suffix.lower()
        if ext not in ALLOWED_EXT:
            continue
        name = f'img_{i}{ext}'
        path = dest / name
        with path.open('wb') as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        saved.append(name)
    return saved


def _mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.png':
        return 'image/png'
    if ext == '.webp':
        return 'image/webp'
    if ext == '.gif':
        return 'image/gif'
    return 'image/jpeg'


def image_paths_for_request(request_id: int, names: list[str] | None) -> list[Path]:
    base = request_images_dir(request_id)
    out: list[Path] = []
    for name in names or []:
        p = base / name
        if p.is_file():
            out.append(p)
    return out
