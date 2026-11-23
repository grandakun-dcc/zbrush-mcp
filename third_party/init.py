# >>> dcc-mcp-zbrush managed bootstrap >>>
try:
    import dcc_mcp_zbrush_socket_bridge as _dcc_mcp_zbrush_socket_bridge
except Exception as _dcc_mcp_zbrush_bootstrap_error:
    import json as _dcc_mcp_zbrush_json
    import os as _dcc_mcp_zbrush_os
    import time as _dcc_mcp_zbrush_time
    try:
        _dcc_mcp_zbrush_root = _dcc_mcp_zbrush_os.path.dirname(_dcc_mcp_zbrush_os.path.dirname(_dcc_mcp_zbrush_os.path.abspath(__file__)))
        _dcc_mcp_zbrush_errors = _dcc_mcp_zbrush_os.environ.get('DCC_MCP_ZBRUSH_BOOTSTRAP_ERRORS') or _dcc_mcp_zbrush_os.path.join(_dcc_mcp_zbrush_root, '.dcc-mcp', 'bootstrap-errors.jsonl')
        _dcc_mcp_zbrush_os.makedirs(_dcc_mcp_zbrush_os.path.dirname(_dcc_mcp_zbrush_os.path.abspath(_dcc_mcp_zbrush_errors)), exist_ok=True)
        with open(_dcc_mcp_zbrush_errors, 'a', encoding='utf-8') as _dcc_mcp_zbrush_stream:
            _dcc_mcp_zbrush_stream.write(_dcc_mcp_zbrush_json.dumps({'timestamp': _dcc_mcp_zbrush_time.time(), 'stage': 'sidecar_import', 'reason': str(_dcc_mcp_zbrush_bootstrap_error), 'exception_type': type(_dcc_mcp_zbrush_bootstrap_error).__name__}, sort_keys=True) + '\n')
    except Exception:
        pass
    raise
# <<< dcc-mcp-zbrush managed bootstrap <<<
