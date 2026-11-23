# third_party

`dcc_mcp_zbrush_socket_bridge.py` 与 `init.py` 不是本项目原创，它们来自
[dcc-mcp/dcc-mcp-zbrush](https://github.com/dcc-mcp/dcc-mcp-zbrush)（MIT License），
是安装到 ZBrush Python 目录后、在 ZBrush 内部开 127.0.0.1:9876 JSON-RPC 端口的那个插件。

放在这里的目的：
1. 让人知道 server.py 依赖的 16 个桥方法从哪来、怎么实现；
2. 离线安装时可以照抄到 `%APPDATA%\Maxon\Maxon ZBrush <version>\Python\`。

本项目没有修改这两个文件。升级 ZBrush 或重装插件后如果端口行为变了，先比对这份副本。
