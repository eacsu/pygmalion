# 行楷与连笔字库调研

核查日期：2026-11-04。目标是可写的单线轨迹，而非双线描边。没有执行实体书写或修改默认字体。

| 候选 | 实际数据与授权 | 适用结论 |
| --- | --- | --- |
| [Stroke2Font](https://github.com/aylqs2025/stroke2font) | 上游提供行楷分笔坐标 JSON、算法与模型，仓库声明 MIT，LICENSE 未单列数据例外 | 最短接入路径，已下载并转换为现有 Parquet 格式；仅实验覆盖 |
| [志莽行](https://github.com/m4rc1e/zhimangxing) / [Google Fonts 元数据](https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/METADATA.pb) | OFL-1.1，简体中文手写轮廓字体；已下载 TTF 与许可 | 广覆盖备选，但 TTF 轮廓不是笔头轨迹，尚未做中心线转换 |
| [CASIA-OLHWDB](https://nlpr.ia.ac.cn/databases/handwriting/Download.html) | 有原始 POT 轨迹；[官方条件](https://nlpr.ia.ac.cn/databases/handwriting/Application_form.html)限制免费学术使用，商业使用另行授权 | 不是统一行楷风格的现成字库；适合获得授权后的轨迹与风格研究，未纳入产品 |
| [CursiveChineseCalligraphyDataset](https://github.com/nccuviplab/CursiveChineseCalligraphyDataset) | 5301 类草书灰度图片，仓库声明 MIT，并说明原图片再分发来源 | 可做图像与风格研究，缺少笔顺和在线轨迹，未转换 |

## 已完成的轨迹导入

新增离线命令：

```bash
poetry run app import-stroke2font \
  --source .cache/font-research/stroke2font-180.json \
  --license-file .cache/font-research/stroke2font-license.txt \
  --output model-bin/stroke2font-xingkai-179
```

源文件：[paper-1-180xk.json](https://raw.githubusercontent.com/aylqs2025/stroke2font/main/data/paper-1-180xk.json)，许可：[LICENSE](https://raw.githubusercontent.com/aylqs2025/stroke2font/main/LICENSE)。下载内容 SHA-256：

- JSON：`429addde13029f3c922682d148d2050d43b0fb7200fd315047a610e56277c103`
- 志莽行 TTF：`644e0cae9b40f0b10ab729a01bd32032e3973bac22be3dccae01bf6ae7fde969`

转换规则：保留数组内的笔画顺序、方向、分笔边界及 y 向下坐标；逐字居中、等比缩入 0.9 em；去除连续重复点，点笔画保留为零长度路径。不重排笔画，不新增牵丝，不执行下载仓库的 Python 或模型。源坐标稀疏，转换没有凭空补足曲线。输出采用 Hugging Face Parquet，并附原许可、来源摘要、输入哈希、转换说明和重复记录处理策略。拒绝覆盖已有目录，验证成功后才发布。

实测 180 条记录中“奥”重复，保留首次版本并在 provenance.json 记录。结果为 179 个字形（178 个汉字＋圆点），以拼音 A/B 开头的字为主，不能作为日常全文字库。已安装为“行楷·实验（179字形）”，需对现有文本显式选择。缺字由原有数据集补充，因此整段可能混合风格。

与当前 `cjk-medians-plus` 共有 178 字，笔画总数由 1841 条降到 1365 条，减少约 25.86%。这是同字集笔画数量比较，不能据此声称实际时间缩短同等比例；尚未进行实机速度、可读性或磨损测试。

字样对比生成于 `output/font-research/comparison.png` 与同名 SVG，逐格左侧为现有字体、右侧为转换行楷。已人工查看 16 字预览；部分字形较粗糙、折线感明显，先作为实验候选。

## 广覆盖字体的算法路线

志莽行的完整 TTF 已下载至 `.cache/font-research/ZhiMangXing-Regular.ttf`，同目录保存 OFL。后续可离线栅格化、提取骨架、剪除伪分支，并以原字形轮廓约束路径拟合；交叉处分笔与笔顺恢复需要额外规则或轨迹模型，不能把骨架遍历直接当成人的连笔。转换结果应另起名称并保留 OFL。该路线尚未实施，不能声称完整志莽行已能用于单线书写。

上游 Stroke2Font 的 DQN、GA 等是研究算法，未运行或引入推理依赖，也未把其论文的优化指标解释成写字机速度。现阶段优先保留可核查原轨迹，再评估平滑、有限连笔与抬落笔减少。
