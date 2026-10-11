import ctypes
import os
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr

from backend.compat import ZoneInfo, ZoneInfoNotFoundError
from backend.settings_base import RuntimeSettings, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_storage_root() -> Path:
    if os.name == "nt":
        # Windows resolves Desktop redirection (including OneDrive) through the shell API.
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer)
        if result != 0:
            raise ValueError("Windows Desktop could not be resolved; set STORAGE_ROOT.")
        return Path(buffer.value) / "Gelen Dosyalar"
    return Path.home() / "Desktop" / "Gelen Dosyalar"


class Settings(RuntimeSettings):
    storage_root: Path = Field(default_factory=default_storage_root)
    data_root: Path = PROJECT_ROOT / "data"
    timezone: str = "Europe/Istanbul"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    session_ttl_minutes: int = Field(default=60, ge=1, le=1440)
    max_file_size_mb: int = Field(default=25, ge=1)
    max_session_size_mb: int = Field(default=100, ge=1)
    max_files_per_session: int = Field(default=10, ge=1, le=100)
    min_free_disk_mb: int = Field(default=512, ge=0)
    allowed_extensions: str = ".pdf,.docx,.pptx,.xlsx,.jpg,.jpeg,.png"
    gateway_secret: Optional[SecretStr] = None
    requests_per_minute: int = Field(default=120, ge=1)
    sessions_per_minute: int = Field(default=20, ge=1)
    sessions_per_day: int = Field(default=2000, ge=1)
    daily_upload_mb: int = Field(default=4000, ge=1)
    max_active_uploads: int = Field(default=4, ge=1, le=32)
    upload_timeout_seconds: float = Field(default=180, gt=0, le=600)

    @field_validator("gateway_secret")
    @classmethod
    def strong_gateway_secret(cls, value):
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("GATEWAY_SECRET must contain at least 32 characters.")
        return value

    @field_validator("allowed_extensions")
    @classmethod
    def supported_extensions(cls, value: str) -> str:
        extensions = {item.strip().lower() for item in value.split(",")}
        supported = {".pdf", ".docx", ".pptx", ".xlsx", ".jpg", ".jpeg", ".png"}
        if not extensions or not extensions <= supported:
            raise ValueError(
                "ALLOWED_EXTENSIONS must be a subset of supported document/image types."
            )
        return ",".join(sorted(extensions))

    @field_validator("storage_root", "data_root")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Use an absolute directory path.")
        return value.resolve()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA time zone.") from error
        return value

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError("The backend must listen on 127.0.0.1; use an HTTPS tunnel.")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_root / "inbox.sqlite3"

    @property
    def temporary_root(self) -> Path:
        return self.data_root / "temporary"
