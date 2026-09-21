# evolution.json v1

同时支持普通对话和项目记录。`project` 是为兼容已有数据保留的字段名；普通对话用其 `title` 表示主题，不要求项目目录。节点的 `artifacts` 可为空，来源 URI 也可为空，但证据定位不能省略。

UTF-8 JSON。稳定 ID 使用英文字母/数字/下划线/连字符，首字符为字母，最长 64 字符，大小写敏感。数组顺序用于同层展示，不证明因果。最小示例：

```json
{
  "schema_version": 1,
  "project": {"title": "项目名", "summary": "回顾范围", "updated_at": "2026-09-19", "current_state": "当前状态未知"},
  "coverage": ["仅有任务 A 的可见摘录，较早轮次尚未读取"],
  "sources": [{"id": "s1", "title": "原始任务标题", "kind": "conversation", "coverage": "excerpt", "locator": "任务 ID / 提供者 / 日期范围", "uri": "", "note": "实际读取范围"}],
  "nodes": [{"id": "n1", "kind": "goal", "title": "确定基础版本", "summary": "先实现基本功能", "reason": "原因未知", "branch": "主线", "status": "proposed", "date": "", "evidence": [{"source": "s1", "locator": "可见摘录，用户第 2 条消息", "note": "用户提出先完成基本功能"}], "artifacts": []}],
  "edges": [],
  "open_questions": ["缺少后续实现结果"],
  "revisions": []
}
```

顶层字段均需提供。`project` 的四项均为字符串，未知日期/现状可为空。`coverage` 非空字符串数组；`sources/nodes` 非空数组；`edges/open_questions/revisions` 可空。source 必填 `id/title/kind/coverage/locator`；`uri/note` 可选。coverage 取 `full/excerpt/summary/unavailable`。kind 为描述性文本，如 `conversation/document/commit/test-log`。

## 节点与产物

节点必填 `id/kind/title/summary/branch/status/evidence`；可选 `date/reason/artifacts`。kind：`goal/milestone/module/experiment/decision/issue`。status：`proposed/in_progress/completed/verified/failed/paused/superseded/unknown`。每个节点至少一条 evidence，其中 source 引用与非空 locator 必填，note 可选。状态属于历史事件，不替代模块的当前状态。

```json
{"label": "MVP 原型", "uri": "./artifacts/prototype.html", "role": "produced", "verification": "exists", "version": "版本标签或 commit；未知可空", "note": "只核实存在，没有运行"}
```

artifact 必填 `label/uri/role/verification`，`version/note` 可选。role：`produced/modified/referenced`。verification：`exists/missing/mentioned/unchecked`，只表示可访问性，不代表功能通过测试。渲染器只在 HTML 的数据副本添加 `href` 等展示字段，输入 JSON 保持不变。

允许相对文件路径、绝对本地路径、`https/http/file/codex` URI。Codex 链接必须来自实际证据。禁止脚本 URL、data URL 和网络共享路径。原 URI 始终显示以便复制；浏览器/宿主可能限制本地链接。

## 关系

```json
{"from": "n1", "to": "n2", "type": "adds", "confidence": "explicit", "reason": "用户要求在基础版上增加导出", "evidence": [{"source": "s1", "locator": "第 8 轮", "note": "先保留 MVP，再补导出"}]}
```

以上字段全部必填，evidence 非空。type：`continues` 延续、`branches` 分叉、`adds` 增加、`pivots` 转向、`merges` 合并、`depends_on` 依赖、`chronological` 仅先后。依赖箭头由前置事件指向后续事件。confidence：`explicit` 材料明确支持、`inferred` 有依据的推测；推测需在 reason 说明，完全无依据则不连线并列入疑问。

实线为明确关系，虚线为推测或仅时间先后，边上显示类型。事件图为 DAG，允许多个根及独立组件。旧方案重启应新增事件，不把箭头指回历史节点。跨来源冲突用事件说明及 `open_questions` 保留，不用倒向箭头制造循环。

## 增量维护

不按数组下标生成 ID。追加证据或新事件，保留旧 ID。`revisions` 是字符串数组，记录重要更正的日期、旧解释、新解释及依据。覆盖记录仅更新到实际读过的位置；未读的后续仍是未知。
