"""High-level ZBrush operations for the zb MCP server.

Every op here rides the bridge's execute_python method, because the ZBrush
plugin only implements 15 fixed RPC methods and has no generic palette call.

Two rules baked into every script:

* Palette paths are resolved at call time. zbc.exists() is state dependent --
  "Tool:Geometry:ZRemesher" only exists while a polymesh is active in edit
  mode -- so each op probes a candidate list and reports a structured
  path_not_found instead of pressing nothing.
* result is always a JSON string. The bridge coerces the script's result with
  str(), so anything else would come back as Python repr.

Each entry in OPS is: name -> {params, body, timeout, annotations}.
PRELUDE is prepended to every body; it exposes P (the tool arguments),
_first, _do, _num and _require_mesh.
"""

PRELUDE = '''
import json

P = params


def _first(paths):
    for p in paths:
        try:
            if zbc.exists(p):
                return p
        except Exception:
            pass
    return None


def _do(paths, what, action="press", value=None):
    path = _first(paths)
    if path is None:
        raise RuntimeError(json.dumps({
            "error": "path_not_found",
            "what": what,
            "probed": list(paths),
            "hint": "Palette paths are state dependent: load a mesh and turn on "
                    "Transform:Edit first, then retry. Use zbrush_palette with "
                    "action=exists to confirm the real path before pressing it.",
        }))
    if action == "press":
        zbc.press(path)
    elif action == "set":
        zbc.set(path, value)
    elif action == "get":
        return zbc.get(path)
    return path


def _num(value, default=None):
    if value is None:
        return default
    return int(value) if float(value).is_integer() else float(value)


def _one(prop):
    """Read one query_mesh3d property; the SDK returns a one-element list."""
    try:
        value = zbc.query_mesh3d(int(prop))
    except Exception:
        return None
    if isinstance(value, (list, tuple)):
        return float(value[0]) if value else None
    return float(value)


def _counts():
    points = _one(0)
    faces = _one(1)
    return (int(points) if points is not None else None,
            int(faces) if faces is not None else None)


def _stats():
    points, faces = _counts()
    out = {"points": points, "faces": faces}
    for key, fn in (("area", "get_polymesh3d_area"), ("volume", "get_polymesh3d_volume")):
        try:
            out[key] = round(float(getattr(zbc, fn)()), 4)
        except Exception:
            pass
    return out


def _require_mesh():
    points, faces = _counts()
    if not points or not faces:
        raise RuntimeError(json.dumps({
            "error": "no_mesh",
            "points": points,
            "faces": faces,
            "hint": "The active subtool has no geometry. Import or create one with "
                    "zbrush_import, or select a subtool that has geometry.",
        }))
    return points, faces


class _quiet(object):
    """Hide ZBrush progress dialogs while a long operation runs."""

    def __enter__(self):
        try:
            zbc.show_actions(0)
        except Exception:
            pass
        return self

    def __exit__(self, *exc_info):
        try:
            zbc.show_actions(1)
        except Exception:
            pass
        return False


def _hard_do(paths, what):
    """Press a path that may open a modal progress dialog."""
    with _quiet():
        return _do(paths, what)


def _done(**payload):
    payload.setdefault("ok", True)
    return json.dumps(payload)
'''

_OPS = {}


def _op(name, params, body, timeout=600, read_only=False, destructive=False):
    _OPS[name] = {
        "params": params,
        "body": body,
        "timeout": timeout,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }


# --- escape hatch ----------------------------------------------------------- #

_op("zbrush_palette", {
    "action": {"type": "string", "enum": ["exists", "press", "set", "get"]},
    "path": {"type": "string"},
    "value": {"type": "number"},
}, '''
action = P["action"]
path = P["path"]
exists = bool(zbc.exists(path))
if not exists:
    raise RuntimeError(json.dumps({"error": "path_not_found", "path": path,
                                   "hint": "state dependent; check the palette manually"}))
if action == "exists":
    result = _done(path=path, exists=True)
elif action == "press":
    zbc.press(path)
    result = _done(path=path, pressed=True)
elif action == "set":
    if P.get("value") is None:
        raise RuntimeError(json.dumps({"error": "missing_value", "path": path}))
    zbc.set(path, _num(P["value"]))
    result = _done(path=path, value=_num(P["value"]))
else:
    result = _done(path=path, value=str(zbc.get(path)))
''', timeout=120)

# --- form -------------------------------------------------------------- #

_op("zbrush_dynamesh", {
    "resolution": {"type": "integer"},
}, '''
_require_mesh()
before = _stats()
if P.get("resolution"):
    _do(["Tool:Geometry:Resolution", "Tool:Geometry:DynaMesh:Resolution"],
        "DynaMesh resolution", "set", int(P["resolution"]))
used = _hard_do(["Tool:Geometry:DynaMesh"], "DynaMesh")
after = _stats()
result = _done(before=before, after=after, pressed=used)
''', timeout=1800)

