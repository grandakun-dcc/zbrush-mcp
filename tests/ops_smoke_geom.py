"""Geometry ops against the cube fixture. MUTATES the open ZBrush document.

Run: py -3 tests/ops_smoke_geom.py  (adds subtools, then remeshes/masks/exports)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ops_smoke import Client, HERE

CUBE = os.path.join(HERE, "fixtures", "cube.obj")
OUT = os.path.join(HERE, "tmp", "export")


def show(label, ok, text):
    print(("PASS " if ok else "FAIL ") + label + " :: " + " ".join(text.split())[:300])


def main():
    c = Client()
    c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "geom", "version": "0"}})
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    ok, text = c.tool("zbrush_import", {"file_path": CUBE})
    show("import cube", ok, text)
    for name, args in (("zbrush_stats", {}),
                       ("zbrush_polygroups", {"action": "auto"}),
                       ("zbrush_dynamesh", {"resolution": 64}),
                       ("zbrush_zremesher", {"target_faces": 2000}),
                       ("zbrush_morph", {"action": "store"}),
                       ("zbrush_mask", {"action": "all"}),
                       ("zbrush_mask", {"action": "clear"}),
                       ("zbrush_polypaint_fill", {"color": [200, 90, 60]})):
        ok, text = c.tool(name, args)
        show(name + " " + json.dumps(args), ok, text)
    os.makedirs(OUT, exist_ok=True)
    ok, text = c.tool("zbrush_batch_export", {"directory": OUT, "prefix": "cube", "overwrite": True})
    show("batch export", ok, text)
    print("files:", sorted(os.listdir(OUT)))
    c.close()


if __name__ == "__main__":
    main()
