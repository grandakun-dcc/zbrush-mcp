#!/usr/bin/env python3
"""ZBrush MCP server — standard stdio transport, pure stdlib.

Chain:  MCP client --stdio(JSON-RPC/line)--> this server --TCP 127.0.0.1:9876--> ZBrush plugin.

Design rules
- No persistent state: no sqlite, no registry, no log files. Logs go to stderr.
- One bridge request in flight at a time (the bridge is serial).
- Bridge error codes are forwarded with their retry semantics intact.
"""

import json
import os
import socket
import sys
import threading
import time
import traceback

SERVER_NAME = "zbrush"
SERVER_VERSION = "0.1.0"
BRIDGE_HOST = os.environ.get("ZBRUSH_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("ZBRUSH_BRIDGE_PORT", "9876"))
CONNECT_TIMEOUT = float(os.environ.get("ZBRUSH_CONNECT_TIMEOUT", "5"))
DEFAULT_TIMEOUT = float(os.environ.get("ZBRUSH_TIMEOUT", "120"))
LONG_TIMEOUT = float(os.environ.get("ZBRUSH_LONG_TIMEOUT", "900"))

SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]


def log(msg):
    sys.stderr.write("[zbrush-mcp] %s\n" % msg)
    sys.stderr.flush()


_OUT_LOCK = threading.Lock()


def send(msg):
    """Write one JSON-RPC message to the client (thread-safe, always UTF-8).

    ZBrush returns localized strings (Chinese on a zh-CN install). Encoding them
    with the console code page would put GBK bytes on the wire, which any MCP
    client decoding UTF-8 rejects. Encode explicitly and escape as a fallback.
    """
    try:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    except (UnicodeEncodeError, ValueError):
        data = (json.dumps(msg, ensure_ascii=True) + "\n").encode("utf-8")
    with _OUT_LOCK:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write(data)
            buf.flush()
        else:
            sys.stdout.write(data.decode("utf-8"))
            sys.stdout.flush()


def send_progress(token, progress, message=None):
    params = {"progressToken": token, "progress": progress}
    if message:
        params["message"] = message
    send({"jsonrpc": "2.0", "method": "notifications/progress", "params": params})


