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

## 文字或照片生成电路图

> 用 Pygmalion MCP 把这张电路照片整理成实验报告原理图，保存为新文档。保留元件编号和数值，看不清的内容列为待确认项。先给我预览，不开始书写。

Codex 负责理解说明或照片，产品本身不调用模型或 OCR。先调用 `list_circuit_symbols` 获取元件和引脚；用 `type: "circuit"` 元素保存结构，优先调用 `layout_circuit(element=…)` 自动排版，将返回的 `element` 作为正式结构，再调用 `render_circuit(element=…)` 检查图形、导线和诊断，再以 `version: 3` 创建或保存文档，最后 `prepare_document`。完整可调用元素见 [RC 低通示例](../examples/circuits/rc-lowpass.json)，其他示例包括 RLC、整流、共射和反相运放。

电路结构包括 `components`、`junctions`、`wires`、`uncertainties`。导线端点使用 `component_id`＋`pin` 或 `junction_id`，中间拐点为 `waypoints`；普通交叉不自动连接，连接需显式声明连接点及导线。局部坐标采用毫米，右、下为正，方向为顺时针 0/90/180/270 度，整体位置由元素的 `x_mm/y_mm` 决定，`scale` 等比缩放。`width_mm/height_mm` 是选择参考框，不裁剪墨迹。

支持 IEC，电阻可切 ANSI；支持电阻、电容、有极性电容、电感、直流/交流电源、电流源、接地、二极管、稳压管、LED、NPN/PNP、NMOS/PMOS、运放和开关。元件固定使用目录中的类型，不执行 Python、远程资源或任意 Schemdraw 脚本。`length_mm` 控制双端元件的总长度；多端元件采用固定标准符号。标注使用所选单线字库，未覆盖的字符会报告缺字。

旧版扩展字库如果缺少 Ω、μ 或 µ，可用现有单线基础字库离线生成新目录；字库发现链会补充这些字符，不覆盖原始文件：

```bash
poetry run app build-font --base model-bin/cjk-medians/train.parquet --output model-bin/circuit-labels
```

网页中双击电路或点击“编辑电路”，可拖动元件，修改编号、参数、说明、方向和标注偏移，连接线跟随引脚；支持撤销、保存及导出 SVG。拓扑和元件增删交给 Codex 通过 MCP 修改。照片中不确定内容使用 `uncertainties: [{"target_id":"r1","message":"R1 数值待核对"}]`，阻止书写，用户核对后在属性中解除。断开的引脚、重复编号与标注重叠给出警告；不进行电气仿真或自动推断真实电路正确性。

## 工具与流程

| 工具 | 用途 |
| --- | --- |
| `list_documents` | 列出共享文档摘要和 ID |
| `get_document` | 读取完整内容和当前 `revision` |
| `create_document` | 创建独立文档；必填 `idempotency_key` |
| `save_document` | 按所读 `revision` 保存完整文档 |
| `import_svg` | 直接解析 SVG 源码，返回可插入文档的矢量元素，不自动保存 |
| `list_circuit_symbols` | 查询 17 种标准电路元件、合法引脚与符号标准 |
| `layout_circuit` | 自动整理元件间距、正交连线和标注，适配参考框；返回建议元素，不自动保存 |
| `render_circuit` | 校核并绘制原生电路元素，返回 SVG、元件/引脚布局及诊断，不保存 |
| `fit_table` | 计算表格自适应建议，不自动保存 |
| `prepare_document` | 为指定文档版本生成冻结方案、校核及预计用时 |
| `get_plan_preview` | 读取冻结方案的 SVG 笔迹预览 |
| `get_queue` | 查看运行任务及等待队列 |
| `get_job` | 查询任务进度及结果 |
| `cancel_job` | 取消等待任务或请求停止运行任务 |

先读取，再修改，再保存；保留未修改元素、元素 ID 和笔头定位，坐标与尺寸均为毫米。`document_changed` 表示其他客户端已保存新版本，此时应重新读取并合并，或创建新文档保留自己的修改。

保存文档、渲染电路和准备预览均不会开始书写。MCP 已移除 `queue_job`，智能体只负责编辑、预览、查询和停止任务；不得转用 HTTP 运动接口。实际书写由用户在网页主动发起。旧服务进程和 Codex 会话需重新加载，工具列表才会更新。

## 排查连接问题

- 工具不可见：检查 `/mcp`，重新打开 Codex 会话。
- 返回网页或 404：确认使用 `/mcp/`，并重新启动已加载旧代码的 Pygmalion 进程。
- 连接拒绝或超时：确认 Codex 所在电脑可以访问该实例；网页地址与 MCP 使用同一主机、端口。
- 文档找不到：确认 Codex 与浏览器指向同一实例，并传入当前地址中的文档 ID。

### 自动排版与微调

选中电路后点击“自动排版”。引擎按现有粗略方位整理网格和元件间距，重建正交导线，为标注选择靠近器件且避让其他内容的位置，最后等比适配当前参考框。保留元件与导线 ID、端点连接和待确认项；旧拐点及标注偏移会被重算。整次操作可撤销，之后仍可拖动或修改属性。请求期间文档变化会丢弃结果。

这是现有拓扑的布局整理，不做电气推断，也不保证任意复杂反馈图完全无交叉。元件数量较多或空间不足时应拆图；保留诊断和最终视觉检查。自动排版、渲染和保存都不操作机器。
