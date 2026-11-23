# zbrush-mcp

一个**标准 MCP（stdio）**服务器，直连 ZBrush 内置的 JSON-RPC 桥（TCP 127.0.0.1:9876），
不依赖 dcc-mcp 的 sidecar / registry / gateway / job 库。

    DSH (MCP client)  --stdio, one JSON-RPC per line-->  server.py
                      --TCP 127.0.0.1:9876-->  ZBrush 插件 --Python SDK-->  ZBrush

- 无持久状态：日志走 stderr，状态只在内存，产物路径由调用方给绝对路径。
- 不写任何用户目录，因此不受 workspace 写限制。
- 纯标准库，Python 3.9+。`server.py` 是协议层；`ops.py` 是高层动作层——把调色板路径
  封装成 14 个语义化 op，全部经桥的 `execute_python` 执行（桥本身只有固定方法集，
  没有通用"按路径点按钮"的 RPC，所以 op 只能这么落地）。

## 仓库结构

    server.py                     MCP 服务器本体（协议、工具表、错误语义）
    ops.py                        14 个高层 op：PRELUDE 助手 + 每个 op 的脚本片段
    e2e_smoke.py                  端到端验收（15 个基础工具，含转台与烘焙）
    tests/test_m*.py              各里程碑的分步测试（握手、只读、导入、破坏性、烘焙/转台）
    tests/ops_smoke.py            高层 op 冒烟：29 工具清单、调色板探测、笔刷别名
    tests/ops_smoke_geom.py       几何链：导入 → stats → polygroups → dynamesh → zremesher → morph/mask → polypaint → 批量导出
    tests/ops_smoke_misc.py       贴图/渲染链：UV → project all → layers → brush → BPR
    fixtures/cube.obj             测试用立方体（8 点 / 6 面 / 面积 24 / 体积 8）
    third_party/                  ZBrush 侧插件桥（来自 dcc-mcp-zbrush，MIT），仅作参考与离线安装
    docs/                         设计稿与旧方案记录
    tmp/                          运行产物（已 gitignore）

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

注册后可见 **29** 个 zb* 工具（15 个基础 + 14 个高层 op）。
改完 server.py / ops.py 必须重新连接一次连接器，聊天里的工具表才会换成新的。

## 三个前置条件

1. **桥必须活着**：ZBrush 在跑且插件已加载、端口对上。`zbrush_session` 是最便宜的体检。
2. **烘焙依赖细分栈 + UV**：法线/置换等需要该子工具有 SDiv 层级，且要有 UV。
   纯 ZRemesher 结果（无细分）会报 `MAP_NOT_CREATED`；无 UV 报 `UVS_MISSING`。
   顺序：细分 1~2 级 → UV 展开（`zbrush_uv_unwrap`）→ 烘焙。
3. **`Transform:Edit` 的读数不可信**：`zbc.get("Transform:Edit")` 恒返回 0.0，
   `zbc.is_enabled("Transform:Edit")` 恒为 False，对它的 press/set/toggle 全是 no-op。
   **不要拿它做门控**——实测 Divide / DynaMesh / ZRemesher / Duplicate / Mask / Deformation /
   Export 在这个读数为 0 时照样执行。真要看笔画有没有落到网格上，看面数/面积变化，或出图。

## 工具（29）

### 基础 15（协议层，直连桥的固定方法）

只读：zbrush_session / zbrush_scene / zbrush_subtools_list / zbrush_subtool_status / zbrush_mesh_inspect
变更：zbrush_subtool_select / zbrush_subdivide / zbrush_import / zbrush_brush_create / zbrush_brush_load / zbrush_export_obj
破坏性：zbrush_remesh / zbrush_bake_map / zbrush_execute_python
耗时：zbrush_capture_turntable（输出 .psd 帧，可用 ffmpeg 转 PNG）

### 高层 14（ops.py，经 execute_python 执行 zbc 脚本）

| 工具 | 关键参数 | 说明与坑 |
| --- | --- | --- |
| zbrush_stats | — | 一次读点/面/面积/体积/solid/bounds/子工具数/当前工具路径，最便宜的"现在什么状态" |
| zbrush_palette | action=exists\|press\|set\|get, path, value | 任意调色板路径的通用口；路径不存在时抛结构化 `path_not_found` 并列出探测过的路径 |
| zbrush_dynamesh | resolution 8–2048 | 改拓扑，不可逆；先 Duplicate 或存 morph |
| zbrush_zremesher | target_faces 1000–100000, keep_groups, freeze_border | 桥内部按**千分**设置，op 已替你除；结果是近似的（2000 → 约 4374 面） |
| zbrush_polygroups | action=auto\|normals\|split | ZRemesher 前先 Auto Groups，否则 UV 与拓扑都乱 |
| zbrush_mask | action=all\|clear\|inverse\|blur, intensity | 摆姿势前 All + 冻结，比直接挪网格安全 |
| zbrush_morph | action=store\|restore\|delete | 破坏性操作前的免费回退点 |
| zbrush_layers | action=new\|bake_all | 每层只做一件事，最后 Bake All |
| zbrush_uv_unwrap | — | 就是 UV Master:Unwrap；Flatten/分岛仍需在 UI 里做 |
| zbrush_project_all | subtool_level | 低模承接高模细节（ZRemesher 之后必需） |
| zbrush_polypaint_fill | color [r,g,b] 0–255 | 只是染色；polypaint 要变贴图还得 Texture Map:Create |
| zbrush_render_bpr | ao, width, height, output_path | `Document:Export` **只写 .psd**（op 会自动补 .psd 并校验非空）；要 PNG 自己转 |
| zbrush_brush | name, size, intensity, focal_shift, stroke | 别名已归一：Inflate→`Brush:Inflat`、hpolish→hPolish、claybuildup→ClayBuildup、dam_standard→DamStandard |
| zbrush_batch_export | directory, prefix, extension, overwrite | 每个子工具写 `<prefix>_NN.<ext>`，按子工具顺序编号 |

