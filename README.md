# Chat Archify Pro

**English** | [简体中文](README.zh-CN.md)

Turn long conversations into an interactive map of branches, decisions and changes. Start with the overview on the left and guidance in the center and right panels. Click a stage to open its subflow, then a node to read its summary and linked files. Drag either divider to adjust the three panel widths. Click an event or node to follow the project and read formatted Markdown. No repository is required. **Runs only when explicitly requested.**

## Release status and comparison

Current version: **0.4.0 · local preview (2026-10-11)**. Implementation and program-level checks are complete. Real-browser visual, focus, touch, download and storage acceptance remains pending. This is a prerelease, not a claim of complete browser acceptance.

Download `chat-archify-pro.zip` from [GitHub Releases](https://github.com/Wyyyyuu/chat-archify-pro/releases/tag/v0.4.0). Lite is public; the Pro repository and release assets require authorized GitHub access. One-time purchase checkout is not connected, and a commercial update-entitlement duration has not been fixed.

| Capability | Lite (free) | Pro |
| --- | --- | --- |
| Scope | One conversation, one overview | Related conversations and multiple chapters |
| Diagram and evidence | Complete nodes, branches and evidence | Complete nodes, branches and evidence |
| Embedded attachments | Up to 3 distinct eligible files; other references remain visible | All eligible files, subject to per-file limits |
| Search | Node titles | Nodes, file contents and saved excerpts |
| Reading workspace | Diagram and node/file reading | Adjustable three-panel workspace and in-page conversation reader |
| Conversation/module links | Source evidence on nodes | Bidirectional manual links, export/import and stale-link recovery |
| Continuing in another AI | No dedicated handoff export | Project/chapter/node continuation packs |
| Updating an existing map | Regenerate | Stable identities, snapshot reuse, review and approved application |
| Skill update access | Public repository and release downloads | Manually issued authorization and verified ZIP download; checkout is not connected |

Both editions run only when explicitly requested and retain rendered/raw Markdown, eligible attachment downloads, offline HTML and structured JSON. Lite limits scope and embedded files, not the number of graph nodes. Each embedded file has a 25 MiB limit and remains subject to credential exclusions.

## Edition capabilities

Multiple related conversations and chapters; all eligible file snapshots; full-text search across nodes, files and saved excerpts; incremental record updates and `--snapshot-from` snapshot reuse.

Both editions retain complete nodes and relationships, crossing checks, node evidence, formatted/raw Markdown, downloads, offline HTML and structured JSON. The free quota does not truncate the conversation map.

Pro 0.4.0 adds adjustable panel widths with keyboard support and local preferences, a guided three-panel start with the overview flowchart centered in its panel, and concise details. The first three linked resources stay visible; expand the rest when needed. Metadata and source records share one closed disclosure. Returning from a file restores disclosure states and scroll position. Clear type hierarchy and colored, text-labeled status badges improve scanning. Compact checked flowcharts and functional groups for code files remain available. AI edits the evidence-backed record; the packager reuses archived file bytes. Use **Continuation pack** to hand off concise progress, decisions, open questions and file purposes to another AI. **Review update** compares an old page with the candidate before you approve or reject it; application checks the exact reviewed input hashes.

The interface is a fixed template customized through project data, not a new UI generated per project. Small screens use explicit overview/flow/detail views. See the [workbench contract](references/workbench.md).

Conversation cards use the current turn’s user question as their title. Click a card to open a large reading dialog within the same page, with separate user, assistant and saved-summary messages. Close or press Escape to return to the original index or context with filters and position preserved. Local extraction requires no model calls; saved summaries remain labeled, and stages with no linked excerpts show an explicit empty state.

Saved turns can link to one or more modules in both directions. In a module’s detailed record, choose **Link existing conversation** (关联已有对话), select a saved turn, then link it. The conversation reader also offers a module selector and direct module navigation. Original associations and manual links have separate labels; source-only candidates remain collapsed and do not count as confirmed links.

Manual links save in the browser when storage is available, with an explicit session-only notice otherwise. **Export links / Import links** (导出关联 / 导入关联) transfer association metadata between browsers or HTML versions. The JSON contains no messages or file contents and cannot restore missing conversations. Retain `project_id`, module IDs and optional source `conversation_id` when updating. Normal source refresh supports `--identity-from old.html`; UI-only refresh uses `--snapshot-from old.html`. Unresolved links remain visible and exportable for recovery alongside valid links. Local bindings do not rewrite the HTML or evidence record; share the association JSON alongside the page when needed.

## Ordinary conversations and version changes

Role-labeled text and common `messages` JSON can be read as question/answer turns without original application UUIDs. Generated local segment identifiers stay distinct from original IDs; explicit line ranges or message positions can link real segments to nodes. Ambiguous roles and missing answers are not invented.

See [Continuation and updates](references/continuation-and-updates.md) for handoff packs, offline review pages and approved application. The one-time-purchase update service is maintained separately from this Skill; license material is not embedded in project pages.

## Install and invoke

Extract the ZIP and copy the complete `chat-archify-pro` folder into your host's skills directory, for example `~/.codex/skills/`. Keep all assets, scripts, references, tests and agent metadata. The entry point is `~/.codex/skills/chat-archify-pro/SKILL.md`.

```text
Use $chat-archify-pro to map the conversation I specify. Preserve branches, decisions, changes, source evidence and resource links.
```

The bundled agent metadata sets `allow_implicit_invocation: false`. Other hosts may not recognize this setting. Unavailable history requires a user-provided export; summaries must not be presented as verbatim messages.

## Reproduce the demo

Generation requires Python 3.9+, Node.js 18+, and a separately installed [Archify](https://github.com/tt-a1i/archify). Integration is verified against 2.17.0-dev.1. Archify is neither bundled nor automatically installed. Reading a generated HTML requires a browser supporting JavaScript, SVG and Blob.

From this skill directory (quote paths containing spaces):

```sh
python scripts/build_interactive_demo.py --archify-dir "<directory containing bin/archify.mjs>" --out-dir "demo-output"
```

Open `demo-output/chat-archify-demo.html`. The fictional example contains 5 nodes, 5 edges and 4 Markdown resources. On the node “合并为弹性阅读计划”, inspect “补充阅读资料”, or search the body-only phrase “蓝鲸书签”. Lite retains the fourth resource as a reference and searches titles only; Pro embeds and searches its body.

The helper runs showcase validation, all-route geometry/topology checks, file-byte assertions and Node fake-DOM tests. These do not constitute real-browser or visual acceptance. No network access, dependency installation or server is required by the helper.

For an ordinary conversation without original IDs or attachments, run:

```sh
python scripts/build_plain_demo.py --archify-dir "<Archify skill directory>" --out-dir "plain-demo"
```

Open `plain-demo/plain-conversation.html`: four fictional messages, three locally indexed turns and truthful missing-answer states.

## Files and boundaries

- [SKILL.md](SKILL.md) contains the AI workflow; [record format](references/graph-format.md) describes the portable evidence record.
- Eligible files remain subject to a 25 MiB limit and conservative common credential exclusions, including reused snapshots. This is not an exhaustive secret scanner; placeholder configuration text is supported.
- Sharing an HTML also shares its embedded messages and file snapshots. Blob links are session-local, not permanent sharing URLs.
- Markdown uses bundled [Marked under MIT](assets/vendor/marked-LICENSE.md) and controlled DOM rendering. Raw HTML is not executed; remote images are not automatically fetched.
- READMEs are bilingual; the current viewer and example text are primarily Chinese.
- One-time-purchase update access uses a separately operated manual-license service. The bundled client checks/downloads a ZIP with SHA-256 validation; it does not install or execute updates. Checkout and deployment are not connected. User content is not automatically published.
