# 普通长对话示例 / Plain conversation example

4 条虚构消息，无原始 UUID、代码仓库或附件。最后两条仅保存用户问题；不补造回答。框图保留比较、选择与“尚未执行”的区别。

Four fictional messages without original application IDs or attachments. Missing replies are not invented; choosing a plan does not mean executing it.

在完整 Skill 目录运行 / Run from the complete Skill folder:

```sh
python scripts/build_plain_demo.py --archify-dir "<Archify skill directory>" --out-dir "plain-demo"
```

打开 / Open `plain-demo/plain-conversation.html`。节点用真实消息序号定位；本地轮次标识不是原应用 ID。The generated local turn identifiers are not original application IDs.
