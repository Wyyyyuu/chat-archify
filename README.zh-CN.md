# Chat Archify · 对话脉络图

[English](README.md) | **简体中文**

把长对话整理成可交互的脉络图，呈现话题、决策与转向，并为每个节点附上来源和可选的资源链接。

适用于单个普通长对话，也适用于跨多个聊天窗口的项目回顾。不需要代码仓库，没有附件也能使用。**只有你明确要求时才生成。**

[快速开始](#快速开始) · [试跑示例](#试跑示例) · [选择查看器](#选择查看器) · [使用边界](#使用边界与数据处理)

Chat Archify 是独立项目，并非 Archify 官方扩展；Archify 仅作为可选的图形查看器集成。

## 可以追溯什么

- **讨论分支：** 最初的问题、候选方案、比较过程与结论。
- **项目演进：** 基础版本、模块增加、并行实验和发布过程。
- **方向变化：** 放弃过哪些方案、原因是什么、后来如何决定。
- **后续讨论：** 保留已有节点 ID，追加新事件与证据。

每个节点记录发生了什么、为什么改变、当时的状态及其来源。可以附文档、代码、截图或网页链接；没有附件时，仍可查看摘要和来源定位。

## 快速开始

### 1. 安装 Skill

下载或复制这个目录，放入 Codex 的 skills 目录，文件夹命名为 `chat-archify`。安装后的入口应为：

```text
~/.codex/skills/chat-archify/SKILL.md
```

如果配置了其他 skills 位置，以实际配置为准。请复制整个目录，包括 `assets/`、`scripts/`、`references/` 和 `agents/`。

随附的 `agents/openai.yaml` 设置了 `allow_implicit_invocation: false`。其他 AI 宿主的安装位置可能不同，也不一定识别这项 Codex 设置。

### 2. 明确要求生成

整理一个对话：

```text
使用 $chat-archify 梳理当前这段长对话。
保留话题分支、候选方案、被放弃的想法和最终决定，
并附上来源和相关资源链接。
```

回顾一个项目：

```text
使用 $chat-archify 回顾这个项目在相关对话中的演进。
展示基础版本如何扩展、哪些地方改变了方向，
以及各个阶段产生了哪些文件。
```

继续更新已有图：

```text
使用 $chat-archify 根据这段新讨论更新已有 evolution.json。
保留旧节点和历史分支，追加新决定，标出尚未解决的问题。
```

宿主无法读取对话时，请提供聊天导出。Skill 本身不能取得不可访问的历史记录。

## 试跑示例

仓库中的[示例对话](examples/reading-plan/conversation.md)是四条关于阅读习惯的虚构消息。[对应记录](examples/reading-plan/evolution.json)包含四个节点，没有产物附件。

准备好 Python 后，在 Skill 目录执行以下命令，无需 Archify 或 AI 宿主：

```sh
python scripts/render.py examples/reading-plan/evolution.json --out-dir outputs/demo
```

打开 `outputs/demo/evolution.html` 查看。同一命令也会生成 SVG、Markdown 和 JSON 副本。已在 Python 3.12 验证，脚本仅使用标准库。

这个示例演示如何渲染已经整理好的记录。对话中的事件和证据由 AI 提炼，脚本不会自行读取聊天或理解其含义。

## 选择查看器

| | 基础查看器 | 交互附件查看器 |
| --- | --- | --- |
| 准备方式 | 内置 Python 渲染器 | 另行准备 Archify，再使用内置打包器 |
| 节点内容 | 详情、来源和资源引用 | 资源弹窗、详情和来源 |
| 文件操作 | 链接到原始资源；本地链接可能受限 | 内嵌快照，文件名可点击，支持预览、下载和复制原始路径 |
| 框图操作 | 轻量框图与 SVG 导出 | Archify 的拖动、缩放与图形控制 |
| 适用场景 | 不使用 Archify，快速查看脉络 | 对照框图浏览各阶段文件 |

**Archify 是可选依赖，不包含在本目录中。** 当前集成基于 Archify 2.17，升级后需重新检查节点联动。HTML 查看器需要支持 JavaScript、SVG、Dialog 和 Blob 的浏览器。

使用交互附件版时，先按[集成说明](references/interactive.md)准备检查通过的 Archify HTML 和 manifest，再执行：

```sh
python scripts/check_routes.py outputs/my-map/archify-overview.html
python scripts/package_interactive.py outputs/my-map/manifest.json outputs/my-map/chat-archify.html
```

这些命令要求图形和 manifest 已存在。打包器逐对检查所有连线，包括共享节点的连线；发现交叉、重合或穿框时会中止，需要先修正图形。检查器支持正交 `M/L` 路径，不支持的几何形式会明确报错。

## 记录与增量更新

`evolution.json` 独立于查看器保存节点、关系、来源、覆盖范围和待解决问题，更新时保留已有 ID。`evolution.md` 提供可读索引，`evolution.svg` 是可选的矢量导出。

提议、决定、实施与验证是不同的事件或状态。发生在后面不自动意味着依赖前面的事件；推测关系必须标明，缺失历史必须作为缺口保留。

## 使用边界与数据处理

- **历史访问取决于宿主。** 实际范围由可见消息、提供的导出和获准使用的工具决定，不能根据摘要还原缺失的原话或决定。
- **附件是可选的。** JSON 中的 `project` 字段为兼容原格式而保留；普通对话可直接填写话题标题。
- **分享附件查看器，也会分享其中的文件。** 快照不会自动更新；Blob 链接属于当前页面会话，不是永久分享地址。
- **生成结果保存在本地。** Skill 不会自动上传仓库、发布网页或向他人发送对话内容。
- **验证有明确范围。** 结构、几何和文件字节检查不能证明历史叙述准确，也不能替代浏览器可用性验证。浏览器交互仍需单独检查；现有代码检查不代表已完成浏览器验收。
- **文档语言与界面语言不同。** README 提供中英文版本；随附技能说明、示例对话和查看器文案目前主要为中文。

这个源码包只包含通用代码、模板、说明和虚构示例，不包含真实用户对话或项目附件。

## 目录导航

| 路径 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | AI 执行技能时的入口说明 |
| `agents/openai.yaml` | Codex 显示名称、调用示例和显式调用设置 |
| [来源说明](references/sources.md) | 访问范围、缺失记录与引用方式 |
| [记录格式](references/graph-format.md) | JSON 字段、节点状态和关系 |
| [交互集成](references/interactive.md) | Archify、附件打包与验证要求 |
| `scripts/` / `assets/` | 渲染器、检查器、打包器和查看器模板 |
| `examples/` | 虚构对话示例及对应记录 |

修改技能时，使用虚构对话演示行为，保留已有节点 ID 和证据，并同步维护中英文 README。提交源码时不应包含私人聊天或文件快照。
