# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

用于实验报告和作业绘图的学生及电子爱好者，以及使用单页写字工作台的用户。

## Product Purpose

通过 Codex 和 MCP 将文字说明或电路照片转成可编辑的原理图，在网页校对参数、标注和位置，避免每次修订重新手绘。

## Operating Context

React/Vite 工作台由 FastAPI 托管，文档保存在实例 SQLite 数据库。自然语言与图像理解交给外部 Codex，产品提供确定性的结构校验、Schemdraw 绘制、编辑和预览。

## Capabilities and Constraints

首版覆盖基础模拟电路；元件增删与拓扑修改通过 MCP，网页微调参数、标签、方向和位置。保留文字、表格和 SVG。两点测量仅为临时视图辅助。

智能体只能编辑、预览和查询或停止任务，不得提交书写或操作运动设备。实际书写由用户在网页主动操作。自动验证不连接真实串口。

## Brand Commitments

沿用用户指定的 Pygmalion Figma 设计及苍渊·白垣双主题。

## Evidence on Hand

2026-11-04 用户确认：实验报告与作业；基础模拟电路；文字和照片两种输入；Codex＋MCP；网页修改参数、标签与位置；移除常驻刻度并改为两点测距。照片识别的真实准确率尚未验证。

## Product Principles

- 电路结构是正式来源，预览与导出由同一结构产生。
- 不猜测图片中不确定的参数和连接。
- 修改保留稳定 ID、连接关系、撤销历史和版本冲突保护。
- 使用毫米语义，纸张只作为背景参考。
