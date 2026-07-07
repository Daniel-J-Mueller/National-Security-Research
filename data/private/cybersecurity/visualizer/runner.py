#!/usr/bin/env python3
"""
Launch the cybersecurity runbook visualizer and print a browser link.
"""

from __future__ import annotations

import argparse
import socket
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import server as visualizer_server


DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8010


def port_is_available(bind: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((bind, port)) != 0


def choose_port(bind: str, preferred_port: int) -> int:
    port = preferred_port
    while port < preferred_port + 100:
        if port_is_available(bind, port):
            return port
        port += 1
    raise RuntimeError(f"No available port found from {preferred_port} to {preferred_port + 99}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the cybersecurity runbook visualizer.")
    parser.add_argument("--bind", default=DEFAULT_BIND, help="Host or IP address to bind to.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Preferred port to listen on.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=visualizer_server.RUNBOOK_OUTPUTS_DIR,
        help="Runbook output directory containing csv/, jsonl/, and optional coords/ subdirectories.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    visualizer_server.configure_runbook_outputs(args.output_dir)
    port = choose_port(args.bind, args.port)
    handler = partial(visualizer_server.VisualizerHandler, directory=str(visualizer_server.VISUALIZER_DIR))
    server = ThreadingHTTPServer((args.bind, port), handler)
    url = f"http://{args.bind}:{port}/"

    print(f"Dock-1: {url}", flush=True)
    print(f"Reading CSV shards from: {visualizer_server.CSV_DIR}", flush=True)
    print(f"Writing quick exports to: {visualizer_server.QUICK_OUTPUT_DIR}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
