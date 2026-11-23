"""Map/render ops: uv, project all, layers, brush, BPR render. MUTATES the document.

Run: py -3 tests/ops_smoke_misc.py  (writes tmp/export/bpr_test.psd)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ops_smoke import Client, HERE

OUT = os.path.join(HERE, "tmp", "export")


def show(label, ok, text):
    print(("PASS " if ok else "FAIL ") + label + " :: " + " ".join(text.split())[:400])


def main():
    c = Client()
    c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "misc", "version": "0"}})
    c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    os.makedirs(OUT, exist_ok=True)
    plan = [
        ("zbrush_uv_unwrap", {}),
        ("zbrush_project_all", {"subtool_level": True}),
        ("zbrush_layers", {"action": "new"}),
        ("zbrush_layers", {"action": "bake_all"}),
        ("zbrush_brush", {"name": "DamStandard", "size": 30, "intensity": 70,
                          "focal_shift": 0, "stroke": "lazy"}),
        ("zbrush_render_bpr", {"ao": True, "width": 960, "height": 540,
                               "output_path": os.path.join(OUT, "bpr_test.psd")}),
        ("zbrush_stats", {}),
    ]
    for name, args in plan:
        ok, text = c.tool(name, args)
        show(name + " " + json.dumps(args)[:60], ok, text)
    psd = os.path.join(OUT, "bpr_test.psd")
    print("psd exists:", os.path.isfile(psd), os.path.getsize(psd) if os.path.isfile(psd) else 0)
    c.close()


if __name__ == "__main__":
    main()
