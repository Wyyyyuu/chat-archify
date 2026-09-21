# Chat Archify

**English** | [简体中文](README.zh-CN.md)

Turn long conversations into interactive maps of topics, decisions, and changes in direction—with sources and optional resource links attached to each node.

Use Chat Archify for a single conversation or a project discussed across several chats. No code repository or file attachments are required. **It runs only when you explicitly ask.**

[Quick start](#quick-start) · [Try the example](#try-the-example) · [Viewer options](#viewer-options) · [Limitations](#limitations-and-data-handling)

Chat Archify is an independent project, not an official Archify extension. Archify is an optional integration for its diagram viewer.

## What you can trace

- **Discussion branches:** the initial question, alternatives, comparisons, and conclusions.
- **Project evolution:** an initial version, added modules, parallel experiments, and releases.
- **Changes in direction:** abandoned approaches, the reasons behind them, and the next decision.
- **Follow-up discussions:** append events and evidence while retaining existing node IDs.

Each node records what happened, why it changed, its status at that time, and its sources. Links can point to documents, code, screenshots, or web pages. Without attachments, nodes still show summaries and source locations.

## Quick start

### 1. Install the skill

Download or copy this directory into your Codex skills directory, using `chat-archify` as its folder name. The resulting entry point should be:

```text
~/.codex/skills/chat-archify/SKILL.md
```

Use your configured skills directory if it differs. Copy the entire directory, including `assets/`, `scripts/`, `references/`, and `agents/`.

The included `agents/openai.yaml` sets `allow_implicit_invocation: false`. Other AI hosts may use different installation locations and may not recognize this Codex setting.

### 2. Ask for a map

For one conversation:

```text
Use $chat-archify to map this conversation.
Keep the topic branches, alternatives, rejected ideas, and final decisions.
Include sources and any relevant resource links.
```

For a project:

```text
Use $chat-archify to trace this project's evolution across its related chats.
Show how the initial version grew, where the direction changed,
and which files came from each stage.
```

To continue an existing map:

```text
Use $chat-archify to update the existing evolution.json with this new discussion.
Preserve old nodes and branches, add new decisions, and identify unresolved questions.
```

Provide a transcript export when the host cannot access the conversation. The skill cannot retrieve unavailable history on its own.

## Try the example

The [sample conversation](examples/reading-plan/conversation.md) is a fictional four-message discussion about a reading habit. Its [structured record](examples/reading-plan/evolution.json) has four nodes and no artifact attachments.

With Python available, run this command from the skill directory. It does not require Archify or an AI host:

```sh
python scripts/render.py examples/reading-plan/evolution.json --out-dir outputs/demo
```

Open `outputs/demo/evolution.html`. The same command also produces SVG, Markdown, and a copy of the JSON record. Python 3.12 has been tested; the scripts use only its standard library.

This demonstrates rendering an already prepared record. The AI extracts events and evidence from conversations; the scripts do not parse chat history or infer its meaning.

## Viewer options

| | Basic viewer | Interactive attachment viewer |
| --- | --- | --- |
| Setup | Included Python renderer | Separately available Archify, then the included packager |
| Nodes | Details, sources, and resource references | Resource dialog, details, and sources |
| Files | Links to original resources; local links may be restricted | Embedded snapshots with clickable names, preview, download, and original-path copying |
| Diagram | Lightweight graph with SVG export | Archify pan/zoom and diagram controls |
| Best for | A quick map without Archify | Exploring diagrams alongside their files |

**Archify is optional and is not bundled.** The current integration was built against Archify 2.17; upgrades require checking node interactions again. The HTML viewer needs a browser that supports JavaScript, SVG, Dialog, and Blob APIs.

For the attachment viewer, prepare checked Archify HTML files and a manifest using the [integration guide](references/interactive.md), then run:

```sh
python scripts/check_routes.py outputs/my-map/archify-overview.html
python scripts/package_interactive.py outputs/my-map/manifest.json outputs/my-map/chat-archify.html
```

These commands require the diagram and manifest to exist first. The packager checks every pair of connectors, including connectors that share a node. It stops on crossings, overlaps, or routes through nodes. Fix the diagram before packaging; the checker validates orthogonal `M/L` paths and reports unsupported geometry.

## Records and updates

`evolution.json` stores the map independently of its viewer: nodes, relationships, sources, coverage, and unresolved questions. Existing IDs survive updates. `evolution.md` provides a readable index, while `evolution.svg` is an optional vector export.

Proposals, decisions, implementation, and verification are distinct events or states. A later event does not automatically depend on an earlier one. Inferred relationships must be labeled, and missing history remains a stated gap.

## Limitations and data handling

- **History access depends on the host.** Visible messages, supplied exports, and authorized tools define the available scope. A summary cannot reconstruct missing quotations or decisions.
- **Attachments are optional.** The JSON field `project` is retained for format compatibility; for an ordinary conversation, its title is simply the topic.
- **Sharing an attachment viewer shares its embedded files.** Snapshots do not update automatically. Blob links belong to the current page session, not a permanent sharing address.
- **Generation stays local.** The skill does not automatically upload a repository, publish a page, or send conversation content to others.
- **Validation has limits.** Structure, geometry, and file-byte checks do not prove historical accuracy or browser usability. Browser interactions still require separate verification; the existing code-level checks are not a completed browser acceptance test.
- **Documentation language differs from UI language.** These READMEs are bilingual. The bundled skill instructions, example transcript, and viewer labels are currently primarily Chinese.

This source package contains reusable code, templates, instructions, and a fictional example—not real user transcripts or project attachments.

## Repository guide

| Path | Purpose |
| --- | --- |
| [SKILL.md](SKILL.md) | Instructions for the AI agent |
| `agents/openai.yaml` | Codex name, prompt, and explicit-invocation setting |
| [Source guide](references/sources.md) | Access scope, missing records, and citations |
| [Record format](references/graph-format.md) | JSON fields, node states, and relationships |
| [Interactive guide](references/interactive.md) | Archify integration, attachments, and validation |
| `scripts/` / `assets/` | Renderers, checker, packager, and viewer templates |
| `examples/` | Fictional sample conversation and its record |

When changing the skill, use fictional transcripts to demonstrate behavior, preserve existing node IDs and evidence, and keep both READMEs aligned. Do not include private conversations or file snapshots in source contributions.
