#!/usr/bin/env python3
"""
Serve the repository root over HTTP for local static-file workflows.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the repository root locally over HTTP.",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Host or IP address to bind to. Default: %(default)s",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on. Default: %(default)s",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((args.bind, args.port), handler)

    print(f"Serving {ROOT} at http://{args.bind}:{args.port}/")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
