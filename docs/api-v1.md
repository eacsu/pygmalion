# 公开接口 v1

API 位于 `/api/v1`；交互文档为 `/docs`，完整契约为 `/openapi.json`。仓库提交了 [OpenAPI](../src/web/openapi.json) 与 [生成的 TypeScript 类型](../src/web/src/generated/api.d.ts)。错误、HTTP 结果及事件消息均由公共 Pydantic 模型定义。旧 `/api/admin/*`、`/api/workbench/*`、投稿接口及命令 WebSocket 已移除，返回 404；已有文档和数据库历史保留。

## 实例共享文档

文档正式保存在实例 SQLite 数据库，与机器控制权无关。浏览器缓存仅用于入口、未确认提交凭证及保存失败时的本页恢复，不作为共享文档来源。

| 方法与路径 | 行为 |
| --- | --- |
| `POST /documents` | CanvasDocument v2 → 新文档；必填 `Idempotency-Key` |
| `GET /documents?limit=100` | 最近更新的文档摘要；最多 200 份，不含正文 |
| `GET /documents/{id}` | 读取正文、ID、版本及时间；响应含 `ETag` |
| `PUT /documents/{id}` | 更新完整 CanvasDocument v2；必填 `If-Match: "版本号"` |

创建和读取返回 `{id, revision, document, created_at, updated_at}`。保存成功递增 `revision`；缺少版本返回 428，版本过期返回 `412 document_changed`，不覆盖已有内容。外部客户端应先 GET，基于所读版本修改后 PUT；冲突需重新读取并合并或另存。同一实例另提供 `/mcp/`，MCP 工具复用这些文档和执行服务；连接配置见 [Codex / MCP 接入](mcp.md)。

网页提供文档库及 `?document=doc_…` 分享入口；每秒检查新版本。无本地修改时更新本页，有未保存修改时保留本页并提示冲突。新建和导入产生独立文档，切换前先保存当前修改。文档更新不会改写已准备的方案或排队任务；修改后需重新准备并提交。

## 准备与书写

| 方法与路径 | 行为 |
| --- | --- |
| `GET /health` | 存活检查；不访问设备 |
| `GET /capabilities` | 文档版本、限制、允许的执行模式、会话期限 |
| `GET /service` | 服务地址信息 |
| `GET /fonts` | 本地数据集名称和覆盖数量；不含服务端绝对路径 |
| `POST /documents/validate` | 校验 CanvasDocument v2 结构；不检查字库或设备 |
| `POST /documents/fit-table` | 文档和 `element_id` → 新表格与诊断；不保存内容 |
| `POST /imports/svg` | `source`、`name` → 可插入文档的标准矢量 `element`；初始尺寸等比适配 A4 页边距，客户端可按当前纸张再次适配 |
| `POST /plans` | CanvasDocument v2 → 不可变方案；不打开串口 |
| `GET /plans/{id}` | 创建时的方案信息 |
| `GET /plans/{id}/preview` | 与冻结轨迹对应的 SVG |
| `POST /jobs` | `plan_id` 和必填 `mode: execute\|simulate` → 持久任务 |
| `GET /jobs/{id}` | 按 ID 查询；与列表条数无关 |
| `GET /jobs?limit=50&before=123&status=succeeded` | ID 倒序分页；`next_cursor` 为空表示结束 |
| `POST /jobs/{id}/cancel` | 请求取消，返回当前任务 |

表中路径均省略 `/api/v1` 前缀。集合统一返回 `data` 与 `next_cursor`。

结构错误返回 422。内容无法准备（没有字库、缺字、溢出、空内容）时仍可创建方案，返回 201、`status: blocked` 和带元素/单元格信息的 `diagnostics`。`ready` 只表示内容可准备，不预占机器。方案固定保存文档、SVG、G-code、软件参数、字库标识与校验摘要，不因后续字号或速度修改而重新生成。

方案可重复使用，**不设过期时间、不自动清理**，`expires_at: null`。提交和执行前检查连接、纸张校准及控制板参数上下文；不匹配返回 `execution_context_changed`，需重新准备。已接受任务保存独立快照。当前一个运行目录只允许一个服务进程，一个实例管理一台设备，可接受多个未结束任务并按顺序逐个执行。各客户端共享队列，`GET /queue` 返回运行任务、最早 200 个等待任务及等待总数，独立于任务历史列表。手动控制会话仍与任务互斥；真实任务发生结果无法确认的异常后，后续真实任务不会自动执行运动，需显式恢复设备。

