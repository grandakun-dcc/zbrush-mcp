"""Smoke-test the high-level ops (zbrush_palette/stats/...) through a real stdio MCP session.

Mutates nothing but brush settings. Run: py -3 tests/ops_smoke.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(HERE, "server.py")


class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=HERE, text=True, encoding="utf-8", bufsize=1)
        self.id = 0

    def send(self, payload):
        self.p.stdin.write(json.dumps(payload) + "\n")
        self.p.stdin.flush()

    def recv(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server closed: " + (self.p.stderr.read() or "")[-800:])
        return json.loads(line)

    def call(self, method, params=None):
        self.id += 1
        self.send({"jsonrpc": "2.0", "id": self.id, "method": method, "params": params or {}})
        while True:
            msg = self.recv()
            if msg.get("id") == self.id:
                return msg

    def tool(self, name, args=None):
        msg = self.call("tools/call", {"name": name, "arguments": args or {}})
        if "error" in msg:
            return False, msg["error"].get("message", "")
        res = msg["result"]
        text = "".join(c.get("text", "") for c in res.get("content", []))
        return (not res.get("isError")), text

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
        except Exception:
            pass


def main():
    c = Client()
    init = c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "ops-smoke", "version": "0"}})
    proto = init["result"]["protocolVersion"]
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    listing = c.call("tools/list")
    names = [t["name"] for t in listing["result"]["tools"]]
    print("protocol:", proto, "tools:", len(names))
    print("ops present:", [n for n in names if n in ("zbrush_palette", "zbrush_dynamesh", "zbrush_zremesher")])

    checks = []
    ok, text = c.tool("zbrush_palette", {"action": "exists", "path": "Brush:Clay"})
    checks.append(("palette exists Brush:Clay", ok, text))
    # a colourless palette path must be refused with a structured hint, not a traceback
    ok, text = c.tool("zbrush_palette", {"action": "exists", "path": "Bogus:Nothing"})
    checks.append(("palette bogus path refused", not ok, text))
    ok, text = c.tool("zbrush_brush", {"name": "Inflate", "size": 42, "intensity": 60})
    checks.append(("brush alias Inflate -> Inflat", ok, text))
    for label, good, text in checks:
        print(("PASS " if good else "FAIL ") + label + " :: " + " ".join(text.split())[:220])
    c.close()


if __name__ == "__main__":
    main()
