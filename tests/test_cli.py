import ast
import json
import re
import socket
from pathlib import Path

import zbrush_mcp_cli


def test_cli_syntax_is_compatible_with_python_39():
    source = Path(zbrush_mcp_cli.__file__).read_text(encoding="utf-8")

    ast.parse(source, feature_version=(3, 9))


def test_repository_has_no_personal_python_path():
    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "README.md",
        root / "e2e_smoke.py",
        *sorted((root / "tests").glob("test_m*.py")),
    ]

    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        assert re.search(r"C:\\+Users\\+Admin", content) is None, path


def test_doctor_reports_unreachable_bridge(capsys):
    result = zbrush_mcp_cli.main(
        ["doctor", "--host", "127.0.0.1", "--port", "1", "--timeout", "0.05"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload == {
        "host": "127.0.0.1",
        "port": 1,
        "status": "unreachable",
    }


def test_doctor_reports_reachable_bridge(capsys):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        result = zbrush_mcp_cli.main(
            ["doctor", "--host", "127.0.0.1", "--port", str(port)]
        )
    finally:
        listener.close()

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "host": "127.0.0.1",
        "port": port,
        "status": "reachable",
    }


def test_serve_delegates_to_existing_server(monkeypatch):
    monkeypatch.setattr(zbrush_mcp_cli.server, "main", lambda: 7)

    assert zbrush_mcp_cli.main(["serve"]) == 7
