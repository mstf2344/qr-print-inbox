"""Current Pydantic for source builds; maintained v1 wheels for Windows 7 (no Rust)."""

import os
from pathlib import Path

__all__ = ["RuntimeSettings", "field_validator"]

ENV_FILE = Path(os.environ.get("QR_INBOX_CONFIG", Path(__file__).resolve().parent.parent / ".env"))

try:
    from pydantic import field_validator as field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseSettings
    from pydantic import validator as field_validator

    class RuntimeSettings(BaseSettings):
        class Config:
            env_file = ENV_FILE
            env_file_encoding = "utf-8"
            extra = "ignore"

        def model_dump(self):
            return self.dict()

else:
    class RuntimeSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
        )
