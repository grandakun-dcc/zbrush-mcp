# Third-party notices

## dcc-mcp-zbrush bridge

- Upstream: `https://github.com/dcc-mcp/dcc-mcp-zbrush`
- License: MIT
- Reference upstream commit checked during migration: `51a43e57a26504e2f15c24069ef30898cece6a98`
- `third_party/dcc_mcp_zbrush_socket_bridge.py` matches upstream
  `bridge/plugin/mcp_socket_bridge.py` at that commit.
- `third_party/init.py` is a retained installation helper and does not match the
  current upstream package initializer byte-for-byte.

The files are retained for offline installation and interface inspection. The
MCP server does not import them at runtime.
