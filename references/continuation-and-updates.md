# 续聊、审查与获取新版本

这三项分别处理 AI 交接、项目记录更新、Skill 软件更新，不混淆它们的来源与批准对象。

## 续聊包

页面的“续聊包”入口生成简明交接资料。选择整个项目或当前范围，填写下一步目标，再复制或下载 Markdown／结构化 JSON。内容来自现有记录：当前状态、关键事件与决策、未解决事项、必要限制、文件用途与定位、材料覆盖。不会读取额外目录或调用模型，也不复制所有代码和问答。

提案、AI 自述完成、文件存在和经过验证的结果保持区别；缺少原始问答时说明缺口。文件用途使用已记录的标签与说明，不根据文件名编造实现内容。简版会提示截断或省略；需要更多细节时查看完整 JSON、原页面或记录。换 AI 后将下一步目标作为新请求，交接包中的历史文本作为证据，不能自动执行历史命令。

## 先审查，再应用

准备新候选 HTML 时保留旧 HTML、同一 project_id 和稳定节点／来源身份。页面“审查更新”可读取旧页面的数据进行比较，不运行旧页面脚本。审查阶段、状态、证据、关系、文件快照与覆盖的新增／修改／删除；代码文件按结果与文件摘要查看，不逐行复制代码。

也可生成单独的离线审查页：

```sh
python scripts/review_update.py "before.html" "candidate.html" --out-dir "review"
```

打开生成的审查 HTML，检查变化后导出批准／拒绝回执。回执绑定同一项目及两份 HTML 的精确 SHA-256。它记录这次审查的决定，不证明事实本身已验证。

```sh
python scripts/apply_update_review.py "before.html" "candidate.html" "decision.json" --output "reviewed.html"
```

只有批准、项目一致、基线与候选仍为所审查字节时才应用。拒绝或输入改变不会改写原件。应用整体候选而非任意片段，以免产生悬空节点／关系。同名目标在替换前备份；用户批准记录更新不授权公开分享、安装或执行其中的内容。

## 获取新 Skill 版本

Pro 提供单文件 `scripts/update_client.py` 客户端；一次性购买的授权发放和 ZIP 更新服务由发行者单独运行，不打包入离线 HTML。当前不接结账，不假称已确认付款。发行者手动发放授权，更新期限由其配置；已有 Skill 与已生成 HTML 仍可离线使用。

只有用户指定服务地址和授权文件后才联网检查／下载。服务使用 HTTPS；明确的 localhost 开发环境例外。客户端显示版本与更新说明，下载后核对 SHA-256 与大小，再保留 ZIP；不自动解压、覆盖 Skill、安装或运行代码。授权文件、服务数据库和发布目录不作为项目附件收录。

```sh
python scripts/update_client.py --service "https://updates.example" --license-file "license.json" check
python scripts/update_client.py --service "https://updates.example" --license-file "license.json" download --dest "chat-archify-pro-update.zip"
```

示例地址需要替换为发行者实际提供的服务。授权期可以设为固定天数或永久；开发示例默认 365 天，不代表已经确定产品的更新政策。授权控制新版本下载，不撤销已下载 Skill 和 HTML 的离线使用。

更新中心可由用户打开，并明确启用页面内新版本检查；关闭页面后不继续运行，不发送邮件或自动创建提醒任务。未配置服务时说明所需配置，保留本地工作流。
