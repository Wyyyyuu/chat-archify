# Artwork provenance

- `workspace-zh` and `workspace-en`: original SVG interface illustrations based on the fictional reading-plan fixture and existing documented features; explicitly labelled as illustrations, not browser screenshots. English labels are translated for the illustration; the viewer is currently primarily Chinese.
- `example-flow.svg`: a static illustration adapted from `scripts/render.py examples/interactive-demo/evolution.json --out-dir <output>`. It shows the basic fallback renderer, not the full three-panel HTML. Export-local node links and interactive styling are removed because the accompanying `evolution.html` is not published in this directory. The legend directs readers to the downloadable HTML demo for interaction.
- `example-flow-en.svg`: English translation of the same static illustration, including labels, tooltips and accessible descriptions. Node identities, relationships and geometry are preserved. The English README uses this version; the Chinese README uses `example-flow.png`.
- PNG files are rasterizations of those SVGs using resvg. No user conversations, real project files, remote images or fonts are embedded.

插图用于解释工作台；流程图基于随包虚构记录的基础导出制作，已移除依赖未随图发布的 HTML 的节点链接。完整交互请下载 Release 中的 HTML 示例体验。没有将示意图当作真实浏览器验收证据。
