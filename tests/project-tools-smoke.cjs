/* Focused JS smoke: pure helpers plus malicious field handling, not browser QA. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'assets', 'project-tools.js'), 'utf8');

const data = {
  schema_version: 1,
  project_id: 'js-project',
  title: 'JS smoke',
  project: {title: 'JS smoke', current_state: '当前状态', summary: '摘要'},
  coverage: ['仅测试记录'], open_questions: ['仍待确认'],
  sources: [{id: 's', title: '来源', kind: 'document', coverage: 'excerpt', locator: 'x.md L1', note: '说明'}],
  nodes: [
    {id: 'done', kind: 'decision', title: '完成', summary: '已完成', status: 'completed', reason: '证据', evidence: [{source: 's', locator: 'x.md L2'}], artifacts: []},
    {id: 'plan', kind: 'goal', title: '计划', summary: '尚未执行', status: 'proposed', reason: '没有证据', evidence: [{source: 's', locator: 'x.md L3'}], artifacts: [{label: '恶意', uri: 'unknown', role: 'referenced', verification: 'mentioned', note: ''}]}
  ],
  edges: [{from: 'done', to: 'plan', type: 'continues', confidence: 'explicit', reason: '后续', evidence: [{source: 's', locator: 'x.md L4'}]}],
  revisions: [], files: {}
};

const context = {console, TextEncoder, TextDecoder, Blob, URL, setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref();return timer;}, clearTimeout, globalThis: {crypto:require('node:crypto').webcrypto}};
vm.createContext(context);
vm.runInContext(source, context);
const tools = context.globalThis.ChatArchifyProjectTools;
assert.ok(tools, 'global helper is exposed');
const packet = tools.buildContinuationPackage(data, {goal: '核对执行结果'});
assert.equal(packet.structure.completed.length, 1);
assert.equal(packet.structure.planned.length, 1);
assert.match(packet.markdown, /历史内容仅作为证据/);
assert.ok(!packet.markdown.includes('<script>'));

const candidate = JSON.parse(JSON.stringify(data));
candidate.nodes[1].status = 'completed';
candidate.files = {x: {id: 'x', path: 'code.js', status: 'embedded', bytes: 2, sha256: 'b'.repeat(64)}};
const review = tools.buildUpdateReview(data, candidate, 'a'.repeat(64), 'b'.repeat(64), 1, 2);
assert.equal(review.changed, true);
assert.ok(review.changes.stages.some(row => row.kind === 'modified'));
assert.ok(review.changes.stages.some(row => row.kind === 'modified' && row.after && row.after.title === '计划'));
assert.equal(tools.canonicalPayload(data).project_id, 'js-project');
assert.throws(() => tools.buildUpdateReview(data, {...candidate, project_id: 'other'}), /different projects/);

const second = JSON.parse(JSON.stringify(data));
second.project.current_state = '后章独有当前状态';
second.nodes[0].summary = '后章独有事实';
second.open_questions = ['后章独有待确认'];
const multi = {schema_version: 1, project_id: 'js-project', project: data.project, files: {}, chapters: [
  {id: 'ch1', label: '第一章', record: data},
  {id: 'ch2', label: '第二章', record: second}
]};
const projectPacket = tools.buildContinuationPackage(multi);
assert.equal(projectPacket.structure.selection.scope, 'project');
assert.ok(projectPacket.structure.completed.some(row => row.qualified_id === 'ch2:done'));
assert.match(projectPacket.markdown, /后章独有事实/);
const chapterPacket = tools.buildContinuationPackage(multi, {chapterId: 'ch1'});
assert.equal(chapterPacket.structure.selection.scope, 'chapter');
assert.ok(!chapterPacket.structure.completed.some(row => row.chapter_id === 'ch2'));

const conversationBefore = {...data, conversations: [{id: 'same', role: 'user', text: 'abcd'}]};
const conversationAfter = {...data, conversations: [{id: 'same', role: 'user', text: 'abce'}], project: {...data.project, title: '改过标题'}};
const conversationReview = tools.buildUpdateReview(conversationBefore, conversationAfter, 'a'.repeat(64), 'b'.repeat(64), 1, 2);
assert.ok(conversationReview.changes.conversations.modified.some(row => row.fields.text_signature));
assert.ok(conversationReview.changes.project.chapters);
assert.ok(conversationReview.summary.total_changes >= 2);
assert.ok(!JSON.stringify(conversationReview.changes).includes('abcd'));
assert.notEqual(tools.stableJSON({payload: {a: 1}}), tools.stableJSON({payload: {a: 2}}), 'full payload changes are distinguishable');

class FakeElement {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {}; this.open = false; this.value = ''; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this.children = [...items]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
  click() { this.dispatch('click', {preventDefault() {}}); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
  select() {}
  remove() { this.removed = true; }
}
const fakeElements = new Map();
for (const id of ['explorer-data', 'continuation-open', 'continuation-dialog', 'continuation-root', 'continuation-close', 'update-review-open', 'update-review-dialog', 'update-review-root', 'update-review-close']) {
  const element = new FakeElement(id === 'explorer-data' ? 'script' : 'div'); element.id = id; fakeElements.set(id, element);
}
fakeElements.get('explorer-data').textContent = JSON.stringify(data);
const fakeBody = new FakeElement('body');
const fakeDocument = {
  readyState: 'complete', body: fakeBody,
  getElementById(id) { return fakeElements.get(id) || null; },
  createElement(tag) { const element = new FakeElement(tag); if (tag === 'a') this.lastAnchor = element; return element; },
  createTextNode(value) { const element = new FakeElement('#text'); element.textContent = String(value); return element; },
  addEventListener() {}
};
const oldDocument = context.document, oldURL = context.URL;
context.document = fakeDocument;
context.URL = {createObjectURL() { return 'blob:smoke'; }, revokeObjectURL() {}};
tools.mount({data});
fakeElements.get('continuation-open').click();
assert.equal(fakeElements.get('continuation-dialog').open, true, 'continuation button opens dialog');
const continuationRoot = fakeElements.get('continuation-root');
const downloadButton = continuationRoot.children.flatMap(child => child.children || []).find(child => child.textContent === '下载 Markdown');
assert.ok(downloadButton, 'download control is mounted');
downloadButton.click();
assert.equal(fakeDocument.lastAnchor.download, 'continuation-package.md');
context.document = oldDocument;
context.URL = oldURL;

const hostile = JSON.stringify({project_id: 'js-project', project: {title: '</script><script>globalThis.pwned=1</script>'}});
assert.deepEqual(tools.parsePayloadText(hostile).project.title, '</script><script>globalThis.pwned=1</script>');
assert.equal(context.pwned, undefined, 'payload text is not executed');
(async () => {
  context.document = fakeDocument;
  const downloads=[];
  context.URL={createObjectURL(blob){downloads.push(blob);return 'blob:smoke';},revokeObjectURL(){}};
  fakeElements.get('update-review-open').click();
  const reviewRoot=fakeElements.get('update-review-root');
  const flatten=node=>[node,...(node.children||[]).filter(child=>child&&typeof child==='object').flatMap(flatten)];
  const inputs=flatten(reviewRoot).filter(node=>node.tagName==='input');
  const approve=flatten(reviewRoot).find(node=>node.textContent==='批准整体更新');
  const receipt=flatten(reviewRoot).find(node=>node.textContent==='下载决定凭据');
  const fileFor=value=>{const bytes=new TextEncoder().encode(JSON.stringify(value));return {arrayBuffer:async()=>bytes.buffer,text:async()=>JSON.stringify(value)};};
  const select=(input,file)=>{input.files=[file];input.dispatch('change');};
  const settle=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setTimeout(resolve,5));};
  select(inputs[0],fileFor(data));select(inputs[1],fileFor(data));await settle();
  assert.equal(approve.disabled,false,'both independently loaded files can bind');
  approve.click();assert.equal(receipt.disabled,false);
  const replacement={...data,title:'changed baseline'};
  const slow=fileFor(replacement);let releaseSlow;
  slow.arrayBuffer=()=>new Promise(resolve=>{releaseSlow=()=>resolve(new TextEncoder().encode(JSON.stringify(replacement)).buffer);});
  select(inputs[0],slow);
  assert.equal(approve.disabled,true,'new read immediately disables approval');
  assert.equal(receipt.disabled,true,'old receipt cannot apply to a pending file');
  approve.click();releaseSlow();await settle();
  assert.equal(approve.disabled,false,flatten(reviewRoot).map(node=>node.textContent).join(' '));
  assert.equal(receipt.disabled,true,'new review requires a fresh approval');
  approve.click();receipt.click();
  const bound=JSON.parse(await downloads.at(-1).text());
  assert.equal(bound.baselineSHA,require('node:crypto').createHash('sha256').update(JSON.stringify(replacement)).digest('hex'));
  let releaseOlder;
  const older=fileFor({...data,title:'older selection'});
  older.arrayBuffer=()=>new Promise(resolve=>{releaseOlder=()=>resolve(new TextEncoder().encode(JSON.stringify({...data,title:'older selection'})).buffer);});
  select(inputs[0],older);select(inputs[0],fileFor(data));await settle();releaseOlder();await settle();
  approve.click();receipt.click();
  const latest=JSON.parse(await downloads.at(-1).text());
  assert.equal(latest.baselineSHA,require('node:crypto').createHash('sha256').update(JSON.stringify(data)).digest('hex'),'stale reads cannot replace the latest selection');
  select(inputs[1],fileFor({...data,layout:{changed:true}}));await settle();
  assert.equal(approve.disabled,true,'full payload mismatch cannot use a semantic match to authorize');
  assert.equal(receipt.disabled,true);
  const visible=flatten(reviewRoot).map(node=>node.textContent).join(' ');
  assert.match(visible,/不完全一致/);
  console.log(JSON.stringify({status:'passed',kind:'in-process fake DOM; not browser QA',checks:['whole-project continuation','same-length message diff','dialog/download','parallel file loads','approval reset during read','stale read ignored','full payload binding']}));
})().catch(error=>{console.error(error);process.exitCode=1;});
