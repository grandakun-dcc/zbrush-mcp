#!/usr/bin/env python3
import json, subprocess, os, sys
PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OBJ = os.path.join(ROOT, "fixtures", "cube.obj")
proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
_id = 0
def call(name, args=None):
    global _id
    _id += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id, "method": "tools/call",
                                 "params": {"name": name, "arguments": args or {}}}) + "\n")
    proc.stdin.flush()
    r = json.loads(proc.stdout.readline())["result"]
    return r.get("isError", False), r["content"][0]["text"]

proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":900,"method":"initialize","params":{
  "protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}})+"\n")
proc.stdin.flush(); proc.stdout.readline()

for name, args in [("zbrush_import", {"file_path": OBJ}),
                   ("zbrush_scene", {}),
                   ("zbrush_subtools_list", {}),
                   ("zbrush_mesh_inspect", {}),
                   ("zbrush_subtool_status", {"index": 0})]:
    err, txt = call(name, args)
    print("== %s isError=%s" % (name, err))
    print(txt[:700].replace("\n", " "), "\n")

proc.stdin.close(); proc.wait(timeout=10)
print("stderr:", proc.stderr.read().strip()[:300])