```http
POST /api/v1/jobs
Content-Type: application/json
Idempotency-Key: a-stable-key-for-this-submission

{"plan_id":"plan_...","mode":"simulate"}
```

`execute` 明确请求真实书写；`simulate` 不访问串口，笔头定位使用虚拟工作坐标 `(0, 0)`。以 `--dry-run` 启动的服务拒绝 `execute`，不静默改成模拟。

## 去重与故障恢复

任务提交、创建控制会话及排队设备操作必须带 1–200 字符的 `Idempotency-Key`。任务和操作在数据库事务中与去重记录一起持久化。同一键与同一请求返回原资源；同一键用于不同请求返回 `409 idempotency_conflict`。并发重试与重启后重试同样生效。记录与任务均无限期保留，当前无自动清理接口。

调用者应在发送前保存键及完整请求。超时后使用原键、原请求重试，拿到 ID 后查询状态；不要生成新键重发运动。网页会保存未确认的任务提交凭证，刷新后显示“找回上次任务”。创建控制会话的旧键在会话结束或重启后返回 `session_expired`，不会复活控制权；新的控制意图使用新键。

这保证提交去重，不能保证硬件在所有故障下恰好执行一次。收到 `interrupted` 后先检查实机；不要把它自动改成新任务。

| 状态 | 含义 |
| --- | --- |
| `queued` | 持久化接受，尚未开始 |
| `running` | 执行中；发送进度可已达 100% |
| `cancelling` | 已请求取消，停止后续发送并等待收尾 |
| `succeeded` | 实机已确认 Idle 或模拟结束 |
| `cancelled` | 未发送，或已确认缓冲区执行结束并完成抬笔收尾 |
| `failed` | 已知拒绝/失败；查看 `error` |
| `interrupted` | 设备通信中断或服务重启导致执行结果无法确认 |

发送完成不等于机器完成；取消请求成功不等于已经停稳。重复取消正在取消或已取消任务返回当前状态，对其他终态取消返回 409。重启时未启动的任务标记取消，可能触及设备的任务进入 `interrupted`，绝不自动重发。

## 笔头定位

文档可带 `pen_anchor: {"x_mm":35,"y_mm":45}`，表示这一个文档点对应当前物理笔头。拖动标志只更新文档中的定位点，文本框、表格、矢量图的位置保持原样；定位数据随文件保存并支持撤销/重做。

空闲时实机提交读取 GRBL 工作坐标（支持 WPos 或 MPos−WCO，转换 `$13` 英寸报告），拒绝无法确认坐标或非 Idle 状态。已有任务时，新任务先持久排队，轮到执行且设备空闲后再读取坐标，不尝试读取运动中的笔头。接受和执行共用同一串口连接，执行前再次核对实际位置。轨迹以定位点为参考整体平移，按校准的轴映射检查实际写字盘范围，完成抬笔后回到本任务绑定时的工作坐标。普通书写也保留已验证连接，避免重新开串口影响坐标。

## 设备观察、操作与控制权

| 方法与路径 | 行为 |
| --- | --- |
| `GET /machine` | 缓存快照，带 `sampled_at`、`stale`、`connected`；不打开串口 |
| `GET /serial-ports` | 仅操作系统枚举 |
| `POST /serial-probes` | 显式探测；返回操作 ID；不自动保存连接 |
| `GET/PATCH /machine/connection` | 读取/选择连接，支持 COM 数字、系统枚举端口、Linux/macOS `/dev/` 路径 |
| `POST /machine/refresh` | 主动通信，返回操作 ID；可带 `session_id` 复用当前控制连接 |
| `POST /machine/control-sessions` | 取得控制权，期限 30 秒 |
| `POST /machine/control-sessions/{id}/renew` | 续期；网页每 10 秒调用 |
| `DELETE /machine/control-sessions/{id}` | 释放，取消尚未发送动作；已运行的操作收尾后释放连接 |
| `POST /machine/commands` | 带 `session_id` 的明确类型命令，返回操作 ID |
| `GET /operations/{id}` | 查询操作状态、结果及错误 |
| `POST /machine/emergency-stop` | 优先急停，不排在运动队列末尾 |
| `GET/POST /machine/backups` | 列表 / 创建备份，创建返回操作 ID |
| `GET /machine/backups/{id}/download` | 下载已有备份 |
| `POST /machine/settings/previews` | 离线检查 `changes`，如 `{"$110":4000}` |
| `POST /machine/settings/previews/{id}/apply` | 带控制会话应用预览，先备份，返回操作 ID |

