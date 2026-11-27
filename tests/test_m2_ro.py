#!/usr/bin/env python3
"""M2 (read-only half): drive the real ZBrush through the server."""
import json, subprocess, os, sys

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")
proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
_id = 0
def rpc(method, params=None):
    global _id
    _id += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id, "method": method,
                                 "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

def call(name, args=None):
    r = rpc("tools/call", {"name": name, "arguments": args or {}})["result"]
    return r.get("isError", False), r["content"][0]["text"]

rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})

ok = True
for name, args in [("zbrush_session", {}), ("zbrush_scene", {}), ("zbrush_subtools_list", {}),
                   ("zbrush_subtool_status", {}), ("zbrush_mesh_inspect", {})]:
    err, txt = call(name, args)
    ok = ok and not err
    print("== %s  isError=%s" % (name, err))
    print(txt[:900].replace("\n", " ")[:900], "\n")

proc.stdin.close()
proc.wait(timeout=10)
print("stderr:", proc.stderr.read().strip()[:400])
print("RESULT:", "ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
