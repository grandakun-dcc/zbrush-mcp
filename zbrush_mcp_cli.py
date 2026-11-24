from __future__ import annotations

import argparse
import json
import socket

import server


def _doctor(host: str, port: int, timeout: float) -> int:
    status = "reachable"
    result = 0
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        status = "unreachable"
        result = 1
    print(json.dumps({"host": host, "port": port, "status": status}))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zbrush-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="Run the MCP stdio server")
    doctor = subparsers.add_parser("doctor", help="Check the local ZBrush bridge")
    doctor.add_argument("--host", default="127.0.0.1")
    doctor.add_argument("--port", type=int, default=9876)
    doctor.add_argument("--timeout", type=float, default=1.0)

    args = parser.parse_args(argv)
    if args.command == "serve":
        return server.main()
    return _doctor(args.host, args.port, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
