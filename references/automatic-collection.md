# 自动采集与一致性校验

适用于 Codex 宿主已提供 `list_threads`、`read_thread` 的情况。只通过宿主授权工具读取；不读私人数据库，不绕过工具访问限制。其他平台没有对应适配器时仍使用用户导出，不能声称已自动搜索该平台历史。

## 运行采集

`scripts/collect_conversations.cjs` 是无网络、无依赖的状态机。`scripts/collect_codex_host.cjs` 适配 MCP 文本响应，自动运行每个批次；`collection_checkpoint.cjs` 保存增量进度。宿主需绑定列表、读取和本地写文件三个回调，之后不由模型逐页决定游标。

先通过项目工具取得实际项目 ID／目录，配置 `projectIds`、`roots` 或明确的 `threadIds`。路径按目录边界匹配，不按标题关键词扩张到无关聊天。状态会扫描活动和归档两个列表，再读取符合范围的每个对话。工具不可用时不能虚构适配结果。

下面是宿主执行器中的调用方式；`listTool`、`readTool`、`writeExclusive` 分别绑定已发现的工具与本地安全写入能力。CommonJS 环境用 `require` 加载模块；没有 Node 文件系统、但能读取本地源文件的宿主 JS 执行器，也可将可信脚本源码作为 CommonJS 模块加载。不要把聊天内容当脚本执行。

```js
const collector = require('./scripts/collect_conversations.cjs');
const journal = require('./scripts/collection_checkpoint.cjs');
const bridge = require('./scripts/collect_codex_host.cjs');
let session = {
  state: collector.createState({projectIds: [actualProjectId], roots: [actualRoot], hostId: 'local'}),
  previous: null,
  sequence: 0
};
session = await bridge.runBatch({
  collector, journal, ...session,
  listThreads: listTool,
  readThread: readTool,
  writeCheckpoint: (name, text) => writeExclusive(checkpointDirectory, name, text),
  maxCalls: 20
});
```

`writeExclusive` 必须先确认目标在本任务输出目录内，拒绝覆盖已有编号，并在写入失败时抛错。每次成功分页或失败重试后都会等待检查点写完。批次返回 `in_progress` 时保存 session、给出必要进度后继续调用；`maxCalls` 只是单批次上限，不能把它当采集完成。若提供方失败，批次从 10 轮缩到 3／1 轮，再尝试较小输出；仍失败就保留游标和缺口，继续其他对话，不跳过失败页。

从磁盘恢复：读取按编号排序的检查点，用 `journal.restore(checkpoints)` 得到 state，`previous` 设为该 state 的深拷贝，`sequence` 设为已有检查点数，继续同一目录。缺少任何编号都会报错。也可先执行：

```text
node "<skill-dir>/scripts/restore_collection.cjs" "<checkpoint-dir>" "<output-dir>/state.json"
```

`collector.freshRun(previousState)` 用同范围建立新采集状态，检查新出现或修改的对话。恢复旧状态只表示续读同一轮，不证明此后没有新增历史；不要把旧回执当实时同步。

## 导出和打包检查

```text
python "<skill-dir>/scripts/collection_audit.py" export "<output-dir>/state.json" --out-dir "<output-dir>/collection"
python "<skill-dir>/scripts/collection_audit.py" check "<output-dir>/collection/collection-receipt.json"
```

生成分对话 JSON、冻结状态、`source-audit.md` 与 `collection-receipt.json`。导出前按原始消息正文重新执行 Python 凭据检查，避免 JSON 转义导致漏检；公开文字与助手进度可保留，推理／工具项不导出。图片等非文字项、正文截断和被过滤消息单独记录。`item-N` 仅作为工具条目标识，不冒充原生消息 ID。日期来自轮次起始时间（UTC），不是逐条消息时间。

将回执中的每个非空导出加入至少一个章节的 conversation sources。source 使用实际任务标题、稳定 conversation_id 和 task locator，`coverage` 将导出的 `complete` 映射为记录格式的 `full`，其他情况用 `excerpt`。所有导出可进入总览的对话索引；模块关联仍需实际消息证据，不能按关键词自动猜测。补充到既有 HTML 时重复使用 `--refresh-conversation <导出绝对路径>`，保留其他历史快照。

新自动采集 manifest 必须包含：

```json
{
  "collection_audit": "collection/collection-receipt.json",
  "collection_policy": "required"
}
```

打包器重新检查分页链、候选集合、公开消息保存情况、导出内容和 SHA-256，并核对每份导出确实作为对话来源嵌入。缺少回执、文件被改动、漏掉来源、仍有待读页均拒绝打包。工具确实读不下去且其他对话已处理后，使用 `collection_policy: "allow_partial"` 可生成标有缺口的版本；它仍不能绕过待读页或损坏的导出检查。旧 manifest 可继续打开／打包，但标为 `not_audited`，不得宣称已通过自动采集完整性检查。

这些检查验证本地记录与导出的一致性，不是提供方签名认证，也无法证明工具未列出、已删除或无权访问的聊天不存在。
