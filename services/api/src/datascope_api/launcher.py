from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the DataScope Studio local API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DATASCOPE_API_PORT", "8000")))
    parser.add_argument("--log-level", default=os.environ.get("DATASCOPE_API_LOG_LEVEL", "info"))
    args = parser.parse_args(argv)

    os.environ["DATASCOPE_API_HOST"] = args.host
    os.environ["DATASCOPE_API_PORT"] = str(args.port)

    uvicorn.run(
        "datascope_api.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
