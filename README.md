# zbrush-mcp

一个**标准 MCP（stdio）**服务器，直连 ZBrush 内置的 JSON-RPC 桥（TCP 127.0.0.1:9876），
不依赖 dcc-mcp 的 sidecar / registry / gateway / job 库。

    DSH (MCP client)  --stdio, one JSON-RPC per line-->  server.py
                      --TCP 127.0.0.1:9876-->  ZBrush 插件 --Python SDK-->  ZBrush

- 无持久状态：日志走 stderr，状态只在内存，产物路径由调用方给绝对路径。
- 不写任何用户目录，因此不受 workspace 写限制。
- 纯标准库，单文件（server.py），Python 3.9+。

## 仓库结构

    server.py                 MCP 服务器本体（唯一需要运行的代码）
    e2e_smoke.py              端到端验收脚本（会改动当前 ZBrush 文档）
    tests/test_m*.py          各里程碑的分步测试（握手、只读、破坏性、转台、烘焙）
    fixtures/cube.obj         测试用立方体
    third_party/              ZBrush 侧插件桥（来自 dcc-mcp-zbrush，MIT），仅作参考与离线安装
    docs/                     设计稿与旧方案记录
    tmp/                      运行产物（已 gitignore）

## 启动

    "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe" server.py

环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| ZBRUSH_BRIDGE_HOST | 127.0.0.1 | 桥地址（只允许本机） |
| ZBRUSH_BRIDGE_PORT | 9876 | 桥端口（与插件一致） |
| ZBRUSH_BRIDGE_TIMEOUT | 1800 | 单个请求等待上限（秒），长活如 remesh/bake 需要 |

## 在 DSH 里注册

    mcp_connector_import_json({ "mcpServers": { "zb": {
      "command": "C:\\Users\\Admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
      "args": ["C:\\Users\\Admin\\Documents\\zbrush-mcp\\server.py"],
      "env": { "ZBRUSH_BRIDGE_PORT": "9876" } } } })

注册后可见 15 个 zb* 工具。

## 两个前置条件（由 ZBrush 侧决定，服务器无法代劳）

1. **Edit 模式**：`Transform:Edit` 必须为 1（在 ZBrush 里点 Edit 按钮）。
   转台截图依赖它；程序化 press 无效，ZBrush 只认真实点击。
2. **烘焙依赖细分栈**：法线/置换等需要该子工具有 SDiv 层级，且要有 UV。
   纯 ZRemesher 结果（无细分）会报 `MAP_NOT_CREATED`；无 UV 报 `UVS_MISSING`。
   顺序：细分 1~2 级 → UV 展开（UV Map 面板 Unwrap）→ 烘焙。

## 工具（15）

只读：zbrush_session / zbrush_scene / zbrush_subtools_list / zbrush_subtool_status / zbrush_mesh_inspect
变更：zbrush_subtool_select / zbrush_subdivide / zbrush_import / zbrush_brush_create / zbrush_brush_load / zbrush_export_obj
破坏性：zbrush_remesh / zbrush_bake_map / zbrush_execute_python
耗时：zbrush_capture_turntable（输出 .psd 帧，可用 ffmpeg 转 PNG）

进度：客户端在 `params._meta.progressToken` 传令牌即可收到 `notifications/progress`（进队一条、每 10 秒心跳、结束一条）。

## 错误语义

桥的错误码原样透传，不一律当失败：

| 码 | 含义 | 可重试 |
| --- | --- | --- |
| -32601 | 未知方法 | 否 |
| -32602 | 参数非法 | 否 |
| -32000 | 宿主异常（data.traceback） | 视情况 |
| -32004 | 已过期，未执行 | 是 |
| -32001 | 桥忙（data.active_method） | 是，稍后 |
| -32002 | 等待超时，仍在跑 | 否，需人工确认 |

领域失败（`success: false`）会升格为 MCP `isError: true`，不会被当成成功。

## 验收脚本

    python e2e_smoke.py

一次跑完 initialize → tools/list → session → scene → import → subdivide → mesh_inspect →
export → remesh → bake（无 UV 时 SKIP）→ turntable → progress → execute_python。

注意：**它会往当前 ZBrush 文档里导入 cube 并改造它**，请在丢弃得了的文档里跑。

最近一次结果：12 passed / 0 failed / 1 skipped，2 条 progress 事件。

## 回滚

只删注册的那条连接即可（mcp_connector_disconnect），不涉及任何文件或系统改动。
插件本身是 dcc-mcp-zbrush 安装的，本项目不修改它。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| BRIDGE_UNREACHABLE | ZBrush 未开 / 插件未加载 / 端口不同 | 在 ZBrush 里确认插件加载，`netstat -ano | findstr :9876` |
| BRIDGE_BUSY | 上一个请求还在跑 | 等它结束再发；区分“可重试”与“超时仍在跑” |
| EDIT_MODE_REQUIRED | 未点 Edit | 在 ZBrush 里点 Edit |
| UVS_MISSING | 无 UV | UV 展开后再烘 |
| MAP_NOT_CREATED | 无细分层级 | 先 subdivide 再烘 |
