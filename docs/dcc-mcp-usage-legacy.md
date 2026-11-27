# dcc-mcp-zbrush（169/62 工具那条路）现在的运行方式

## 它是什么

`dcc-mcp-zbrush` 是一个“适配器 + 网关”的重型 MCP：HTTP 端点在 `http://127.0.0.1:8788/mcp`，
底下通过 ZBrush 插件（TCP 9876）操作 ZBrush。它的工具面是**渐进式**的：
基础工具常驻，其余按技能包（skill）分组，`load_skill` 之后才出现。

## 现在的进程

| 进程 | 端口 | 说明 |
| --- | --- | --- |
| ZBrush.exe (pid 10648) | 9876 LISTEN | 插件桥，唯一底层通道 |
| dcc-mcp-zbrush sidecar (pid 17584) | 8788 LISTEN | 169 那套的 HTTP MCP 服务 |

DSH 连接器 `json-zbrush` = streamable-http `http://127.0.0.1:8788/mcp`，协议 2025-03-26，healthy。

## 启动（幂等）

    zbrush-mcp-test\start-sidecar.cmd

已在跑就直接返回（查 8788 占用）。脚本里设了三个关键环境变量：

    DCC_MCP_REGISTRY_DIR=<工作区>\zbrush-mcp-test\runtime\registry
    DCC_MCP_LOG_DIR=<工作区>\zbrush-mcp-test\runtime\logs
    DCC_MCP_DISABLE_JOB_PERSISTENCE=1

前两个把注册表/日志从 `%TEMP%` 挪到可写目录，这是当初 `os error 5` 的解法；
第三个因为 job 持久化在本机环境里打不开它的 ownership lock（同样是 os error 5），
只能让 job 历史留在内存（进程活着的期间可查，重启即清空）。

## 开机自启（可选，需要你点头我才做）

    schtasks /Create /TN "zbrush-mcp-sidecar" /SC ONLOGON /RL LIMITED ^
      /TR "<工作区>\zbrush-mcp-test\start-sidecar.cmd"

不加也行：每次用之前双击一下那个 .cmd。

## 怎么用（DCC 官方那套节奏）

1. `search_tools("关键词")` —— 先看有没有现成工具，别硬凑。
2. `load_skill("zbrush-subtool")` 之类的技能包 —— 工具才会出现，比如
   `zbrush_subtool__remesh_active_subtool`、`zbrush_subtool__bake_active_subtool_map`。
3. `tools/call` 调具体工具。
4. 长活（remesh / bake / turntable）用 `jobs_get_status` 轮询，不要死等。
5. 要视觉证据用 `zbrush_viewport__capture_turntable`，**不要用** `dcc_diagnostics__screenshot`（见下）。

常用技能包与工具数：zbrush-scene / zbrush-subtool(6) / zbrush-brush(2) / zbrush-viewport(1) /
zbrush-interchange(1) / zbrush-import-to-scene(1) / zbrush-dialog(2) / zbrush-scripting(1)，
另有基础设施包 dcc-diagnostics(5) / media(8) / qt-ui-inspector(5) / ui-control(10) / workflow(1)。

## 已知限制（都是上游的，不是配置问题）

| 现象 | 原因 | 绕法 |
| --- | --- | --- |
| `dcc_diagnostics__screenshot` 报 `no window for pid=<sidecar pid>` | sidecar 模式下 `dcc_pid` 被填成了适配器自己的 pid（应为 10648），window_handle 为 null | 用 `capture_turntable` 出图 |
| job 历史重启即失 | 本机打不开 SQLite ownership lock（os error 5） | 只依赖进程内轮询；或关掉持久化（已关） |
| 桥忙 `-32001` | TCP 9876 是串行的，一次只处理一个请求 | 串行调用；忙则稍后重试 |
| 工具数只有 62 | 这个包本体就 14 个技能、上限 ~62 个工具 | 我之前说的 169 是错的，见下 |

## 关于“169 个工具”

复核结论：这个包（0.2.34）装的是 14 个技能，工具面上限实测 **62**（基础 55 + 技能 7~），
`tools_list` 的 uniqueToolCount 与 totalToolEntries 都是 62。**169 我复现不出来**，
之前那个数是我没核对就记下的，作废。要更大的工具面只有两条路：把其它 DCC 适配器也挂上，
或者自己写技能包扩进来。

## 排错

    netstat -ano | findstr :8788        # sidecar 在不在
    netstat -ano | findstr :9876        # 插件桥在不在（ZBrush 必须开着）
    type zbrush-mcp-test\runtime\logs\dcc-mcp-zbrush.*.log
    type zbrush-mcp-test\runtime\logs\dcc-mcp-zbrush.*.host-errors.log
