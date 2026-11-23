#!/usr/bin/env python3
import json, os, subprocess, sys, time
PY = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OUT = os.path.join(ROOT, "tmp", "out"); os.makedirs(OUT, exist_ok=True)
TT = os.path.join(OUT, "turntable"); os.makedirs(TT, exist_ok=True)
proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
_id = 0
def call(name, args):
    global _id; _id += 1
    t0 = time.time()
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":_id,"method":"tools/call",
        "params":{"name":name,"arguments":args}})+"\n"); proc.stdin.flush()
    r = json.loads(proc.stdout.readline())["result"]
    return r.get("isError", False), r["content"][0]["text"], time.time()-t0
proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":900,"method":"initialize","params":{
  "protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}})+"\n")
proc.stdin.flush(); proc.stdout.readline()

tif = os.path.join(OUT, "normal.tif")
err, txt, dt = call("zbrush_bake_map", {"map_type":"Normal","output_path":tif,"width":512,"height":512})
print("== bake_map %.1fs isError=%s\n   %s" % (dt, err, txt[:400].replace("\n"," ")))
print("   file:", tif, os.path.getsize(tif) if os.path.exists(tif) else "MISSING")

err, txt, dt = call("zbrush_capture_turntable", {"output_dir":TT,"angles":[0,120,240],
                                                 "prefix":"cube","bpr_render":False})
print("\n== capture_turntable %.1fs isError=%s\n   %s" % (dt, err, txt[:400].replace("\n"," ")))
if os.path.isdir(TT):
    for f in sorted(os.listdir(TT)):
        print("   frame:", f, os.path.getsize(os.path.join(TT, f)))

proc.stdin.close(); proc.wait(timeout=15)
print("\nstderr:", proc.stderr.read().strip()[-300:])
