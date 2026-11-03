# Codex 接入 Pygmalion

Pygmalion 在网页同一实例提供 Streamable HTTP MCP：`http://127.0.0.1:8080/mcp/`。它直接复用文档、方案和队列服务，不启动第二个设备执行器，也不创建另一份文档数据库。

## 启动与连接

更新依赖后重新启动 Pygmalion，已有调试进程需要停止后重新运行：

```bash
poetry install
poetry run app serve
```

只有排版和演练需求时，可以使用 `poetry run app serve --dry-run`。排版和预览工具本身不移动设备。

在运行 Codex 的电脑执行：

```bash
codex mcp add pygmalion --url http://127.0.0.1:8080/mcp/
codex mcp list
```

如果 Codex 在另一台电脑，把 `127.0.0.1:8080` 换成浏览器访问 Pygmalion 的实例地址。`127.0.0.1` 始终指运行 Codex 的那台电脑。保留结尾的 `/mcp/`。

也可以在 Codex 的 `~/.codex/config.toml` 中添加：

```toml
[mcp_servers.pygmalion]
url = "http://127.0.0.1:8080/mcp/"
tool_timeout_sec = 120
```

重新打开 Codex 会话，在 `/mcp` 查看 `pygmalion` 及其工具。连接方式依据 [OpenAI 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)，实现使用 [官方 Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)。

## 使用示例

在网页打开目标文档，复制包含 `?document=doc_…` 的地址给 Codex：

> 用 Pygmalion MCP 修改这个文档：〈粘贴文档地址〉。把标题放在纸张上方居中，正文使用 8 mm 字号，保留表格和 SVG。先读取最新版本，修改后保存并生成预览；这次只排版，不开始书写。

Codex 读取数据库文档并保存新版本后，网页会自动同步。修改坐标、尺寸、文本框、表格和 SVG 的布局不需要改应用源码或操作浏览器。

## 直接导入 SVG

把 SVG 文件交给 Codex，或提供 SVG 源码，并说明目标文档和摆放位置，例如：

> 将这个 SVG 导入〈文档地址〉，放在右下角，宽度设为 30 mm，保持宽高比，保留已有文字。保存后生成预览，先不要书写。

智能体先读取文件内容，调用 `import_svg(source="<svg …>…</svg>", name="装饰图案")`。工具返回标准 `element`，包含独立 ID、名称、原始毫米尺寸、归一化路径以及轮廓或填充设置。它与网页导入使用同一解析器，不再需要智能体手工转换路径。

导入阶段只做转换。智能体随后读取目标文档，把返回的元素加入 `elements`，按毫米调整 `x_mm`、`y_mm`、`width_mm` 和 `height_mm`，再用所读版本调用 `save_document`；最后 `prepare_document` 生成预览。保持宽高比时应同时按比例调整宽、高。

支持路径、直线、折线、多边形、矩形、圆、椭圆、分组变换及填充规则。SVG 最大 1 MB；文字需先转成路径，位图、脚本、外部资源、裁剪和滤镜等内容会返回错误。输入为 SVG 源码，远程实例无需访问智能体电脑上的文件路径。

## 工具与流程

| 工具 | 用途 |
| --- | --- |
| `list_documents` | 列出共享文档摘要和 ID |
| `get_document` | 读取完整内容和当前 `revision` |
| `create_document` | 创建独立文档；必填 `idempotency_key` |
| `save_document` | 按所读 `revision` 保存完整文档 |
| `import_svg` | 直接解析 SVG 源码，返回可插入文档的矢量元素，不自动保存 |
| `fit_table` | 计算表格自适应建议，不自动保存 |
| `prepare_document` | 为指定文档版本生成冻结方案、校核及预计用时 |
| `get_plan_preview` | 读取冻结方案的 SVG 笔迹预览 |
| `get_queue` | 查看运行任务及等待队列 |
| `get_job` | 查询任务进度及结果 |
| `queue_job` | 提交方案到共享队列；必须明确传 `mode` 和去重键 |
| `cancel_job` | 取消等待任务或请求停止运行任务 |

先读取，再修改，再保存；保留未修改元素、元素 ID 和笔头定位，坐标与尺寸均为毫米。`document_changed` 表示其他客户端已保存新版本，此时应重新读取并合并，或创建新文档保留自己的修改。

保存文档和准备预览不会开始书写。用户要求书写后，使用预览返回的 `plan_id` 提交任务；`simulate` 演练，`execute` 操作实体机器。提交响应丢失时复用同一 `idempotency_key`、`plan_id` 和 `mode`，不能生成新键重复提交。任务提交后轨迹冻结，继续编辑文档不会改变已排队任务。

## 排查连接问题

- 工具不可见：检查 `/mcp`，重新打开 Codex 会话。
- 返回网页或 404：确认使用 `/mcp/`，并重新启动已加载旧代码的 Pygmalion 进程。
- 连接拒绝或超时：确认 Codex 所在电脑可以访问该实例；网页地址与 MCP 使用同一主机、端口。
- 文档找不到：确认 Codex 与浏览器指向同一实例，并传入当前地址中的文档 ID。
