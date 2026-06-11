"""Start the strategy dashboard web server."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the dhan-algo dashboard.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    args = parser.parse_args(argv)

    import uvicorn

    if not os.environ.get("DASHBOARD_API_KEY"):
        print("Warning: DASHBOARD_API_KEY not set — API is open without authentication.")

    uvicorn.run("dashboard.app:app", host=args.host, port=args.port, reload=False)
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
