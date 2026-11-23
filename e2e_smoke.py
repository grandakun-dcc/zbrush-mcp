#!/usr/bin/env python3
"""End-to-end smoke test for zbrush-mcp/server.py (stdio MCP -> bridge 9876)."""
import json, os, subprocess, sys, time

PY = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OUT = os.path.join(ROOT, "tmp", "out"); os.makedirs(OUT, exist_ok=True)
TT = os.path.join(OUT, "turntable"); os.makedirs(TT, exist_ok=True)

proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
pid_counter = [0]
notes = []

PROGRESS = []


def rpc(method, params, notify=False):
    if not notify:
        pid_counter[0] += 1
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    if not notify:
        payload["id"] = pid_counter[0]
    proc.stdin.write(json.dumps(payload) + "\n"); proc.stdin.flush()
    if notify:
        return None
    while True:
        # progress notifications arrive interleaved with the response
        line = json.loads(proc.stdout.readline())
        if line.get("method") == "notifications/progress":
            PROGRESS.append(line["params"])
            continue
        return line

def call(name, args=None, token=None):
    params = {"name": name, "arguments": args or {}}
    if token:
        params["_meta"] = {"progressToken": token}
    resp = rpc("tools/call", params)
    res = resp["result"]
    body = res["content"][0]["text"]
    try:
        data = json.loads(body)
    except Exception:
        data = body
    return res.get("isError", False), data

def ok(label, cond, detail=""):
    notes.append(("PASS" if cond else "FAIL", label, detail))
    print("%-4s %-28s %s" % ("PASS" if cond else "FAIL", label, detail))

init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "e2e", "version": "0"}})
rpc("notifications/initialized", {}, notify=True)
ok("initialize", init["result"]["serverInfo"]["name"] == "zbrush")

tools = rpc("tools/list", {})["result"]["tools"]
ok("tools/list", len(tools) == 15, "%d tools" % len(tools))

err, d = call("zbrush_session")
ok("zbrush_session", not err and d.get("bridge", {}).get("ok") is True,
   "pid=%s" % d.get("session", {}).get("pid"))

err, d = call("zbrush_scene")
ok("zbrush_scene", not err, "%s / %s subtools" % (d.get("active_tool"), d.get("subtool_count")))

err, d = call("zbrush_import", {"file_path": os.path.join(ROOT, "fixtures", "cube.obj")})
ok("zbrush_import", not err, "%s" % (d.get("subtool_name") or d.get("message", ""))[:60])

err, d = call("zbrush_subdivide", {"subdivision_levels": 1})
ok("zbrush_subdivide", not err and d.get("subdivision_levels", 0) >= 1,
   "sdiv=%s" % d.get("subdivision_levels"))

err, d = call("zbrush_mesh_inspect")
ok("zbrush_mesh_inspect", not err and d.get("face_count", 0) > 0,
   "%s pts / %s faces" % (d.get("point_count"), d.get("face_count")))

obj = os.path.join(OUT, "e2e_export.obj")
err, d = call("zbrush_export_obj", {"output_path": obj})
ok("zbrush_export_obj", not err and os.path.exists(obj), "%s B" % (os.path.getsize(obj) if os.path.exists(obj) else 0))

err, d = call("zbrush_remesh", {"target_face_count": 2000, "duplicate": True})
ok("zbrush_remesh", not err, "faces %s -> %s" % (d.get("face_count_before"), d.get("face_count_after")))

err, d = call("zbrush_subdivide", {"subdivision_levels": 2})
err, uv = call("zbrush_mesh_inspect")
has_uv = bool(uv.get("has_uvs", uv.get("uv_bounds") and any(uv.get("uv_bounds") or [])))
if not has_uv:
    notes.append(("SKIP", "zbrush_bake_map", "no UV on this subtool (see README precondition 2)"))
    print("%-4s %-28s %s" % ("SKIP", "zbrush_bake_map", "no UV on this subtool"))
else:
    err2, d2 = call("zbrush_bake_map", {"map_type": "Normal",
                                        "output_path": os.path.join(OUT, "e2e_normal.tif"),
                                        "width": 512, "height": 512})
    ok("zbrush_bake_map", not err2 and os.path.exists(d2.get("output_path", "")),
       "%s" % (d2.get("error") or ("%s B" % d2.get("bytes"))))

err, d = call("zbrush_capture_turntable", {"output_dir": TT, "angles": [0, 120, 240],
                                           "prefix": "e2e", "bpr_render": False}, token="e2e-progress")
ok("zbrush_capture_turntable", not err and len(d.get("frames", [])) == 3,
   "%s frames" % len(d.get("frames", [])))

ok("notifications/progress", len(PROGRESS) >= 2,
   "%d progress events: %s" % (len(PROGRESS),
                              [p.get("message") for p in PROGRESS][:3]))

err, d = call("zbrush_execute_python", {"code": "result = 6 * 7"})
ok("zbrush_execute_python", (not err) and "42" in json.dumps(d), "result 42")

proc.stdin.close(); proc.wait(timeout=15)
fails = [n for n in notes if n[0] == "FAIL"]
skips = [n for n in notes if n[0] == "SKIP"]
print("\n%d passed, %d failed, %d skipped" % (len(notes) - len(fails) - len(skips), len(fails), len(skips)))
sys.exit(1 if fails else 0)