_op("zbrush_zremesher", {
    "target_faces": {"type": "integer"},
    "keep_groups": {"type": "boolean"},
    "freeze_border": {"type": "boolean"},
}, '''
_require_mesh()
before = _stats()
if P.get("target_faces"):
    target = int(P["target_faces"])
    if not 1000 <= target <= 100000:
        raise RuntimeError(json.dumps({
            "error": "bad_target_faces",
            "value": target,
            "hint": "ZRemesher accepts 1000-100000 faces; the palette control is in thousands.",
        }))
    _do(["Tool:Geometry:ZRemesher:Target Polygons Count",
         "Tool:Geometry:Target Polygons Count"],
        "target polygon count", "set", target / 1000.0)
if P.get("keep_groups"):
    _do(["Tool:Geometry:Keep Groups", "Tool:Geometry:ZRemesher:Keep Groups"],
        "keep groups", "press")
if P.get("freeze_border"):
    _do(["Tool:Geometry:Freeze Border", "Tool:Geometry:ZRemesher:Freeze Border"],
        "freeze border", "press")
used = _hard_do(["Tool:Geometry:ZRemesher"], "ZRemesher")
after = _stats()
result = _done(before=before, after=after, pressed=used)
''', timeout=1800)

_op("zbrush_polygroups", {
    "action": {"type": "string", "enum": ["auto", "normals", "split"]},
}, '''
_require_mesh()
paths = {
    "auto": ["Tool:Polygroups:Auto Groups"],
    "normals": ["Tool:Polygroups:Groups By Normals"],
    "split": ["Tool:Geometry:Groups Split", "Tool:Polygroups:Groups Split"],
}[P["action"]]
used = _do(paths, "polygroups " + P["action"])
result = _done(pressed=used, subtools=int(zbc.get_subtool_count()))
''', destructive=True)

_op("zbrush_mask", {
    "action": {"type": "string", "enum": ["all", "clear", "inverse", "blur"]},
    "intensity": {"type": "integer"},
}, '''
_require_mesh()
if P.get("intensity") is not None:
    _do(["Tool:Masking:Mask Intensity"], "mask intensity", "set", int(P["intensity"]))
paths = {
    "all": ["Tool:Masking:Mask All", "Tool:Masking:Mask All Polygroups"],
    "clear": ["Tool:Masking:Clear"],
    "inverse": ["Tool:Masking:Inverse"],
    "blur": ["Tool:Masking:Blur Mask", "Tool:Masking:Blur"],
}[P["action"]]
result = _done(pressed=_do(paths, "mask " + P["action"]))
''')

_op("zbrush_morph", {
    "action": {"type": "string", "enum": ["store", "restore", "delete"]},
}, '''
_require_mesh()
paths = {
    "store": ["Tool:Morph Target:Store"],
    "restore": ["Tool:Morph Target:Restore"],
    "delete": ["Tool:Morph Target:Delete"],
}[P["action"]]
result = _done(pressed=_do(paths, "morph " + P["action"]))
''')

_op("zbrush_layers", {
    "action": {"type": "string", "enum": ["new", "bake_all"]},
}, '''
_require_mesh()
paths = {"new": ["Tool:Layers:New"], "bake_all": ["Tool:Layers:Bake All"]}
result = _done(pressed=_do(paths[P["action"]], "layer " + P["action"]))
''', destructive=True)

_op("zbrush_uv_unwrap", {}, '''
_require_mesh()
used = _hard_do(["Tool:UV Map:UV Master:Unwrap", "Tool:UV Map:UV Master:Unwrap All"],
                "UV Master unwrap")
result = _done(pressed=used)
''', timeout=1800)

_op("zbrush_project_all", {
    "subtool_level": {"type": "boolean"},
}, '''
_require_mesh()
paths = (["Tool:SubTool:Project All"] if P.get("subtool_level")
         else ["Tool:Modify:ProjectAll", "Tool:SubTool:Project All"])
result = _done(pressed=_hard_do(paths, "Project All"))
''')

_op("zbrush_polypaint_fill", {
    "color": {"type": "array"},
}, '''
_require_mesh()
color = P.get("color") or [255, 255, 255]
if len(color) != 3:
    raise RuntimeError(json.dumps({"error": "bad_color",
                                   "detail": "color needs 3 numbers 0-255"}))
rgb = [max(0, min(255, int(c))) for c in color]
try:
    zbc.set_color("Draw:Rgb", rgb)
except Exception:
    for i, channel in enumerate(("Draw:Rgb R", "Draw:Rgb G", "Draw:Rgb B")):
        try:
            zbc.set(channel, rgb[i])
        except Exception:
            pass
used = _do(["Color:Fill Object"], "polypaint fill")
result = _done(pressed=used, color=rgb)
''')

