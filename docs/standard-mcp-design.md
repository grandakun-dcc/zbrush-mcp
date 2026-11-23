# ZBrush MCP —— 标准 MCP 架构设计

状态：设计稿（未实现）。日期 2026-11-24。
前置事实全部来自实测，见文末「证据」。

## 1. 为什么换

现在的形态是：`dcc-mcp-zbrush` sidecar（HTTP :8788）+ 插件（TCP :9876）+ 外部守护，
靠三个 `DCC_MCP_DISABLE_*` 环境变量绕开写盘失败。它解决不了四件事：

| # | 阻塞 | 现状根因 |
|---|---|---|
| 1 | sidecar 写不了 log/job/registry（os error 5） | venv 里的解释器（255,200 B）被 OS 层限制为仅可写 workspace；系统 python（105,696 B）可自由写 |
| 2 | sidecar 不常驻、无 stdio | 适配器只有 HTTP 端点，客户端无法持有其生命周期 |
| 3 | `dcc_pid` 错位 → `screenshot` 必败 | `server.py:41` 的 `dcc_pid` 无人填充 |
| 4 | 169 个工具的上下文税 | 全量 tools/list |

标准 MCP 架构下，这四条**在设计上就不存在**，不是靠补丁压住的。

## 2. 目标架构

```
DSH (MCP client)
   │  stdio: newline-delimited JSON-RPC 2.0
   ▼
zbrush_mcp_server.py        ← 我们写，纯 stdlib，单文件，约 400 行
   │  TCP 127.0.0.1:9876, newline-delimited JSON-RPC 2.0
   ▼
dcc_mcp_zbrush_socket_bridge.py   ← 复用，已在本机跑通
   │  主线程 pump + queue
   ▼
ZBrush 2027 内嵌 Python 3.11.9 / zbrush.commands
```

关键分工：

- **server 是客户端的子进程**（stdio）。客户端起它、关它；服务器崩溃不影响 ZBrush；ZBrush 关掉时服务器只报错不退出。
- **server 无持久状态**：不建 SQLite、不建 registry、不写 log 文件。日志走 **stderr**（MCP 规范里 stderr 就是给服务器日志用的）。
- **插件由 ZBrush 自己加载**（`ZStartup` 或 `ZBRUSH_PLUGIN_PATH`），只要 ZBrush 开着，9876 就在。
- **pid 由 ZBrush 侧报**：`execute_python("import os; result = os.getpid()")` 或插件新增字段，不再猜。

## 3. 逐条对应

| 阻塞 | 标准架构如何处理 |
|---|---|
| os error 5 | 不需要可写状态目录。日志→stderr，状态→内存，产物→调用方指定的绝对路径。 |
| 不常驻 | stdio 由客户端持有；server 空闲时只是阻塞在 stdin 读，零开销。 |
| dcc_pid | 会话信息里带真实 pid，来自 `os.getpid()`，不是配置项。 |
| 上下文税 | 默认 15 个工具；`execute_python` 作为逃生口；如需更多再分层。 |

## 4. 已核实的桥协议（可直接实现）

文件：`C:\Users\Admin\AppData\Roaming\Maxon\Maxon ZBrush 2027_5B5302DE\Python\dcc_mcp_zbrush_socket_bridge.py`（53,031 B，1,274 行）

- 传输：TCP，默认端口 9876（`DCC_MCP_ZBRUSH_SOCKET_PORT` 覆盖），**一行一条 JSON**，读到 `\n` 为止，回一行。
- 信封：标准 JSON-RPC 2.0，`{"jsonrpc":"2.0","id":N,"method":"...","params":{...}}`。
- 可选 `params.deadline_unix_ms`（毫秒时间戳）：桥会在超时前拒绝执行，避免"迟到的请求仍然跑"。
- 方法表（`_handle_zbrush_request` :98-163）：

| method | 关键参数 |
|---|---|
| `ping` | 无；回 `{ok,busy,active_method}`，不触碰 SDK |
| `get_session_info` | 无 |
| `get_scene_info` | 无 |
| `list_subtools` | 无 |
| `get_subtool_status` | `index?` |
| `select_subtool` | `index` |
| `refine_active_subtool` | `subdivision_levels`, `polish`, `inflate` |
| `remesh_active_subtool` | `target_face_count`, `duplicate` |
| `inspect_active_mesh` | 无 |
| `bake_active_subtool_map` | `map_type`, `output_path`, `width`, `height`, `smooth`, `border` |
| `create_wrinkle_brush` | `output_path` |
| `load_wrinkle_brush` | `brush_path` |
| `export_active_subtool_obj` | `output_path` |
| `capture_turntable` | `output_dir`, `angles?`, `prefix`, `bpr_render`, `polyframe` |
| `import_to_scene` | `file_path` |
| `execute_python` | `code`, `context?`；命名空间预置 `zbc`，回 `result` |

- 错误码（`_dispatch_request` :1071-1146，必须原样映射，不能一律当失败）：

| code | 含义 | 可重试 |
|---|---|---|
| -32601 | 未知方法 | 否 |
| -32602 | 参数非法 | 否 |
| -32000 | 宿主异常（含 traceback 在 `data`） | 视情况 |
| -32004 | 过期，**未执行**（`data.executed:false`） | 是 |
| -32001 | 桥忙（`data.active_method`） | 是 |
| -32002 | 等待超时，**可能仍在执行**（`data.still_running:true`） | 否，须人工确认 |

## 5. server 侧规范映射

### 5.1 生命周期

