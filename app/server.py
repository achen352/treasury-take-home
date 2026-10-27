"""Production entry point: python -m app.server"""

from typing import Any

import uvicorn

from app.config import Settings


def uvicorn_options(settings: Settings) -> dict[str, Any]:
    return {
        "app": "app.main:create_app",
        "factory": True,
        # Inside the container the app must listen on all interfaces; the platform
        # proxy is the only thing that can reach it.
        "host": "0.0.0.0",  # noqa: S104  # nosec B104
        "port": settings.port,
        "server_header": False,
        "proxy_headers": True,
        "forwarded_allow_ips": settings.forwarded_allow_ips,
    }


def main() -> None:
    uvicorn.run(**uvicorn_options(Settings()))


if __name__ == "__main__":
    main()
