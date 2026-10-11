// Focused in-process smoke checks for pending link recovery and aliases.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync(require('node:path').resolve(__dirname, '..', 'assets', 'conversations.js'), 'utf8');
const stored = new Map();
const localStorage = { getItem: key => stored.get(key) || null, setItem: (key, value) => stored.set(key, String(value)), removeItem: key => stored.delete(key) };
const E = { project_id: 'conversation-recovery-smoke', chapters: [{ id: 'chapter', record: { nodes: [{ id: 'node' }], sources: [] } }], conversations: [{ id: 'entry-new', turn_group_id: 'group-new', identity_kind: 'original', role: '用户', text: 'question', line: 1 }] };
const context = vm.createContext({ E, app: { view: 'other' }, localStorage, Map, Set, JSON, Math, Number, String, Array, RegExp, Error, console });
vm.runInContext(source, context, { timeout: 10000 });
const run = expression => vm.runInContext(expression, context, { timeout: 10000 });
const documentFor = (links, extra = {}) => JSON.stringify({ schema: 'chat-archify-manual-conversation-links', version: 1, project_id: E.project_id, links, ...extra });

const valid = { chapter_id: 'chapter', node_id: 'node', group_id: 'group-new' };
const unknown = { chapter_id: 'missing-chapter', node_id: 'missing-node', group_id: 'group-old' };
assert.equal(run(`validateManualConversationLinksDocument(${JSON.stringify(documentFor([valid, unknown]))}).ok`), false, 'strict import keeps its rejection behavior');
const recovered = run(`recoverManualConversationLinks(${JSON.stringify(documentFor([valid, unknown]))})`);
assert.equal(recovered.added, 1);
assert.equal(recovered.pendingAdded, 1);
assert.equal(run('manualConversationExportPayload().links.length'), 1);
assert.equal(run('manualConversationExportPayload().pending.length'), 1, 'unknown links remain exportable pending records');

E.conversation_group_aliases = { 'group-old': 'group-new' };
run('manualConversationLinksHydrated=false; manualConversationLinksState={links:[],storage:"pending"};');
assert.equal(run(`validateManualConversationLinksDocument(${JSON.stringify(documentFor([{ ...unknown, chapter_id: 'chapter', node_id: 'node' }]))}).links[0].group_id`), 'group-new');

const storageKey = run('manualConversationStorageKey()');
stored.set(storageKey, documentFor([valid, unknown], {raw_backup:[{raw:'original-import', source:'import'}]}));
run('manualConversationLinksHydrated=false; manualConversationLinksState={links:[],storage:"pending"};');
assert.equal(run('ensureManualConversationLinks().links.length'), 1);
assert.equal(run('manualConversationExportPayload().pending.length'), 1, 'reload keeps valid links and pending independently');
assert.equal(run('manualConversationExportPayload().raw_backup[0].raw'), 'original-import', 'imported raw backup survives a reload');
stored.set(storageKey, '{bad-json');
run('manualConversationLinksHydrated=false; manualConversationLinksState={links:[],storage:"pending"};');
assert.equal(run('ensureManualConversationLinks().data_status'), 'invalid');
assert.equal(run('manualConversationExportPayload().raw_backup.length'), 1, 'corrupt source is retained for recovery export');
console.log(JSON.stringify({ status: 'passed', checks: ['strict import', 'valid plus pending recovery', 'alias resolution', 'corrupt storage raw backup'] }));