_op("zbrush_render_bpr", {
    "ao": {"type": "boolean"},
    "width": {"type": "integer"},
    "height": {"type": "integer"},
    "output_path": {"type": "string"},
}, '''
_require_mesh()
if P.get("width"):
    _do(["Document:Width"], "document width", "set", int(P["width"]))
if P.get("height"):
    _do(["Document:Height"], "document height", "set", int(P["height"]))
used = _hard_do(["Render:BPR AO"] if P.get("ao") else ["Render:BPR"], "BPR render")
payload = {"pressed": used}
if P.get("output_path"):
    import os
    path = os.path.abspath(str(P["output_path"]))
    if not path.lower().endswith(".psd"):
        path = path + ".psd"
    with _quiet():
        zbc.set_next_filename(path)
        _do(["Document:Export"], "document export")
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(json.dumps({
            "error": "render_not_saved",
            "path": path,
            "hint": "ZBrush writes documents as PSD; if the file is missing the export "
                    "dialog may have been blocked. Check the ZBrush window.",
        }))
    payload["saved"] = path
    payload["bytes"] = os.path.getsize(path)
result = _done(**payload)
''', timeout=1800)

_op("zbrush_brush", {
    "name": {"type": "string"},
    "size": {"type": "number"},
    "intensity": {"type": "number"},
    "focal_shift": {"type": "number"},
    "stroke": {"type": "string"},
}, '''
ALIASES = {"inflate": "Inflat", "dam_standard": "DamStandard",
           "claybuildup": "ClayBuildup", "clay_buildup": "ClayBuildup",
           "hpolish": "hPolish", "h_polish": "hPolish", "trimdynamic": "TrimDynamic"}
used = None
if P.get("name"):
    raw = str(P["name"])
    cands = [ALIASES.get(raw.lower(), raw), raw]
    paths = []
    for c in cands:
        paths.append("Brush:" + c)
    used = _do(paths, "brush " + raw)
applied = {}
for key, candidates in (("size", ["Draw:Draw Size"]),
                        ("intensity", ["Draw:Z Intensity"]),
                        ("focal_shift", ["Draw:Focal Shift"])):
    if P.get(key) is not None:
        path = _do(candidates, key)
        zbc.set(path, _num(P[key]))
        applied[key] = _num(P[key])
stroke_path = None
if P.get("stroke"):
    s = str(P["stroke"]).lower()
    table = {"freehand": "Stroke:FreeHand", "lazy": "Stroke:Lazy Mouse",
             "lazymouse": "Stroke:Lazy Mouse", "lazy_mouse": "Stroke:Lazy Mouse",
             "lazystep": "Stroke:LazyStep", "lazy_step": "Stroke:LazyStep"}
    stroke_path = _do([table.get(s, "Stroke:" + str(P["stroke"]))], "stroke " + s)
result = _done(brush=used, set=applied, stroke=stroke_path)
''', timeout=120)

_op("zbrush_batch_export", {
    "directory": {"type": "string"},
    "prefix": {"type": "string"},
    "extension": {"type": "string"},
    "overwrite": {"type": "boolean"},
}, '''
import os
_require_mesh()
directory = os.path.abspath(P["directory"]).replace(os.sep, "/")
if not os.path.isdir(directory):
    raise RuntimeError(json.dumps({"error": "bad_directory", "directory": directory,
                                   "hint": "create the folder first; this op does not mkdir"}))
prefix = P.get("prefix") or "subtool"
ext = (P.get("extension") or "obj").lstrip(".").lower()
total = int(zbc.get_subtool_count())
written, skipped = [], []
for index in range(total):
    try:
        zbc.select_subtool(index)
    except Exception as exc:
        skipped.append({"index": index, "reason": "select_failed: " + str(exc)})
        continue
    target = "%s/%s_%02d.%s" % (directory, prefix, index, ext)
    if os.path.exists(target) and not P.get("overwrite"):
        skipped.append({"index": index, "path": target, "reason": "exists"})
        continue
    try:
        zbc.set_next_filename(target)
        zbc.press("Tool:Export")
        written.append(target)
    except Exception as exc:
        skipped.append({"index": index, "path": target, "reason": str(exc)})
result = _done(directory=directory, extension=ext, total=total,
               written=written, skipped=skipped)
''', timeout=1800)

_op("zbrush_stats", {}, '''
_require_mesh()
points, faces = _counts()
payload = {"points": points, "faces": faces, "subtools": int(zbc.get_subtool_count()),
           "active_subtool": int(zbc.get_active_subtool_index()),
           "tool_path": str(zbc.get_active_tool_path())}
for key, fn in (("area", "get_polymesh3d_area"), ("volume", "get_polymesh3d_volume"),
                ("solid", "is_polymesh3d_solid")):
    try:
        value = getattr(zbc, fn)()
        payload[key] = round(float(value), 4) if key != "solid" else bool(value)
    except Exception:
        pass
try:
    payload["bounds"] = [round(float(v), 4) for v in zbc.query_mesh3d(2)]
except Exception:
    pass
result = _done(**payload)
''', timeout=120, read_only=True)

OPS = _OPS
