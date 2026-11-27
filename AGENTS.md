# Repository guidance

- Keep `server.py` as the MCP protocol and bridge layer.
- Keep `ops.py` as the semantic ZBrush operation layer.
- Do not introduce persistent state or write logs to disk.
- The bridge must remain bound to localhost by default.
- Treat `tests/test_m*.py` and `tests/ops_smoke*.py` as live-ZBrush verification scripts.
- Run `python -m pytest -q` for repeatable unit tests.
- Run live scripts only in a disposable ZBrush document.
- Remove generated PSD, TIF, OBJ, logs, build output, and virtual environments before commit.