命令采用判别类型：`{"type":"jog","session_id":"session_...","axis":"x","distance_mm":1}`，以及 `pen_up`、`pen_down`、`set_origin`、`goto_origin`、`recover`、`disconnect`、`cancel_pending`。队列最多一个运行加三个等待动作。会话失效、主动释放或执行失败会丢弃未开始的动作；刷新页面不恢复控制会话或重发命令。任务与手动动作由同一个所有者仲裁。

`/events` WebSocket 只推送 `machine.updated`、`job.updated`、`operation.updated`，使用与 HTTP 相同的数据模型。观察不取得控制权。重连后通过 HTTP 查询补齐快照；网页不会重发运动。事件契约见 OpenAPI 的 `Event` 与 `x-websocket`。

急停结果分别提供 `command_sent` 与 `stop_confirmed`。当前优先通道能报告发送结果，不能独立确认停稳，因此返回 `interrupted / stop_unconfirmed`、`stop_confirmed: false`。急停后禁止新真实书写和普通运动，需显式 `recover`。取消与急停的响应都不能作为已停稳的替代证据。

固件参数写入无法原子回滚。结果包含 `applied`、`failed`、`unknown`、`not_applied` 以及备份；明确拒绝为 `failed`，通信中断为 `interrupted`，未确认项不自动重试。这里“控制板参数写入”不涉及刷新固件。

## 配置与错误

`GET/PATCH /settings/software`、`/settings/editor`、`/settings/calibration` 与 `/machine/connection` 使用同一版本协议。读取结果的 `values` 是配置，`etag` 与 HTTP `ETag` 一致。更新只提交需要更改的字段，并将编辑开始时的 ETag 放入 `If-Match`。未知字段、错误类型或越界值整批拒绝；不会保存部分字段或静默钳制。连接和校准在设备被占用时拒绝修改。

```http
PATCH /api/v1/settings/editor
If-Match: "读取时返回的版本"
Content-Type: application/json

{"font_size_mm":6.5}
```

错误统一返回：

```json
{"error":{"code":"machine_busy","message":"设备已被占用","details":{},"retry_advice":"wait"},"request_id":"req_..."}
```

程序判断使用 `code`；`message` 用于展示。`retry_advice` 为 `never`、`wait`、`query_status`、`reprepare` 或 `refresh`。响应头提供 `X-Request-ID`。

| HTTP | 含义 |
| --- | --- |
| 400 | JSON 无法解析 |
| 404 | 路由或资源不存在 |
| 409 | 设备占用、状态/上下文冲突、重复键冲突 |
| 412 | 配置 ETag 已过时 |
| 422 | 结构、字段或参数约束不满足 |
| 428 | 缺少 If-Match |
| 503 | 提交所需设备位置不可用 |
| 500 | 未预期内部错误；动作结果先查询 |

## 独立客户端

先从网页导出 `.pygmalion.json` 文档，也可以直接生成符合 OpenAPI 的 CanvasDocument v2。示例直连指定服务，不读取系统代理；仅使用 HTTP，不依赖前端：

```bash
poetry run python examples/v1_write.py 文档.pygmalion.json --receipt .cache/submit-1.json
# 同一个凭证再次运行：找回同一任务；写另一份使用新的凭证路径。
poetry run python examples/v1_write.py --receipt .cache/submit-1.json
# 实机书写需要显式指定：
poetry run python examples/v1_write.py 文档.pygmalion.json --execute --receipt .cache/real-1.json
poetry run python examples/v1_write.py --cancel 123
```

示例把预览保存为凭证同名 `.svg`；凭证在请求前落盘，网络错误时保留。明确业务拒绝后应先修正原因，再使用新凭证重新准备。成功或失败的最终状态可继续按任务 ID 查询。


纸张尺寸仅定义参考背景。元素和笔头定位坐标允许负数或超出纸张；元素宽高为正有限数值，不再以 297 mm 为上限。方案预览 SVG 的 viewBox 包含纸张与所有元素。纸边、页边距和旧写字盘背景配置不再作为任务提交门槛，控制板自身限位保持有效。

软件速度字段没有软件上限，`fields[].max` 在没有上限时为 `null`；当前最低速度为 100 mm/min。不得将 `null` 当作 0 或沿用旧的 8000 上限。


`Plan` 和 `Job` 增加可空字段 `estimated_duration_seconds`，单位为秒；无可用估算或历史数据时为 `null`。方案按生成的冻结 G-code 和软件参数粗估，真实任务在绑定实际笔头坐标后重新估算并持久化。该字段不代表设备承诺时间。界面通过 `started_at` / `finished_at` 计算已用时间；`percent` 与进度条始终表示指令发送比例，`status: succeeded` 才表示书写结束。
