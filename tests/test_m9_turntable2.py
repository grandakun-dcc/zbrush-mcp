#!/usr/bin/env python3
import json, os, subprocess, time, sys
PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OUT = os.path.join(ROOT, "tmp", "out"); TT = os.path.join(OUT, "turntable")
os.makedirs(TT, exist_ok=True)
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

code = r'''
out = {}
try:
    out["before"] = str(zbc.get("Transform:Edit"))
except Exception as e:
    out["before"] = "ERR " + str(e)
try:
    zbc.set("Transform:Edit", 1)
    out["set"] = "ok"
except Exception as e:
    out["set"] = "ERR " + str(e)
try:
    out["after"] = str(zbc.get("Transform:Edit"))
except Exception as e:
    out["after"] = "ERR " + str(e)
result = out
'''
err, txt, dt = call("zbrush_execute_python", {"code": code})
print("== edit toggle isError=%s\n%s\n" % (err, txt[:500]))

err, txt, dt = call("zbrush_capture_turntable", {"output_dir":TT,"angles":[0,120,240],
                                                 "prefix":"cube","bpr_render":False})
print("== turntable %.1fs isError=%s\n   %s\n" % (dt, err, txt[:500].replace("\n"," ")))
if os.path.isdir(TT):
    fs = sorted(os.listdir(TT))
    print("   frames:", len(fs))
    for f in fs: print("   ", f, os.path.getsize(os.path.join(TT, f)))
proc.stdin.close(); proc.wait(timeout=15)
