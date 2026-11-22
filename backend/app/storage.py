"""Photo storage behind a small interface, so the cloud phase can swap in Cloud Storage."""

from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> str: ...
    def load(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Key escapes storage root: {key}")
        return path

    def save(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        try:  # drop the report folder once it is empty
            path.parent.rmdir()
        except OSError:
            pass


class GcsStorage:
    """Private Google Cloud Storage bucket. Credentials come from the Cloud Run service account
    (no keys in the app); photos are never public and are read only through the backend."""

    def __init__(self, bucket: str):
        from google.cloud import storage  # imported only in the cloud

        self.bucket = storage.Client().bucket(bucket)

    def save(self, key: str, data: bytes) -> str:
        ext = key.rsplit(".", 1)[-1].lower()
        ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "application/octet-stream")
        self.bucket.blob(key).upload_from_string(data, content_type=ctype)
        return key

    def load(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(key).delete()
        except NotFound:
            pass


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_bucket:
            _storage = GcsStorage(settings.storage_bucket)
        else:
            _storage = LocalStorage(settings.resolve(settings.photo_dir))
    return _storage