class _Heartbeat(object):
    """Emit periodic progress while a blocking bridge call is in flight."""

    def __init__(self, token, label):
        self.token = token
        self.label = label
        self.started = time.time()
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if self.token is None:
            return self
        send_progress(self.token, 0, "%s: sent to ZBrush" % self.label)
        self._thread = threading.Thread(target=self._run, name="progress", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(10.0):
            elapsed = time.time() - self.started
            send_progress(self.token, int(elapsed), "%s: still waiting (%.0fs)" % (self.label, elapsed))

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.token is None:
            return False
        elapsed = time.time() - self.started
        if exc_type is None:
            send_progress(self.token, int(elapsed) + 1, "%s: finished in %.1fs" % (self.label, elapsed))
        else:
            send_progress(self.token, int(elapsed) + 1, "%s: failed after %.1fs" % (self.label, elapsed))
        return False


# --------------------------------------------------------------------------- #
# bridge client
# --------------------------------------------------------------------------- #

class BridgeError(Exception):
    def __init__(self, code, message, data=None, kind="bridge"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        self.kind = kind


def _next_id():
    _next_id.value += 1
    return _next_id.value


_next_id.value = 0


def bridge_call(method, params=None, timeout=None):
    """Send one JSON-RPC request to the ZBrush bridge and return its result."""
    timeout = float(timeout or DEFAULT_TIMEOUT)
    params = dict(params or {})
    if method != "ping":
        deadline = time.time() + timeout - 2.0
        if deadline > time.time():
            params.setdefault("deadline_unix_ms", int(deadline * 1000))
    payload = {"jsonrpc": "2.0", "id": _next_id(), "method": method, "params": params}
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        sock = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=CONNECT_TIMEOUT)
    except OSError as exc:
        raise BridgeError(
            "ECONNREFUSED",
            "cannot connect to the ZBrush bridge at %s:%d (%s)" % (BRIDGE_HOST, BRIDGE_PORT, exc),
            {"hint": "ZBrush is probably not running, or the bridge plugin is not loaded. "
                     "Start ZBrush and confirm the plugin wrote a listening socket on port %d." % BRIDGE_PORT},
            kind="connect",
        )

    try:
        sock.settimeout(timeout)
        sock.sendall(raw)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise BridgeError("ECONNRESET", "bridge closed the connection before replying", kind="connect")
            buf += chunk
        line = buf.split(b"\n", 1)[0]
    except socket.timeout:
        raise BridgeError(
            "ETIMEDOUT",
            "no reply from the bridge within %.0fs" % timeout,
            {"hint": "The call may still be executing on ZBrush's main thread. "
                     "Check state with zbrush_session before retrying."},
            kind="timeout",
        )
    finally:
        try:
            sock.close()
        except OSError:
            pass

    try:
        msg = json.loads(line.decode("utf-8", "replace"))
    except ValueError:
        raise BridgeError("EBADJSON", "bridge replied with non-JSON: %r" % line[:200], kind="protocol")

    err = msg.get("error")
    if err:
        raise BridgeError(err.get("code"), err.get("message") or "bridge error", err.get("data"))
    return msg.get("result")


# --------------------------------------------------------------------------- #
# tool table
# --------------------------------------------------------------------------- #

def _schema(props, required=None):
    s = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    s["additionalProperties"] = False
    return s


TOOLS = [
    {
        "name": "zbrush_session",
        "description": "Read ZBrush session state: version, whether the bridge is responding, "
                       "which method currently holds the bridge, active tool and subtool count. "
                       "Use this first, and after any timeout, before retrying.",
        "bridge_method": "get_session_info",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({}),
    },
    {
        "name": "zbrush_scene",
        "description": "Read the current document: active tool path, subtool count, selected subtool index. "
                       "Does not modify the scene.",
        "bridge_method": "get_scene_info",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({}),
    },
    {
        "name": "zbrush_subtools_list",
        "description": "List every subtool of the active tool with index, name and visibility/lock flags.",
        "bridge_method": "list_subtools",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({}),
    },
    {
        "name": "zbrush_subtool_status",
        "description": "Read one subtool's status: face/point counts, subdivision level, flags. "
                       "Defaults to the active subtool when index is omitted.",
        "bridge_method": "get_subtool_status",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({
            "index": {"type": "integer", "minimum": 0,
                      "description": "Subtool index; omit for the active subtool."},
        }),
    },
    {
        "name": "zbrush_mesh_inspect",
        "description": "Inspect the active subtool's mesh: counts, bounding box, polygroups, symmetry state.",
        "bridge_method": "inspect_active_mesh",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({}),
    },
    {
        "name": "zbrush_subtool_select",
        "description": "Make one subtool active by index. Does not alter geometry.",
        "bridge_method": "select_subtool",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({
            "index": {"type": "integer", "minimum": 0, "description": "Subtool index to activate."},
        }, ["index"]),
    },
    {
        "name": "zbrush_subdivide",
        "description": "Refine the active subtool by subdivision levels (SDiv), optionally polishing "
                       "and inflating. Can multiply the face count by 4 per level.",
        "bridge_method": "refine_active_subtool",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "subdivision_levels": {"type": "integer", "minimum": 1, "description": "Levels to add."},
            "polish": {"type": "boolean", "description": "Apply polish after subdividing."},
            "inflate": {"type": "number", "description": "Inflation amount."},
        }, ["subdivision_levels"]),
    },
    {
        "name": "zbrush_remesh",
        "description": "ZRemesher the active subtool to a target face count. DESTRUCTIVE: replaces the "
                       "current topology (set duplicate=true to keep the original as a new subtool). "
                       "Long running; may take minutes.",
        "bridge_method": "remesh_active_subtool",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "target_face_count": {"type": "integer", "minimum": 16, "description": "Desired face count."},
            "duplicate": {"type": "boolean", "description": "Keep the source subtool (recommended)."},
        }, ["target_face_count"]),
    },
    {
        "name": "zbrush_import",
        "description": "Import a mesh file (OBJ/FBX/... as supported by ZBrush) into the current document. "
                       "Use an absolute path on the machine running ZBrush.",
        "bridge_method": "import_to_scene",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "file_path": {"type": "string", "description": "Absolute path of the file to import."},
        }, ["file_path"]),
    },
    {
        "name": "zbrush_export_obj",
        "description": "Export the active subtool as OBJ to an absolute path. Overwrites an existing file.",
        "bridge_method": "export_active_subtool_obj",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "output_path": {"type": "string", "description": "Absolute .obj path to write."},
        }, ["output_path"]),
    },
    {
        "name": "zbrush_bake_map",
        "description": "Bake a map (normal/displacement/AO/...) from the active subtool to an image file. "
                       "Requires the active subtool to have usable UVs (unwrap first). "
                       "Long running; blocks ZBrush's UI while it works.",
        "bridge_method": "bake_active_subtool_map",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "map_type": {"type": "string", "description": "Map kind, e.g. Normal, Displacement, AO, Cavity."},
            "output_path": {"type": "string", "description": "Absolute path to write; the bridge only accepts .tif or .tiff."},
            "width": {"type": "integer", "minimum": 64},
            "height": {"type": "integer", "minimum": 64},
            "smooth": {"type": "boolean"},
            "border": {"type": "integer", "minimum": 0, "description": "Border padding in pixels."},
        }, ["map_type", "output_path"]),
    },
    {
        "name": "zbrush_brush_create",
        "description": "Create a wrinkle/crease brush asset (ZBP) and write it to an absolute path.",
        "bridge_method": "create_wrinkle_brush",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({
            "output_path": {"type": "string", "description": "Absolute .zbp path to write."},
        }, ["output_path"]),
    },
    {
        "name": "zbrush_brush_load",
        "description": "Load a brush (ZBP) into ZBrush by absolute path and make it active.",
        "bridge_method": "load_wrinkle_brush",
        "timeout": DEFAULT_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": _schema({
            "brush_path": {"type": "string", "description": "Absolute .zbp path to load."},
        }, ["brush_path"]),
    },
    {
        "name": "zbrush_capture_turntable",
        "description": "Render turntable frames of the document and write images into a directory. "
                       "Prefers viewport capture; the active tool must be in 3D Edit mode "
                       "(Transform:Edit = 1) or it fails with EDIT_MODE_REQUIRED. "
                       "This is the visual-evidence path: prefer it over OS screenshots. "
                       "Long running; blocks the UI.",
        "bridge_method": "capture_turntable",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "output_dir": {"type": "string", "description": "Absolute directory for the frames; it must already exist."},
            "angles": {"type": "array", "items": {"type": "number"},
                       "description": "Angle list in degrees; omit for the bridge default."},
            "prefix": {"type": "string", "description": "Filename prefix."},
            "bpr_render": {"type": "boolean", "description": "Use BPR instead of viewport capture."},
            "polyframe": {"type": "boolean", "description": "Render the polyframe."},
        }, ["output_dir"]),
    },
    {
        "name": "zbrush_execute_python",
        "description": "Escape hatch: run Python inside ZBrush's embedded interpreter. 'zbc' is pre-bound "
                       "to zbrush.commands; assign to 'result' to return a value. "
                       "DESTRUCTIVE by nature: it can change or delete anything in the scene.",
        "bridge_method": "execute_python",
        "timeout": LONG_TIMEOUT,
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": _schema({
            "code": {"type": "string", "description": "Python source to execute."},
            "context": {"type": "object", "description": "Extra names injected into the namespace."},
        }, ["code"]),
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------- #
# tools/call
# --------------------------------------------------------------------------- #