op 失败时返回 MCP `isError: true`，text 里是结构化 JSON（`error` / `hint` / `probed`），不会被当成成功。

## 调色板路径实测（ZBrush 2027 + 适配器 0.2.34）

存在：`Tool:Geometry:DynaMesh|Divide|Lower Res|Higher Res|ZRemesher|Weld|Close Holes|Groups Split|Insert Mesh|Adaptive Size|MicroMesh|Project All`、
`Tool:Deformation:Polish|Inflate|Smooth|Flatten|Array Mesh`、`Tool:SubTool:Duplicate|Merge Down|Delete`、`Tool:Polygroups:Auto Groups|Groups By Normals`、
`Tool:Masking:Clear|Inverse|Blur`、`Tool:Morph Target:Store|Restore|Delete`、`Tool:Layers:New|Bake All`、`Tool:UV Map:UV Master:Unwrap`、
`Tool:Modify:ProjectAll`、`Brush:ClayBuildup|DamStandard|Move|TrimDynamic|hPolish|Pinch|Smooth|Standard|Inflat|SnakeHook|Layer|Planar|Flatten|Elastic|Nudge|Polish|Displace`、
`Draw:Z Intensity|Zadd|Zsub|Draw Size|Focal Shift|Rgb`、`Stroke:FreeHand|Lazy Mouse|LazyStep`、`Render:BPR`、`Document:Export|Import`、`Tool:Export|Import`、`Tool:GoZ`。

**不存在**（别按）：`Tool:Geometry:Decimation Master`、`Tool:SubTool:Merge`、`Tool:SubTool Master`、`Tool:UV Map:UV Master`（只有 `:Unwrap`）、
`Tool:Geometry:Sculptris Pro`、`Tool:Geometry:Dynamic Subdiv`、`Tool:Boolean:Live Boolean`、`Render:Turntable`、`Brush:Form`、`Brush:Mallet`、`Tool:Snapshot`。
注意笔刷名是 **`Brush:Inflat`**，不是 `Brush:Inflate`。

## 进度

客户端在 `params._meta.progressToken` 传令牌即可收到 `notifications/progress`（进队一条、每 10 秒心跳、结束一条）。

## 错误语义

桥的错误码原样透传，不一律当失败：

| 码 | 含义 | 可重试 |
| --- | --- | --- |
| -32601 | 未知方法 | 否 |
| -32602 | 参数非法 | 否 |
| -32000 | 宿主异常（data.traceback）；op 的结构化拒绝也走这条，data.error/hint 带原因 | 视情况 |
| -32004 | 已过期，未执行 | 是 |
| -32001 | 桥忙（data.active_method） | 是，稍后 |
| -32002 | 等待超时，仍在跑 | 否，需人工确认 |

领域失败（`success: false`）会升格为 MCP `isError: true`，不会被当成成功。

## 验收脚本

    python e2e_smoke.py            # 15 个基础工具：initialize → tools/list → session → scene → import →
                                   # subdivide → mesh_inspect → export → remesh → bake → turntable → progress
    py -3 tests/ops_smoke.py       # 29 工具清单 + 调色板探测 + 笔刷别名（几乎不改场景）
    py -3 tests/ops_smoke_geom.py  # 几何链，会导入 cube 并 remesh（**改动文档**）
    py -3 tests/ops_smoke_misc.py  # UV / project all / layers / brush / BPR（**改动文档**，写 tmp/export）

全部都是在**当前 ZBrush 文档**里跑的，请在丢弃得了的文档里验收。
最近一次结果：e2e 12 passed / 0 failed / 1 skipped；三个 ops 冒烟全 PASS。

## 已知坑

- **删子工具会弹模态框**，ZBrush 问「这不是可撤消操作」；弹着的时候脚本停在桥里，
  后续调用全部 `BRIDGE_BUSY`/`ETIMEDOUT`。要么先在 UI 点一次「始终确定（下次重新启动前一直跳过此注释）」，
  要么一次只删一个、删完立刻确认，别在循环里连删。
- **`query_mesh3d` 返回 list[float]**，取 [0]；0=点数 1=面数 2=XYZ bounds 3=UV bounds 8=面积。
- **`Document:Export` 只出 PSD**（桥的转台也是先落 .psd）。
- 脚本在 `execute_python` 里没有预置模块，要自己 `import json/os`。

## 回滚

只删注册的那条连接即可（mcp_connector_disconnect），不涉及任何文件或系统改动。
插件本身是 dcc-mcp-zbrush 安装的，本项目不修改它。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| BRIDGE_UNREACHABLE | ZBrush 未开 / 插件未加载 / 端口不同 | 在 ZBrush 里确认插件加载，`netstat -ano | findstr :9876` |
| BRIDGE_BUSY | 上一个请求还在跑（常见：模态框卡住） | 看 ZBrush 窗口有没有弹框，点掉再发 |
| ETIMEDOUT | 脚本仍在主线程执行 | 先 `zbrush_session` 看 `busy`，别重复发 |
| 笔画没反应 | 在遮罩里 / 子工具不可见 / Zsub 且 Z 太小 | `zbrush_mask clear`、看小眼睛、Z 加回 Zadd |
| UVS_MISSING | 无 UV | `zbrush_uv_unwrap` 后再烘 |
| MAP_NOT_CREATED | 无细分层级 | 先 `zbrush_subdivide` 再烘 |
