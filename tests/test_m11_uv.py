#!/usr/bin/env python3
import json, os, subprocess, time, sys
PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "tests" else HERE
SERVER = os.path.join(ROOT, "server.py")
OUT = os.path.join(ROOT, "tmp", "out"); os.makedirs(OUT, exist_ok=True)
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

probe = r'''
out = {}
try: out["edit"] = str(zbc.get("Transform:Edit"))
except Exception as e: out["edit"] = "ERR " + str(e)
try: out["uv_before"] = [float(v) for v in zbc.query_mesh3d(3)]
except Exception as e: out["uv_before"] = "ERR " + str(e)

for name in ("Tool:UV Map:Unwrap", "Tool:UVMap:Unwrap", "Zplugin:UV Master:Unwrap",
             "Tool:UV Map:Flatten", "Zplugin:UV Master:Work On Clone"):
    try:
        zbc.press(name); out[name] = "pressed"
    except Exception as e:
        out[name] = "ERR " + str(e)[:80]
    try:
        out[name + " -> uv"] = [float(v) for v in zbc.query_mesh3d(3)]
    except Exception as e:
        out[name + " -> uv"] = "ERR"
try: zbc.update(redraw_ui=True)
except Exception: pass
result = out
'''
err, txt, dt = call("zbrush_execute_python", {"code": probe})
print("== uv probe isError=%s\n%s\n" % (err, txt[:1400]))

mti = os.path.join(OUT, "normal_uv.tif")
err, txt, dt = call("zbrush_bake_map", {"map_type":"Normal","output_path":mti,"width":512,"height":512})
print("== bake %.1fs isError=%s\n   %s" % (dt, err, txt[:400].replace("\n"," ")))
print("   file:", mti, os.path.getsize(mti) if os.path.exists(mti) else "MISSING")
proc.stdin.close(); proc.wait(timeout=15)
