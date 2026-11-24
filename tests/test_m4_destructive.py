#!/usr/bin/env python3
"""M2 destructive half: run the scene-changing tools on the throwaway cube."""
import json, os, subprocess, sys, time

PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OUT = os.path.join(ROOT, "tmp", "out")
os.makedirs(OUT, exist_ok=True)

proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
_id = 0
def call(name, args=None, timeout=None):
    global _id
    _id += 1
    t0 = time.time()
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id, "method": "tools/call",
                                 "params": {"name": name, "arguments": args or {}}}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    dt = time.time() - t0
    if not line:
        return True, "SERVER DIED: " + proc.stderr.read()[-800:], dt
    r = json.loads(line)["result"]
    return r.get("isError", False), r["content"][0]["text"], dt

proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 900, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}) + "\n")
proc.stdin.flush(); proc.stdout.readline()

def show(name, args, note=""):
    err, txt, dt = call(name, args)
    print("== %-26s %5.1fs isError=%s %s" % (name, dt, err, note))
    print("   " + txt[:560].replace("\n", " "))
    return err, txt

results = {}
results["subdivide"] = show("zbrush_subdivide", {"subdivision_levels": 2, "polish": False})
obj = os.path.join(OUT, "cube_export.obj")
results["export"] = show("zbrush_export_obj", {"output_path": obj})
print("   file:", obj, os.path.getsize(obj) if os.path.exists(obj) else "MISSING")

results["remesh"] = show("zbrush_remesh", {"target_face_count": 5000, "duplicate": True})
show("zbrush_subtools_list", {}, "(after remesh)")

png = os.path.join(OUT, "normal.png")
results["bake"] = show("zbrush_bake_map", {"map_type": "Normal", "output_path": png,
                                           "width": 512, "height": 512})
print("   file:", png, os.path.getsize(png) if os.path.exists(png) else "MISSING")

tt = os.path.join(OUT, "turntable")
results["turntable"] = show("zbrush_capture_turntable", {"output_dir": tt, "angles": [0, 120, 240],
                                                         "prefix": "cube", "bpr_render": False})
if os.path.isdir(tt):
    for f in sorted(os.listdir(tt)):
        print("   frame:", f, os.path.getsize(os.path.join(tt, f)))

proc.stdin.close(); proc.wait(timeout=15)
print("\nstderr tail:", proc.stderr.read().strip()[-400:])
fails = [k for k, (e, _) in results.items() if e]
print("\nRESULT:", "ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(0 if not fails else 1)
