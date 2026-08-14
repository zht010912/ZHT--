---
name: ActionFlow 会议协同工作台
description: 浅色精密工作台设计系统——Linear/Notion 级工艺的中文会议协同界面
colors:
  accent: "#4f46e5"
  accent-deep: "#4338ca"
  accent-soft: "#eef0fe"
  canvas: "#f5f6f8"
  surface: "#ffffff"
  ink: "#171b22"
  ink-2: "#454d5c"
  muted: "#667085"
  faint: "#a7afbb"
  line: "#e7eaef"
  amber: "#b45309"
  green: "#15803d"
  red: "#c23434"
---

# Design System: ActionFlow 会议协同工作台

## Overview

**Creative North Star: "一间明亮、秩序井然的作战室"**

ActionFlow 是面试演示场景下的会议协同工作台，视觉语言选择类别标准（canon）并以 Linear / Notion / 飞书的工艺水平执行：浅色、精密、克制，所有表现力交给排版、图标与动效体系，而不是色彩堆砌。设计服务演示动线：评委第一眼读到「会议 → 行动项 → AI 待审核」的完整工作流。

明确的视觉否决：深色侧边栏与深色主题（用户认定压抑）；emoji/unicode 符号充当图标；渐变文字与玻璃拟态装饰；eyebrow/kicker 装饰性小标题；后端技术标识（模型名、错误码、prompt 版本）出现在界面文案中。

**Key Characteristics:**
- 单一靛蓝强调色，语义色（琥珀=待审核、绿=完成、红=失败/逾期）各司其职
- 1.5px 描边圆角 SVG 内联图标系统，全站统一
- 1px 细线分界取代厚重阴影，阴影只在悬停时浮现
- 编排式进场动效（stagger rise），只在首次挂载播放一次
- 全中文产品文案，用户语言，无技术黑话

## Colors

色彩纪律：中性灰承载 90% 的界面，靛蓝只为行动与选中态服务，语义色只为状态服务。

### Primary
- **靛蓝 Indigo**（#4f46e5）：主按钮、选中态、焦点环、品牌标识、置信度标记。hover 加深为 #4338ca。
- **靛蓝软底 Indigo Soft**（#eef0fe）：导航选中底、会议行选中底、提示条底色。

### Secondary
- **琥珀 Amber**（#b45309 / 底 #fdf4e4 / 线 #f2ddb3）：AI 待审核状态专用——safety badge、分析卡片、待办标签。它是「需要人来处理」的全站统一语义。
- **青绿 Green**（#15803d / 底 #e9f7ef）：完成状态、服务就绪指示灯。
- **绯红 Red**（#c23434 / 底 #fdecec / 线 #f3c9c9）：失败卡片、逾期标签、表单校验错误。

### Neutral
- **纸白 Canvas**（#f5f6f8）：应用底色。
- **白面 Surface**（#ffffff）：卡片与侧边栏。
- **墨色 Ink**（#171b22）：主文案。
- **深灰 Ink-2**（#454d5c）：次级文案、幽灵按钮。
- **灰 Muted**（#667085）：辅助说明文字（对比度 ≥4.5:1 的底线）。
- **浅灰 Faint**（#a7afbb）：占位符、图标、字符计数等纯装饰性文字。
- **细线 Line**（#e7eaef / #d8dde5）：分界与描边。

### Named Rules
**The One Voice Rule.** 靛蓝在任何一屏占比不超过 10%；它是行动的声音，不是装饰的涂料。
**The Amber Gate Rule.** 琥珀色只允许出现在「等待人工决策」的语义上——AI 建议未经确认前，它不是装饰，是门槛。

## Typography

**Display/Body Font:** 系统无衬线栈（"Inter", SF Pro, PingFang SC, Microsoft YaHei, Noto Sans SC）——演示环境离线可用，中文渲染稳定。
**Mono Font:** 仅用于真实代码/数据场景（"SF Mono", Cascadia Code, Consolas）。

**Character:** 干净、工程感、中西文混排稳定；数字统一 `tabular-nums` 对齐。

### Hierarchy
- **Display**（700, 24px, 1.3, tracking -0.02em）：主区页面标题。
- **Headline**（700, 19px, tracking -0.015em）：详情面板会议标题。
- **Title**（650–700, 14–16px）：面板标题、弹窗标题、区块标题。
- **Body**（400, 13–14px, 1.6）：正文与表单。
- **Label**（600, 11–12.5px）：元信息、标签、辅助说明。

## Layout

240px 浅色侧边栏（白底 + 1px 右分线）+ 主内容区（最大留白 clamp(20px, 3.6vw, 46px)）。工作区为「会议列表 : 详情 ≈ 0.78 : 1.5」双栏。间距节奏：标题上方留白大于下方。≤1050px 侧边栏收窄为图标栏、双栏变单栏；≤720px 侧边栏变为顶部横排导航、指标卡 2×2、筛选单列堆叠。

## Elevation & Depth

静止状态以 1px 细线（#e7eaef）分界，不用阴影；深度只作为状态反馈出现。

### Shadow Vocabulary
- **悬浮浮现**（`0 1px 2px rgba(23,27,34,.05), 0 8px 24px -8px rgba(23,27,34,.12)`）：指标卡与行动项卡片 hover。
- **模态浮层**（`0 24px 70px -12px rgba(23,27,34,.28)`）：对话框。

### Named Rules
**The Flat-By-Default Rule.** 所有面静止时是平的；阴影是界面「抬起回应」的语言，常挂的阴影一律视为视觉噪音。

## Shapes

圆角阶梯：区块卡片 14px（--r-lg）、列表行与内层卡片 10px（--r-md）、按钮与输入 8px（--r-sm）、标签与徽章 999px 胶囊。图标统一 1.5px 描边、圆角端点、currentColor 继承。

## Motion

一次编排，不撒特效：页面/列表首次挂载时子项以 40ms 步进 stagger `rise`（透明度 + 10px 位移，expo 缓出 cubic-bezier(.16,1,.3,1)）；之后的每次数据更新不再重播。交互动效均为 0.16–0.28s：按钮 press scale(.97)、hover 底色过渡、toast 滑入、弹窗 scale(.98)+淡入、服务就绪指示灯的 pulse ring。AI 分析中在建议区叠加扫光（scan）。全局 `prefers-reduced-motion` 降级。

## Iconography

全部内联 SVG 手绘：24 viewBox、1.5px 描边、round caps，尺寸 13–19px 依语境缩放。禁用 emoji 与 unicode 符号（◫ ✦ ⌁ 等已清除）。语义绑定：盾牌=人工确认门槛、三角=待审核/警告、对勾=成功/完成、时钟=待办/逾期。

## Copy

全中文用户语言。控件命名动作（「保存修改并确认」），错误说明问题与出路（「AI 服务尚未配置，请联系管理员完成配置后重试。」）。禁止后端标识入文案：模型名、错误码、环境变量名、prompt 版本一律不出现在界面。

## Responsive & Accessibility

断点 1050px / 720px；焦点环 2px 靛蓝外发光；`::selection` 主题化；滚动条细化；正文对比度 ≥4.5:1；语义色在各自浅底上对比度 ≥4.5:1。
