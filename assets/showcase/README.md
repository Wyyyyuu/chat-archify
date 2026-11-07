# Artwork provenance

- `workspace-zh` and `workspace-en`: original SVG interface illustrations based on the fictional reading-plan fixture and existing documented features; explicitly labelled as illustrations, not browser screenshots. English labels are translated for the illustration; the viewer is currently primarily Chinese.
- `example-flow.svg`: actual output of `scripts/render.py examples/interactive-demo/evolution.json --out-dir <output>`. It is the basic fallback renderer, not the full three-panel HTML.
- `example-flow-en.svg`: English translation of the same export, including labels, tooltips and accessible descriptions. Node identities, relationships, geometry and the original Chinese export are unchanged. The English README uses this version; the Chinese README keeps `example-flow.png`.
- PNG files are rasterizations of those SVGs using resvg. No user conversations, real project files, remote images or fonts are embedded.

插图用于解释工作台；流程图来自随包虚构记录的实际基础导出。完整功能请下载 Release 中的 HTML 示例体验。没有将示意图当作真实浏览器验收证据。