- `initialize` → 回 `protocolVersion`、`capabilities: {tools:{}}`、`serverInfo:{name:"zbrush", version}`。
- `notifications/initialized` → 忽略。
- 不实现 `resources`/`prompts` 第一版（可选：`zbrush://session`、`zbrush://subtools`）。

### 5.2 工具面（15 个）

只读（`readOnlyHint: true`）：`zbrush_session`、`zbrush_scene`、`zbrush_subtools_list`、`zbrush_subtool_status`、`zbrush_mesh_inspect`。
变更：`zbrush_subtool_select`、`zbrush_subdivide`、`zbrush_import`、`zbrush_brush_create`、`zbrush_brush_load`、`zbrush_export_obj`。
破坏性（`destructiveHint: true`）：`zbrush_remesh`、`zbrush_bake_map`、`zbrush_execute_python`。
耗时（`capture_turntable`、`remesh`、`bake_map`）：标注长活，客户端超时须 ≥ 600 s 或改轮询。

每个工具有完整 `inputSchema`（type/properties/required/description），参数名与上表一致，不做二次发明。

### 5.3 错误语义

- ZBrush 没开 / 插件没载 → `isError: true`，正文给出**可执行指引**（"启动 ZBrush 2027 并确认 9876 在监听"），不是抛栈。
- -32001 → 返回"桥忙（正在执行 X），可重试"，并在正文标注 retryable。
- -32002 → 返回"已超时但可能仍在执行，请先用 zbrush_session 确认状态"，**不自动重试**。
- 连接被拒（ECONNREFUSED）与超时（timeout）分开报，前者是"没起"，后者是"卡住"。

### 5.4 进度与取消

- 长活用 `notifications/progress`（`progressToken` 从 `_meta` 取）发心跳；桥没有进度接口，只能发阶段标记（已发送→等待中→完成）。
- `notifications/cancelled`：只能丢弃"尚未发送"的请求；已进入 ZBrush 主线程的工作**不可取消**，必须如实告知（与 -32002 同）。

### 5.5 安全

- 只连 `127.0.0.1`，不监听外部地址。
- 插件当前**无鉴权**：任何本机进程都能通过 9876 执行任意 Python。第一版接受（与 Blender 插件同类风险），后续可在插件与 server 之间加共享 token（`DCC_MCP_ZBRUSH_TOKEN`，两端比对）。
- `execute_python` 是最高危工具，描述里明确写"可任意修改场景"。

## 6. 部署

DSH 侧注册一个 stdio MCP server：

```json
{
  "mcpServers": {
    "zbrush": {
      "command": "C:\\Users\\Admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
      "args": ["C:\\Users\\Admin\\Documents\\deepseek-harness\\default-workspace\\zbrush-mcp\\server.py"],
      "env": { "ZBRUSH_BRIDGE_PORT": "9876" }
    }
  }
}
```

- 用**系统 python（105,696 B 那个）**，不用 venv —— 它不受 workspace 写限制；且 server 纯 stdlib，无 pip 依赖。
- 不需要计划任务、不需要守护、不需要环境变量补丁。
- ZBrush 侧的插件安装：把 `dcc_mcp_zbrush_socket_bridge.py` 放到 ZStartup，或用 `ZBRUSH_PLUGIN_PATH` 指向它（已实测可加载）。

## 7. 实施计划

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 | server 骨架：initialize / tools/list / ping | 客户端能看到 15 个工具 |
| M2 | 全部 16 个 method 转发 + 错误码映射 | 逐个调用成功；断桥时给指引文案 |
| M3 | 长活（turntable/remesh/bake）+ 进度通知 | 转台出图、remesh 完成、超时文案正确 |
| M4 | 文档 + 一条 e2e 脚本 | 一条命令跑完"起 ZBrush→建档→雕→导出" |

工作量：server ≈ 400 行 stdlib Python + 一个 e2e 脚本；插件不改（可选加 pid 与 token）。

## 8. 风险

- 桥是**串行**的：一个请求在跑时其他一律 -32001。server 必须自己排队或快速失败，不能并发打。
- `capture_turntable` / `bake_map` 会长时间占 UI 主线程，期间 ZBrush 界面卡；要提前告知用户。
- 插件无鉴权（见 5.5）。
- MCP `protocolVersion` 需按客户端实际支持的版本回；DSH 侧以 2024-11-05 / 2025-03-26 兼容实现为准。

## 9. 与现状的关系

- `dcc-mcp-zbrush` / `dcc-mcp-core` 退居参考实现：读它的错误码、超时策略、SDK 调用方式，**不作为运行时**。
- 已安装的插件保留复用（它才是真正碰 ZBrush 的那层，且已在本机验证 2027.0.1 可用）。

## 10. 证据（实测）

- 桥方法表与错误码：`dcc_mcp_zbrush_socket_bridge.py` 第 98-163、1037-1146 行。
- 桥传输：同文件第 1044-1056 行（TCP、\n 分隔、单行响应）。
- 写权限矩阵：`zbrush-mcp-test/probe_write.py` 输出；venv python 255,200 B 被限制，系统 python 105,696 B 不受限；新建干净 venv 复现同样限制。
- 会话信息：`zbrush_version 2027.001`、`embedded_python true`、`bridge_instance_id ad034163-...`、ZBrush pid 10648、9876 由 10648 监听。
- 插件落盘位置与时间：`AppData\Roaming\Maxon\Maxon ZBrush 2027_5B5302DE\Python\`，2026-11-15 04:55。
