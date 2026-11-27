#!/usr/bin/env python3
"""M1 acceptance: drive server.py over stdio the way a real MCP client would."""
import json, subprocess, sys, os

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")

proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

_id = 0
def rpc(method, params=None, notify=False):
    global _id
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if not notify:
        _id += 1
        msg["id"] = _id
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if notify:
        return None
    line = proc.stdout.readline()
    if not line:
        err = proc.stderr.read()
        raise SystemExit("server died: " + err[-2000:])
    return json.loads(line)

ok = True
def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    ok = ok and cond

init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "m1-test", "version": "0"}})
res = init.get("result", {})
check("initialize", res.get("protocolVersion") == "2025-06-18" and res.get("serverInfo", {}).get("name") == "zbrush",
      res.get("serverInfo"))
check("capabilities.tools", res.get("capabilities", {}).get("tools") is not None)

rpc("notifications/initialized", None, notify=True)

tl = rpc("tools/list").get("result", {})
tools = tl.get("tools", [])
names = sorted(t["name"] for t in tools)
check("tools/list count=15", len(tools) == 15, len(tools))
check("tool names", names == sorted([
    "zbrush_session","zbrush_scene","zbrush_subtools_list","zbrush_subtool_status","zbrush_mesh_inspect",
    "zbrush_subtool_select","zbrush_subdivide","zbrush_remesh","zbrush_import","zbrush_export_obj",
    "zbrush_bake_map","zbrush_brush_create","zbrush_brush_load","zbrush_capture_turntable",
    "zbrush_execute_python"]), names)
check("every tool has schema", all(t.get("inputSchema", {}).get("type") == "object" for t in tools))
check("annotations present", all("annotations" in t for t in tools))

p = rpc("ping")
check("ping", "result" in p and p["result"] == {})

sess = rpc("tools/call", {"name": "zbrush_session", "arguments": {}})["result"]
txt = sess["content"][0]["text"]
print("\n--- zbrush_session ---\n" + txt[:700] + "\n")
check("session call returns content", bool(txt))
print("isError:", sess.get("isError"))

bad = rpc("tools/call", {"name": "nope", "arguments": {}})["result"]
check("unknown tool -> isError", bad.get("isError") is True, bad["content"][0]["text"][:120])

argerr = rpc("tools/call", {"name": "zbrush_subtool_select", "arguments": {}})["result"]
check("missing arg -> isError", argerr.get("isError") is True, argerr["content"][0]["text"][:120])

unknown_param = rpc("tools/call", {"name": "zbrush_scene", "arguments": {"bogus": 1}})["result"]
check("unknown param -> isError", unknown_param.get("isError") is True, unknown_param["content"][0]["text"][:120])

nf = rpc("bogus/method")
check("unknown method -> -32601", nf.get("error", {}).get("code") == -32601, nf.get("error"))

proc.stdin.close()
proc.wait(timeout=10)
err = proc.stderr.read()
print("\n--- stderr ---\n" + err.strip())
print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
