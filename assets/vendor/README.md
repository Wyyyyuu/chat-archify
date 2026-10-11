# Vendored Markdown tokenizer

- Library: Marked 17.0.5
- Upstream: https://github.com/markedjs/marked
- File: `marked.umd.js`, copied from the installed 17.0.5 distribution without modification.
- License: [MIT](marked-LICENSE.md)

Chat Archify uses `marked.lexer()` only. Its own `markdown.js` builds a restricted DOM tree; it does not insert HTML produced by the parser. The bundle is embedded into the standalone viewer, so document previews do not need a network request.
