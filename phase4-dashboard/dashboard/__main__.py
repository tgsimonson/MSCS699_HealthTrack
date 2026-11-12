"""run the dashboard: python -m dashboard  (api url from HT_API_URL, default http://localhost:8000)"""
from __future__ import annotations

import argparse
import logging
import os

from dashboard.app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="HealthTrack monitoring dashboard")
    ap.add_argument("--host", default=os.getenv("HT_DASH_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("HT_DASH_PORT", "8050")))
    ap.add_argument("--api", default=os.getenv("HT_API_URL", "http://localhost:8000"))
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(args.api)
    print(f"dashboard on http://{args.host}:{args.port}  (api {args.api})")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
