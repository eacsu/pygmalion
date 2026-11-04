# 志莽行中心线实验转换

2026-11-04，离线转换已完成并保留为独立字体“行意单线·实验（轮廓转换）”。默认字体和机器速度参数未修改，没有执行实机书写。

## 输入与授权

- 字体：[Google Fonts 志莽行](https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/ZhiMangXing-Regular.ttf)，[原始项目](https://github.com/m4rc1e/zhimangxing)。
- 许可：[SIL OFL 1.1](https://raw.githubusercontent.com/google/fonts/main/ofl/zhimangxing/OFL.txt)。派生字库改名为“行意单线”，保留原作者声明、完整 OFL 和来源信息。
- 源 TTF SHA-256：`644e0cae9b40f0b10ab729a01bd32032e3973bac22be3dccae01bf6ae7fde969`。
- FontTools 读取 Unicode cmap，Pillow/FreeType 栅格化。只在离线命令中转换，运行服务直接读取 Parquet。

## 复现

```bash
poetry install
poetry run app convert-outline-font \
  --source .cache/font-research/ZhiMangXing-Regular.ttf \
  --license-file .cache/font-research/zhimangxing-license.txt \
  --output model-bin/xingyi-centerline
```

输出必须是新目录。可用 `--characters '负反馈放大电路'` 先做小样，`--pixels 256` 控制采样尺寸，允许 96–512。命令不联网，不写配置、不初始化机器。先验证再原子发布；已有输出拒绝覆盖。

## 算法与边界

1. 默认选择源字体覆盖的基本汉字、ASCII、常用中日韩标点和全角西文；去除空白并跳过缺失映射，不使用系统字体代替。
2. 256 px 渲染，灰度阈值 128；Zhang-Suen 二阶段细化，得到中心线骨架。该算法也见 [OpenCV thinning 文档](https://docs.opencv.org/4.10.0/df/d2d/group__ximgproc.html)。
3. 建立像素图，避免正交边之外的冗余对角三角形；按连通分量将奇数度节点配虚边，欧拉分解保留所有真实骨架边。虚边仅作为抬笔分隔，绝不绘制跨越空白的连接线。孤立点保留。
4. RDP 简化容差为 0.65 px；闭环保持闭合。逐字等比缩入 0.9 em，以万分之一 em 整数保存坐标，输出 Hugging Face Parquet。

分解只保证骨架边被覆盖，不恢复原作者的书写时间、真实笔顺、压力和自然连笔。细化会在粗笔尖端、交叉与装饰处产生短分支，图遍历的方向可能不适合实际写字。此版本未做针对中文结构的伪分支剪除或笔顺模型，不应称作天然单线行楷，也不保证速度改善。

## 实际结果

- 源 cmap：7015 个 Unicode 映射，含 6763 个基本汉字。
- 默认筛选 6968 个映射，排除空白后产出 6967 个字形，跳过缺失/空墨迹字形 0 个。
- 总路径数 77636。完整覆盖字符与逐字路径数、点数见生成目录的 `characters.txt`、`provenance.json`。
- 74 字小样与原字库相比，路径数为 632 对 531，增加约 19%；减少抬落笔的目标尚未达成。不能把覆盖增加当作提速证明。
- 已人工检查 16 字原轮廓/中心线对照：`output/font-research/outline-comparison.png`。主要字形可辨，部分字末端和交叉存在额外分支。
- 可在相同内容、字号、速度配置下比较实际用时；本次只创建预览文档，不发送运动指令。

后续优先研究短伪分支剪除与交叉处的连续方向选择，并检查其对汉字结构的损伤；不通过直接增大硬件速度来掩盖路径问题。

## 优化版

2026-11-04 新增 `--optimize`，完整转换仍保留 6967 个字形（6763 个汉字），安装为独立字体“行意单线·优化版”，ID 为 `xingyi-centerline-fast`。基线字体和默认字体均未覆盖。

```bash
poetry run app convert-outline-font \
  --source .cache/font-research/ZhiMangXing-Regular.ttf \
  --license-file .cache/font-research/zhimangxing-license.txt \
  --output model-bin/xingyi-centerline-fast --optimize
```

在每个骨架连通分量中，使用有距离上限的最短路寻找可配对的奇数度节点，沿已有骨架短距离回描，减少欧拉分解后的抬笔次数。单次回描上限为栅格边长的 12%，每字新增回描总长预算不超过原骨架线长的 15%。不删除字形分支，不画跨空白的新连接线，孤立点和独立部件保留。只对没有真实笔顺的轮廓转换字形做字内路径排序及反向，不影响原字库，也不跨字重排。优化模式的 RDP 容差为 0.9 px，基线仍为 0.65 px。

128 字同内容、8 mm 样张，使用同一软件参数的离线比较：

| 指标 | 原字体 | 初版中心线 | 优化中心线 |
| --- | ---: | ---: | ---: |
| 路径数 | 864 | 1080 | 544 |
| 字库轨迹点数 | 5584 | 19992 | 9312 |
| 落笔长度（em） | 446.099 | 426.368 | 440.278 |
| 最终 G-code 行数 | 8369 | 22092 | 11922 |
| 粗估时间（秒） | 59.65 | 67.62 | 42.06 |

优化版相对初版少约 49.6% 的路径、落笔长度增加约 3.3%；相对原字体路径少约 37.0%，模型粗估用时少约 29.5%。估算未计入控制板加减速、短线段处理、通信吞吐和真实墨迹条件，不能作为实机提速承诺。优化后的指令行数仍多于原字体。回描可能造成局部墨色加深；它也不恢复人的自然笔顺。

已查看 16 字优化前后对照 `output/font-research/fast-comparison.png` 和实际单页预览 `output/font-research/fast-live.png`，主要字形保持一致。测试验证原骨架边不遗漏、不新增跨空白落笔、回描预算、确定性和路径排序边界。实际写字速度、墨色及笔尖状态仍需用户主动测试。
