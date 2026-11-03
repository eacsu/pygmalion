# 功能重建与离线验证

本次以重新检出的代码为基线，根据对话确认的需求、智能体会话记录中的源码修改和测试用例，重建之前已实现的功能。旧 Git 对象已不存在，因此这些是新的恢复提交。

## 恢复范围

| 范围 | 恢复结果 |
| --- | --- |
| 字库与文字 | 无字库立即提示并禁止书写；超大字形等比收进字格；退出编辑保留笔画预览；白纸固定浅色渲染，双主题检查真实笔迹像素 |
| 字号 | 应用默认 8 mm，可保存为 4–40 mm；新建文本框、表格及 TXT 导入使用默认值；已有文本框独立设置、保存与撤销 |
| 速度 | 书写及空走上限 8,000 mm/min，抬落笔上限 10,000 mm/min；公开接口整批严格校验 |
| 机器选择 | 支持 COM、Linux/macOS 设备路径；自动模式下唯一可识别设备由网页选用，多设备时手动选择 |
| 笔头定位 | 拖动笔尖标志或输入毫米坐标，使整份内容相对实际笔头定位；支持键盘、文件保存、刷新与撤销 |
| 公开接口 | `/api/v1` 完整请求/响应/错误 Schema；独立 API 启动；OpenAPI 与生成的 TypeScript 类型 |
| 执行与恢复 | 冻结 Plan、明确真实/模拟模式、持久任务和去重键、按 ID 查询及分页、取消与重启不重发 |
| 设备操作 | 短期控制会话、可查询操作、只读事件推送、版本化配置、备份和参数分项写入结果 |

接口语义及 Python 示例见 [公开接口 v1](api-v1.md)。旧投稿与旧机器控制接口已移除；新功能统一使用 v1。

## 字库数据

从本机 Hugging Face 数据缓存恢复了 `model-bin/cjk-medians/train.parquet`（9,574 字）及 `model-bin/cjk-medians-plus/train.parquet`（9,797 字），并附带授权文件。`model-bin` 按既有规则不进入 Git；另存本地恢复包时需同时保存字库。

源码重建不生成丢失的历史任务、机器校准或用户文档。运行时继续读取实际存在的配置、数据库及浏览器草稿。

## 不访问物理硬件的验证

后端测试通过自动 fixture 禁止真实 `serial.Serial`；需要设备交互的测试显式安装替身。即使调用路径捕获异常，测试收尾也会检查是否发生过未模拟的串口访问。

Playwright 服务使用 `.cache/e2e` 独立配置、模拟书写、占位端口 `COM99`，并通过 `tests/no_hardware/sitecustomize.py` 禁止服务子进程打开真实串口。机器控制的浏览器场景使用 HTTP 与事件通道替身。

```bash
poetry run pytest -q
pnpm --dir src/web run api:check
pnpm --dir src/web run lint
pnpm --dir src/web run build
pnpm --dir src/web run test:e2e
```

本次重新运行：188 项后端测试、54 项浏览器测试通过；类型生成、契约漂移、lint 和生产构建通过。另以串口被禁止的独立 API 进程运行 Python 示例，同一凭证重复提交只创建一个成功的模拟任务，定位坐标为虚拟 `(0, 0)`，真实执行请求被拒绝。

测试不证明实机行程、实际抬落笔或急停停稳效果。急停接口继续明确区分指令发送与停止确认。

## 本地恢复包

目录外的本地恢复包位于 `~/.cache/pygmalion-recovery/` 下的本次日期目录。源码包为 `source.bundle`，字库包为 `fonts.tar.gz`，校验值在 `SHA256SUMS`。恢复到新目录时：

```bash
git clone /绝对路径/source.bundle pygmalion-restored
cd pygmalion-restored
git switch dev
tar -xzf /绝对路径/fonts.tar.gz
poetry install
pnpm --dir src/web install --frozen-lockfile
pnpm --dir src/web run build
```

恢复包在当前目录之外，但仍是本机副本；远端推送依用户指示执行。
