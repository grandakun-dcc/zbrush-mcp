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
for label, fn in (("press", lambda: zbc.press("Transform:Edit")),
                  ("press2", lambda: zbc.press("Tool:Edit")),
                  ("set_int", lambda: zbc.set("Transform:Edit", 1))):
    try:
        fn(); out[label] = "ok"
    except Exception as e:
        out[label] = "ERR " + str(e)
    try:
        out[label + "_now"] = str(zbc.get("Transform:Edit"))
    except Exception as e:
        out[label + "_now"] = "ERR " + str(e)
try:
    zbc.update(redraw_ui=True)
except Exception as e:
    out["update"] = str(e)
result = out
'''
err, txt, dt = call("zbrush_execute_python", {"code": code})
print("== toggle isError=%s\n%s\n" % (err, txt[:700]))

err, txt, dt = call("zbrush_capture_turntable", {"output_dir":TT,"angles":[0,120,240],
                                                 "prefix":"cube","bpr_render":False})
print("== turntable %.1fs isError=%s\n   %s\n" % (dt, err, txt[:400].replace("\n"," ")))
if os.path.isdir(TT):
    for f in sorted(os.listdir(TT)): print("   ", f, os.path.getsize(os.path.join(TT,f)))
proc.stdin.close(); proc.wait(timeout=15)
