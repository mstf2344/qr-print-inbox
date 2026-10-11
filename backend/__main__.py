import uvicorn

from backend.config import Settings
from backend.main import create_app


def main() -> None:
    settings = Settings()
    # Tokens occur in status URLs. Never write request paths to access logs.
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