def _validate(tool, args):
    schema = tool["inputSchema"]
    props = schema["properties"]
    for key in args:
        if key not in props:
            raise BridgeError(-32602, "unknown parameter %r for %s" % (key, tool["name"]),
                              {"known": sorted(props)})
    for key in schema.get("required", []):
        if key not in args or args[key] is None:
            raise BridgeError(-32602, "missing required parameter %r for %s" % (key, tool["name"]))
    out = {}
    for key, value in args.items():
        if value is None:
            continue
        expected = props[key].get("type")
        if expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
                else:
                    raise BridgeError(-32602, "parameter %r must be an integer" % key)
        elif expected == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BridgeError(-32602, "parameter %r must be a number" % key)
        elif expected == "boolean":
            if not isinstance(value, bool):
                raise BridgeError(-32602, "parameter %r must be a boolean" % key)
        elif expected == "string":
            if not isinstance(value, str):
                raise BridgeError(-32602, "parameter %r must be a string" % key)
        elif expected == "object":
            if not isinstance(value, dict):
                raise BridgeError(-32602, "parameter %r must be an object" % key)
        elif expected == "array":
            if not isinstance(value, list):
                raise BridgeError(-32602, "parameter %r must be an array" % key)
        out[key] = value
    return out


def _explain(exc):
    """Turn a bridge error into an operator-facing message with retry guidance."""
    data = exc.data if isinstance(exc.data, dict) else {}

    if exc.kind == "connect":
        hint = data.get("hint", "")
        return ("ZBrush bridge unreachable.\n%s\n%s\n"
                "Not retried automatically: fix the connection, then call zbrush_session."
                % (exc.message, hint)).strip()

    if exc.kind == "timeout":
        return ("Bridge did not answer in time.\n%s\n%s\n"
                "The operation may still be running inside ZBrush. "
                "Call zbrush_session to check before retrying; do not resubmit blindly."
                % (exc.message, data.get("hint", ""))).strip()

    code = exc.code
    if code == -32001:
        active = data.get("active_method") or "unknown"
        return ("ZBrush bridge is busy running '%s'.\n"
                "RETRYABLE: wait for that call to finish, then retry this one." % active)
    if code == -32004:
        return ("Request expired before ZBrush picked it up (executed=%s).\n"
                "RETRYABLE: nothing ran; send it again." % data.get("executed"))
    if code == -32002:
        return ("Bridge gave up waiting but the work may still be running "
                "(still_running=%s).\nNOT retryable: call zbrush_session first and confirm the scene "
                "state, otherwise you may apply the same operation twice." % data.get("still_running"))
    if code == -32601:
        return ("The ZBrush plugin does not implement this method (%s).\n"
                "The installed bridge is probably older than this server. Do not retry." % exc.message)
    if code == -32602:
        return exc.message if exc.message.startswith("Invalid") else "Invalid arguments: %s" % exc.message
    if code == -32000:
        tb = data.get("traceback") or data.get("trace") or ""
        if "query_mesh3d" in (exc.message or "") and not tb:
            return ("The document has no mesh to inspect (active tool is still the empty "
                    "SimpleBrush document).\nImport or create a subtool first "
                    "(zbrush_import), then call zbrush_mesh_inspect again.\nBridge detail: %s"
                    % exc.message)
        return "ZBrush host exception: %s\n%s" % (exc.message, tb)
    if exc.kind == "protocol":
        return "Bridge protocol error: %s" % exc.message
    return "Bridge error %s: %s" % (code, exc.message)


def call_tool(name, args):
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise BridgeError(-32602, "unknown tool %r" % name, {"known": sorted(TOOLS_BY_NAME)})

    params = _validate(tool, args)
    method = tool["bridge_method"]

    if name == "zbrush_session":
        started = time.time()
        try:
            ping = bridge_call("ping", {}, timeout=10)
            info = bridge_call(method, {}, timeout=tool["timeout"])
        except BridgeError:
            raise
        result = {"bridge": ping, "session": info, "latency_ms": int((time.time() - started) * 1000)}
        return result

    return bridge_call(method, params, timeout=tool["timeout"])


# --------------------------------------------------------------------------- #
# JSON-RPC plumbing
# --------------------------------------------------------------------------- #

def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _text_content(text, is_error):
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


def handle(msg):
    """Return a response dict, or None for notifications."""
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method is None:
        return _error(msg_id, -32600, "missing method")

    if msg_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Drives a running Maxon ZBrush instance over its local bridge. "
                            "Call zbrush_session first; it reports whether the bridge is alive "
                            "and whether another call is currently running.",
        })

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(msg_id, -32602, "arguments must be an object")
        token = (params.get("_meta") or {}).get("progressToken")
        try:
            with _Heartbeat(token, name):
                result = call_tool(name, args)
        except BridgeError as exc:
            log("tool %s failed: %s" % (name, exc.message))
            return _result(msg_id, _text_content(_explain(exc), True))
        except Exception as exc:  # noqa: BLE001 - never kill the server on one bad call
            log("tool %s crashed: %s" % (name, traceback.format_exc()))
            return _result(msg_id, _text_content("Internal server error: %s" % exc, True))
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
        # The bridge reports domain failures as {success: false, message, error} with a
        # successful JSON-RPC envelope; promote those to MCP tool errors so clients see them.
        failed = isinstance(result, dict) and result.get("success") is False
        return _result(msg_id, _text_content(text, failed))

    if method == "resources/list":
        return _result(msg_id, {"resources": []})

    if method == "prompts/list":
        return _result(msg_id, {"prompts": []})

    return _error(msg_id, -32601, "method not found: %s" % method)


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - older/custom streams may lack reconfigure
            pass
    log("ready (bridge %s:%d, %d tools)" % (BRIDGE_HOST, BRIDGE_PORT, len(TOOLS)))
    buf = ""
    while True:
        chunk = sys.stdin.readline()
        if not chunk:
            log("stdin closed, exiting")
            return 0
        buf += chunk
        if not buf.strip():
            buf = ""
            continue
        try:
            msg = json.loads(buf)
        except ValueError:
            # one line may be incomplete: keep buffering until it parses or a newline closes it
            if not buf.endswith("\n"):
                continue
            log("invalid JSON on stdin, ignoring: %r" % buf[:200])
            buf = ""
            continue
        buf = ""
        try:
            response = handle(msg)
        except Exception as exc:  # noqa: BLE001
            log("handler crashed: %s" % traceback.format_exc())
            response = _error(msg.get("id"), -32603, "internal error: %s" % exc)
        if response is not None:
            send(response)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
