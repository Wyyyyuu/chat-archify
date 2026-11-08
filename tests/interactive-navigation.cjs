// Portable in-process navigation smoke test. This uses a small fake DOM and
// must not be reported as real-browser or visual acceptance evidence.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const skillRoot = path.resolve(__dirname, '..');
const htmlPath = process.argv[2] && path.resolve(process.argv[2]);
if (!htmlPath || !fs.existsSync(htmlPath)) throw new Error('Usage: node tests/interactive-navigation.cjs <packaged-demo.html>');
const page = fs.readFileSync(htmlPath, 'utf8');
const payloadMatch = page.match(/<script type="application\/json" id="explorer-data">([\s\S]*?)<\/script>/);
assert.ok(payloadMatch, 'packaged demo contains the data payload');
const payload = JSON.parse(payloadMatch[1]);

let activeDocument = null;
class Element {
  constructor(tag) {
    this.tagName = tag.toLowerCase(); this.children = []; this.parentElement = null; this.dataset = {}; this.attrs = {}; this.listeners = {};
    this.clientWidth=620;this.clientHeight=680;this.style = {setProperty(name,value){this[name]=value;},getPropertyValue(name){return this[name]||'';}}; this._text = ''; this.className = ''; this.hidden = false; this.open = false; this.scrollTop = 0; this.scrollLeft = 0; this.classList = {
      add: (...names) => { for (const name of names) if (!this.className.split(/\s+/).includes(name)) this.className = [this.className,name].filter(Boolean).join(' '); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => name && !names.includes(name)).join(' '); },
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name,force) => { const has=this.classList.contains(name),add=force===undefined?!has:Boolean(force);if(add&&!has)this.className=[this.className,name].filter(Boolean).join(' ');if(!add&&has)this.classList.remove(name);return add; }
    };
  }
  get id() { return this._id || ''; } set id(value) { this._id=String(value); }
  get childNodes() { return this.children; }
  get textContent() { return this._text+this.children.map(child=>child.textContent).join(''); }
  set textContent(value) { for(const child of this.children)child.parentElement=null;this.children=[];this._text=String(value??''); }
  get href() { return this.attrs.href||''; } set href(value) { this.attrs.href=String(value); }
  get src() { return this.attrs.src||''; } set src(value) { this.attrs.src=String(value); }
  get value() { return this._value||''; } set value(value) { this._value=String(value??''); }
  get parentNode() { return this.parentElement; }
  append(...children) { for(let child of children){if(!(child instanceof Element)){const text=new Element('#text');text.textContent=String(child);child=text;}child.parentElement=this;this.children.push(child);} }
  prepend(...children) { for(let child of [...children].reverse()){if(!(child instanceof Element)){const text=new Element('#text');text.textContent=String(child);child=text;}child.parentElement=this;this.children.unshift(child);} }
  replaceChildren(...children) { for(const child of this.children)child.parentElement=null;this.children=[];this._text='';this.append(...children); }
  replaceChild(next,old) { const i=this.children.indexOf(old);if(i>=0)this.children[i]=next;else this.children.push(next);next.parentElement=this;old.parentElement=null;return old; }
  setAttribute(name,value) { this.attrs[name]=String(value);if(name==='class')this.className=String(value); }
  getAttribute(name) { return this.attrs[name]??null; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(type,fn) { (this.listeners[type]??=[]).push(fn); }
  dispatchEvent(e) { e.target??=this;for(let node=this;node;node=node.parentElement){e.currentTarget=node;for(const fn of node.listeners?.[e.type]||[])fn(e);if(e.stopped)break;}return true; }
  click() { this.dispatchEvent({type:'click',target:this,currentTarget:this,button:0,preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}}); }
  setPointerCapture() {}
  releasePointerCapture() {}
  matches(selector) {
    return selector.split(',').some(part=>{
      part=part.trim();const id=part.match(/^\[data-node-id="([^"]+)"\]$/);if(id)return this.dataset.nodeId===id[1];
      if(part==='[data-node-id][aria-pressed="true"]')return Boolean(this.dataset.nodeId)&&this.getAttribute('aria-pressed')==='true';
      if(part==='[data-node-id]')return Boolean(this.dataset.nodeId);if(part==='[data-chapter]')return Boolean(this.dataset.chapter);
      if(part==='[data-source-start][data-source-end]')return this.dataset.sourceStart!==undefined&&this.dataset.sourceEnd!==undefined;
      if(part==='[data-line]')return this.dataset.line!==undefined;if(part.startsWith('#'))return this.id===part.slice(1);if(part.startsWith('.'))return this.classList.contains(part.slice(1));
      if(part.startsWith('[')){const attr=part.match(/^\[([\w-]+)\]$/);return Boolean(attr&&this.getAttribute(attr[1])!==null);}return this.tagName===part.toLowerCase();
    });
  }
  querySelectorAll(selector) { return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
  closest(selector) { for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null; }
  remove() { if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null; }
  focus() { if(activeDocument)activeDocument.activeElement=this; }
  showModal() { this.open=true; this.setAttribute('open',''); }
  close() { this.open=false; this.removeAttribute('open'); this.dispatchEvent({type:'close',target:this}); }
  select() {}
  scrollIntoView() { this.scrolled=true; }
}
class FakeTextNode {
  constructor(parent,value) { this.parentElement=parent;this.parentNode=parent;this.nodeValue=value; }
  splitText(offset) { const rest=new FakeTextNode(this.parentElement,this.nodeValue.slice(offset));this.nodeValue=this.nodeValue.slice(0,offset);return rest; }
}
const body = new Element('body'), ids = new Map();
const template = page.split('<script type="application/json"')[0];
for(const match of template.matchAll(/<([a-z][\w-]*)\b[^>]*\bid="([^"]+)"[^>]*>/gi)){const node=new Element(match[1]);node.id=match[2];for(const attr of match[0].matchAll(/([\w-]+)="([^"]*)"/g))node.setAttribute(attr[1],attr[2]);ids.set(node.id,node);body.append(node);}
const dataElement=new Element('script');dataElement.id='explorer-data';dataElement.textContent=JSON.stringify(payload);ids.set(dataElement.id,dataElement);body.append(dataElement);
const findId=(node,id)=>node.id===id?node:node.children.map(child=>findId(child,id)).find(Boolean)||null;
const doc={body,createElement:tag=>new Element(tag),getElementById:id=>ids.get(id)||findId(body,id),querySelectorAll:s=>body.querySelectorAll(s),listeners:{},matches:()=>false,addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},createTreeWalker(root){const nodes=[];const visit=n=>{if(n._text)nodes.push(new FakeTextNode(n,n._text));for(const child of n.children)visit(child);};visit(root);let i=0;return{nextNode:()=>nodes[i++]||null};}};
doc.documentElement=new Element('html');
const localeMatch=page.match(/<script type="application\/json" id="locale-data">([\s\S]*?)<\/script>/);
if(localeMatch){const localeElement=new Element('script');localeElement.id='locale-data';localeElement.textContent=localeMatch[1];ids.set('locale-data',localeElement);body.append(localeElement);}
// Static UI slots, including those without IDs, are represented for locale checks.
for(const match of template.matchAll(/<([a-z][\w-]*)\b[^>]*data-i18n(?:-[\w-]+)?="[^"]+"[^>]*>/gi)){
 const id=match[0].match(/\bid="([^"]+)"/),node=id?ids.get(id[1]):new Element(match[1]);
 if(!node)continue;for(const attr of match[0].matchAll(/([\w-]+)="([^"]*)"/g))node.setAttribute(attr[1],attr[2]);if(!id)body.append(node);
}
body.parentElement=doc;
activeDocument=doc;
let desktop=true;
const windowListeners={};const window={matchMedia:query=>({matches:query.includes('min-width')?desktop:false}),addEventListener(type,fn){(windowListeners[type]??=[]).push(fn);},dispatchEvent(e){for(const fn of windowListeners[e.type]||[])fn(e);}};
const location={hash:''},historyRows=[];let historyIndex=-1;
const history={get state(){return historyRows[historyIndex]?.state||null;},replaceState(state,_title,url){if(historyIndex<0){historyRows.push({state,url});historyIndex=0;}else historyRows[historyIndex]={state,url};if(url&&String(url).includes('#'))location.hash=String(url).slice(String(url).indexOf('#'));},pushState(state,_title,url){historyRows.splice(historyIndex+1);historyRows.push({state,url});historyIndex++;if(url&&String(url).includes('#'))location.hash=String(url).slice(String(url).indexOf('#'));},back(){if(historyIndex>0){historyIndex--;location.hash=historyRows[historyIndex].url;window.dispatchEvent({type:'popstate',state:this.state});}},forward(){if(historyIndex+1<historyRows.length){historyIndex++;location.hash=historyRows[historyIndex].url;window.dispatchEvent({type:'popstate',state:this.state});}}};
const blobs=new Map();let blobSerial=0;class TestURL extends URL{static createObjectURL(blob){const u=`blob:portable-${++blobSerial}`;blobs.set(u,blob);return u;}static revokeObjectURL(){}}
const storageRows=new Map();const localStorage={getItem:key=>storageRows.get(key)||null,setItem:(key,value)=>storageRows.set(key,String(value)),removeItem:key=>storageRows.delete(key)};
class Observer{constructor(fn){this.callback=fn;}observe(){}disconnect(){}}
const context=vm.createContext({document:doc,window,history,location,localStorage,navigator:{clipboard:{writeText:async()=>{}}},URL:TestURL,URLSearchParams,TextDecoder,Uint8Array,Blob,atob,Map,Set,console,MutationObserver:Observer,NodeFilter:{SHOW_TEXT:4},setTimeout:fn=>{fn();return 1;},clearTimeout:()=>{},requestAnimationFrame:fn=>fn(),matchMedia:window.matchMedia,TextEncoder});
const assetScript=page.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(assetScript,context,{timeout:10000});
const run=source=>vm.runInContext(source,context),$=id=>doc.getElementById(id==='conversation-content'?'conversation-list':id);
const initialLocale=payload.locale||'zh-CN';assert.equal(run('window.ChatArchifyI18n.language'),initialLocale);assert.equal(doc.documentElement.getAttribute('lang'),initialLocale);if(initialLocale==='en')assert.equal($('continuation-open').textContent,'Export handoff');run("window.ChatArchifyI18n.setLanguage('zh-CN')");
const sourceChapter=payload.chapters.find(item=>item.id===(payload.navigation?.source_chapter||payload.chapters[0].id))||payload.chapters[0],record=sourceChapter.record;
assert.equal(run('app.view'),'overview','a fresh page opens the project flowchart');
assert.equal($('reader-panel').hidden,false,'desktop keeps the detail column visible');
assert.equal($('chapter-panel').hidden,false,'desktop keeps the chapter column visible');
assert.equal($('graph-empty').hidden,false,'the center column starts with an empty-state prompt');
assert.ok($('reader-content').textContent.includes('选择流程中的节点'));
assert.ok($('overview-graph').querySelectorAll('.graph-node').length>0);
assert.equal(run('typeof window.ChatArchifyProjectTools.mount'),'function','the packaged page includes Pro tools');
$('continuation-open').click();assert.equal($('continuation-dialog').open,true,'packaged continuation entry opens');
assert.ok($('continuation-root').textContent.includes('整个项目'),'default continuation covers the project');
$('continuation-close').click();assert.equal($('continuation-dialog').open,false);
$('update-review-open').click();assert.equal($('update-review-dialog').open,true,'packaged review entry opens');
$('update-review-close').click();assert.equal($('update-review-dialog').open,false);
assert.equal(run('app.view'),'overview','tools do not replace the active graph route');
assert.equal($('node-picker'),null,'node picker removed');assert.equal($('mobile-chapter'),null,'chapter picker removed');assert.equal($('chapters'),null,'legacy chapter navigation removed');
const emptyReader=$('reader-content').children[0];desktop=false;window.dispatchEvent({type:'resize'});
assert.equal($('chapter-panel').hidden,true,'the first resize can cross directly to mobile');assert.equal($('reader-panel').hidden,true);assert.equal($('reader-content').children[0],emptyReader);
desktop=true;window.dispatchEvent({type:'resize'});assert.equal($('chapter-panel').hidden,false);assert.equal($('reader-panel').hidden,false);
for(const id of ['splitter-overview-graph','splitter-graph-reader']){assert.equal($(id).getAttribute('role'),'separator');assert.equal($(id).getAttribute('aria-orientation'),'vertical');}
$('workspace').clientWidth=1100;run('applyWorkbenchWidths()');const firstSplitter=$('splitter-overview-graph'),beforeOverview=Number.parseFloat($('workspace').style.getPropertyValue('--overview-width'));
firstSplitter.dispatchEvent({type:'pointerdown',button:0,clientX:100,pointerId:1,preventDefault(){}});firstSplitter.dispatchEvent({type:'pointermove',clientX:132,pointerId:1});firstSplitter.dispatchEvent({type:'pointerup',clientX:132,pointerId:1});
const afterOverview=Number.parseFloat($('workspace').style.getPropertyValue('--overview-width'));assert.ok(afterOverview>beforeOverview,'pointer drag adjusts the overview column');assert.ok(storageRows.has('chat-archify:workbench-widths:v6'),'column widths persist locally');
firstSplitter.dispatchEvent({type:'keydown',key:'Home',preventDefault(){}});assert.equal(firstSplitter.getAttribute('aria-valuenow'),firstSplitter.getAttribute('aria-valuemin'),'Home clamps the overview column');firstSplitter.dispatchEvent({type:'keydown',key:'End',preventDefault(){}});assert.equal(firstSplitter.getAttribute('aria-valuenow'),firstSplitter.getAttribute('aria-valuemax'),'End clamps the overview column at its maximum');
const secondSplitter=$('splitter-graph-reader');secondSplitter.dispatchEvent({type:'keydown',key:'Home',preventDefault(){}});assert.equal(secondSplitter.getAttribute('aria-valuenow'),secondSplitter.getAttribute('aria-valuemax'),'reader splitter Home keeps the graph usable');
const overviewRow=$('overview-graph').querySelector('.graph-node');assert.ok(overviewRow);overviewRow.click();
assert.equal(run('app.view'),'chapter','overview click opens the chapter flow');assert.equal(run('app.node'),null,'overview click does not preselect a detail node');assert.equal($('graph-empty').hidden,true);assert.ok($('native-graph').querySelectorAll('.graph-node').length>0,'chapter graph appears');
const firstChapterRow=$('native-graph').querySelector('.graph-node');firstChapterRow.click();assert.equal(run('app.view'),'node');assert.equal(run('app.node'),firstChapterRow.dataset.nodeId);const firstChapterNode=(payload.chapters.find(item=>item.id===run('app.chapter'))?.record.nodes||[]).find(node=>node.id===firstChapterRow.dataset.nodeId);assert.equal($('reader-title').textContent,firstChapterNode?.display_title||firstChapterNode?.title);
assert.equal($('reader-content').querySelectorAll('button').some(node=>node.textContent==='复制阶段定位'),false,'node detail no longer exposes duplicate stage locator copy');assert.equal($('reader-content').querySelector('.conversation-context'),null,'node detail no longer repeats a conversation context card');assert.ok($('reader-content').querySelectorAll('button').some(node=>node.textContent.startsWith('打开对话索引')),'stage details retain a conversation index entry point');
// Exercise real UI actions with real fixture IDs; bindings exist only in this VM.
function testConversationModuleLinks(){
 if(!payload.conversations.length)return;
 const nodes=payload.chapters.flatMap(ch=>ch.record.nodes.map(node=>({chapter:ch.id,node}))),targetA=nodes.find(t=>t.chapter==='foundation'&&t.node.id==='b_permanent')||nodes.find(t=>!t.node.conversation_source_entry_ids?.length)||nodes[0],targetB=nodes.find(t=>t.chapter!==targetA.chapter)||nodes.find(t=>t.node.id!==targetA.node.id);
 if(!targetB)return;
 const entry=payload.conversations.find(e=>e.turn_group_id&&payload.conversations.some(other=>other.id!==e.id&&other.turn_group_id===e.turn_group_id))||payload.conversations[0],groupId=entry.turn_group_id||entry.id,group=payload.conversations.filter(e=>(e.turn_group_id||e.id)===groupId),groupIds=group.map(e=>e.id),facts=run('JSON.stringify({chapters:E.chapters,files:E.files,conversations:E.conversations})');
 const q=JSON.stringify,invoke=(name,...args)=>run(`${name}(${args.map(q).join(',')})`),buttons=root=>root.querySelectorAll('button'),press=(root,text)=>{const b=buttons(root).find(b=>b.textContent===text);assert.ok(b,`available UI action: ${text}`);b.click();},groupCard=()=>$('conversation-list').querySelectorAll('.conversation-result').find(card=>groupIds.includes(card.dataset.conversationId));
 const nodeArg={chapter:targetA.chapter,node:targetA.node.id};
 invoke('navigateNode',targetA.node.id,targetA.chapter);press($('reader-content'),'关联已有对话');
 assert.equal(run('app.conversationScope'),null,'direct module picker explicitly opens all saved turns');assert.equal(run('app.conversationAssociationPicker'),true);assert.equal(run('initialState().conversationAssociationTarget.node'),targetA.node.id,'deep links retain the exact module target');assert.ok(groupCard());
 press($('reader-content'),'退出关联选择');assert.equal(run('app.conversationAssociationPicker'),false,'picker can return to the module scope');press($('reader-content'),'关联已有对话');
 const pickerSearch=$('reader-content').querySelectorAll('input').find(input=>input.getAttribute('aria-label')==='搜索已保存对话摘录');pickerSearch.value=entry.source_title||'';pickerSearch.dispatchEvent({type:'input'});assert.ok(groupCard(),'filtered picker retains matching turn');
 const bindButton=buttons(groupCard()).find(b=>b.textContent==='关联此对话');bindButton.dispatchEvent({type:'keydown',key:'Enter',preventDefault(){}});assert.equal(run('app.conversationId'),null,'Enter on the nested association control does not also open the card');
 press(groupCard(),'关联此对话');assert.equal(run('app.conversationQuery'),'','association completion clears picker query');assert.equal(run('app.conversationTask'),'','association completion clears picker task');assert.equal(invoke('manualConversationLinksForNode',targetA.chapter,targetA.node.id).length,1);assert.equal(run('app.conversationAssociationPicker'),false);assert.ok(groupIds.every(id=>run('app.conversationScope').includes(id)),'whole saved turn appears in module index');
 groupCard().click();const dialog=$('conversation-dialog'),content=$('conversation-dialog-content');assert.equal(dialog.open,true);content.scrollTop=164;content.dispatchEvent({type:'scroll'});assert.ok(content.textContent.includes('手动关联'));press(content,'移除手动关联');assert.equal(dialog.open,true,'removal keeps the conversation open');assert.equal(content.scrollTop,164,'removal preserves reading position');assert.equal(invoke('manualConversationLinksForNode',targetA.chapter,targetA.node.id).length,0);$('conversation-dialog-close').click();
 invoke('navigateToConversationIndex',null,'');assert.equal(run('app.conversationAssociationTarget'),null);groupCard().click();content.scrollTop=127;content.dispatchEvent({type:'scroll'});
 const bind=t=>{const select=content.querySelectorAll('select').find(e=>e.getAttribute('aria-label')==='选择要关联的模块');assert.ok(select,'global conversation reader has a module selector');select.value=t.chapter+'\u0000'+t.node.id;press(content,'关联到所选模块');};
 bind(targetA);bind(targetB);bind(targetB);assert.equal(run('manualConversationExportPayload().links.length'),2,'one turn links to two modules without duplicate rows');assert.equal(content.scrollTop,127,'adding links keeps dialog scroll');
 const confirmed=invoke('linkedConversationModuleRecords',group),candidates=invoke('linkedConversationModuleCandidates',group);assert.equal(new Set(confirmed.map(r=>r.chapter+'/'+r.node)).size,confirmed.length,'group links are deduplicated');assert.ok(candidates.every(c=>!confirmed.some(r=>r.chapter===c.chapter&&r.node===c.node)),'source-only candidates do not inflate confirmed module counts');
 const row=content.querySelectorAll('.conversation-module-link').find(r=>r.querySelector('strong')?.textContent===(targetB.node.display_title||targetB.node.title));assert.ok(row);press(row,'查看模块');assert.equal(run('app.view'),'node');assert.equal(run('app.node'),targetB.node.id);assert.equal(run('app.chapter'),targetB.chapter);assert.ok(invoke('conversationScopeForNode',targetB.node,targetB.chapter).ids.includes(entry.id));history.back();assert.equal(dialog.open,true);assert.equal(content.scrollTop,127);
 run('globalThis.linkExportCapture=null;globalThis.savedLinkDownload=downloadBytes;downloadBytes=(bytes,name,mime)=>{globalThis.linkExportCapture={text:new TextDecoder().decode(bytes),name,mime};savedLinkDownload(bytes,name,mime);};exportManualConversationLinks();downloadBytes=savedLinkDownload;');
 const captured=run('linkExportCapture'),exported=JSON.parse(captured.text);assert.equal(captured.name,'chat-archify-conversation-links.json');assert.deepEqual(Object.keys(exported).sort(),['links','project_id','schema','version']);assert.ok(exported.links.every(link=>Object.keys(link).sort().join(',')==='chapter_id,group_id,node_id'),'exports contain only association metadata');
 run('manualConversationLinksState={links:[],storage:"local"};manualConversationLinksHydrated=false;');assert.equal(run('ensureManualConversationLinks().links.length'),2,'startup hydration restores locally persisted links');
 run('manualConversationLinksState.links=[];persistManualConversationLinks();');assert.equal(invoke('importManualConversationLinks',captured.text).added,2,'metadata round trip restores links');assert.equal(invoke('importManualConversationLinks',captured.text).added,0,'repeat import merges duplicates');
 const before=run('JSON.stringify(manualConversationExportPayload())');for(const bad of [{...exported,project_id:'another-project'},{...exported,links:[{...exported.links[0],node_id:'missing-node'}]},{...exported,links:[{...exported.links[0],group_id:'missing-group'}]},{...exported,links:[exported.links[0],{...exported.links[1],chapter_id:'missing-chapter'}]},{...exported,version:99}]){assert.equal(invoke('importManualConversationLinks',JSON.stringify(bad)).ok,false);assert.equal(run('JSON.stringify(manualConversationExportPayload())'),before,'invalid imports do not partially change links');}
 assert.equal(invoke('importManualConversationLinks','{broken').ok,false);assert.equal(invoke('importManualConversationLinks',' '.repeat(1000001)).ok,false);
 const originalExact=nodes.find(t=>t.node.conversation_entry_ids?.some(id=>groupIds.includes(id)));if(originalExact){invoke('addManualConversationLink',originalExact.chapter,originalExact.node.id,groupId,{refresh:false});invoke('removeManualConversationLink',originalExact.chapter,originalExact.node.id,groupId,{refresh:false});assert.ok(invoke('conversationScopeForNode',originalExact.node,originalExact.chapter).ids.includes(entry.id),'removing manual metadata retains original evidence');const scope=invoke('conversationScopeForNode',originalExact.node,originalExact.chapter).ids;const unrelated=(originalExact.node.conversation_source_entry_ids||[]).find(id=>!groupIds.includes(id)&&!originalExact.node.conversation_entry_ids.includes(id));if(unrelated&&!run(`expandConversationIds(${q(originalExact.node.conversation_entry_ids)})`).includes(unrelated))assert.ok(!scope.includes(unrelated),'exact module scope is not widened to its source task');}
 const persistedBeforeBlocked=run('JSON.stringify(manualConversationExportPayload())');
 const get=localStorage.getItem,set=localStorage.setItem;localStorage.getItem=()=>{throw Error('blocked');};localStorage.setItem=()=>{throw Error('blocked');};run('manualConversationLinksHydrated=false;manualConversationLinksState={links:[],storage:"pending"};');const session=invoke('addManualConversationLink',targetA.chapter,targetA.node.id,groupId);assert.equal(session.ok,true);assert.equal(session.persisted,false);assert.equal(run('manualConversationLinksState.storage'),'session');assert.ok(content.textContent.includes('关闭页面后会丢失'),'blocked persistence is stated in the active reader');assert.ok(run('manualConversationExportPayload().links.length')>0,'session bindings remain exportable');
 localStorage.getItem=get;localStorage.setItem=set;run('manualConversationLinksHydrated=false;ensureManualConversationLinks();');assert.equal(run('JSON.stringify(manualConversationExportPayload())'),persistedBeforeBlocked,'blocked storage did not overwrite saved links');run('manualConversationLinksState.links=[];persistManualConversationLinks();conversationLinkNotice={kind:"",text:""};');
 assert.equal(run('JSON.stringify({chapters:E.chapters,files:E.files,conversations:E.conversations})'),facts,'all original records, files and messages remain immutable');$('conversation-dialog-close').click();invoke('navigateNode',record.nodes[0].id,sourceChapter.id);
 console.log(JSON.stringify({status:'passed',check:'V12 manual module links',kind:'in-process DOM; no browser QA',checks:['empty module picker and exit','whole turn to multiple modules','dialog refresh and scroll','bidirectional module navigation','metadata export/import and invalid rejection','local hydration and blocked-storage fallback','original evidence and source candidate separation']}));
}
testConversationModuleLinks();
// Scope, picker filters, exact message selection and breadcrumb restoration.
(function testScopedConversationNavigation(){
 const group=payload.conversations.find(entry=>entry.turn_group_id&&payload.conversations.some(other=>other.id!==entry.id&&other.turn_group_id===entry.turn_group_id));if(!group)return;
 const parts=payload.conversations.filter(entry=>entry.turn_group_id===group.turn_group_id),exact=parts.find(entry=>!['用户','user'].includes(String(entry.role||'').toLowerCase()))||parts[parts.length-1],target=payload.chapters[0].record.nodes[0],chapter=payload.chapters[0],file=Object.keys(payload.files)[0],q=JSON.stringify;
 const invoke=(name,...args)=>run(`${name}(${args.map(q).join(',')})`),press=(root,label)=>{const control=root.querySelectorAll('button').find(button=>button.textContent===label);assert.ok(control,`available action: ${label}`);control.click();};
 const before=run(`JSON.stringify(findNode(${q(target.id)},${q(chapter.id)}))`);
 run(`findNode(${q(target.id)},${q(chapter.id)}).conversation_entry_ids=[];findNode(${q(target.id)},${q(chapter.id)}).conversation_source_entry_ids=[${q(exact.id)}]`);
 invoke('navigateNode',target.id,chapter.id);press($('reader-content'),'打开对话索引');assert.equal(run('app.conversationScope.length'),0,'source candidates do not become confirmed associations');assert.ok($('conversation-list').textContent.includes('未收录此阶段的原始对话'));
 press($('reader-content'),'查看同来源候选（未确认关联）');assert.equal(run('app.conversationScopeMode'),'source');assert.ok($('conversation-list').querySelector('.conversation-result'));press($('reader-content'),'返回已关联对话');assert.equal(run('app.conversationScopeMode'),'none');run(`app.conversationTask='missing task';renderRoute()`);assert.equal(run('app.conversationTask'),'','obsolete task filter is corrected');
 run(`app.conversationQuery='stale query';app.conversationTask='stale task';startConversationAssociationPicker()`);assert.equal(run('app.conversationQuery'),'');assert.equal(run('app.conversationTask'),'');assert.ok($('conversation-list').querySelector('.conversation-result'));
 run(`app.conversationQuery='stale query';app.conversationTask='stale task';startConversationAssociationPicker()`);assert.equal(run('app.conversationQuery'),'');assert.equal(run('app.conversationTask'),'');
 run(`findNode(${q(target.id)},${q(chapter.id)}).conversation_entry_ids=[${q(exact.id)}]`);invoke('navigateNode',target.id,chapter.id);press($('reader-content'),'打开对话索引');const card=$('conversation-list').querySelector('.conversation-result');assert.equal(card.dataset.conversationId,exact.id,'exact association selects the matching message rather than the user lead');assert.ok(card.textContent.includes('阶段匹配片段'));assert.equal(invoke('conversationScopeForNode',invoke('findNode',target.id,chapter.id),chapter.id).sourceIds.length,0,'confirmed turns are excluded from unconfirmed candidates');card.click();assert.equal(run('app.conversationId'),exact.id);assert.ok($('conversation-dialog-content').querySelectorAll('.conversation-message').some(message=>message.dataset.entryId===exact.id&&message.getAttribute('aria-current')==='true'));$('conversation-dialog-close').click();
 run(`app.conversationQuery='saved query';app.conversationTask=${q(group.source_title||'')};persistState()`);const expected=run('JSON.stringify({scope:app.conversationScope,target:app.conversationAssociationTarget,query:app.conversationQuery,task:app.conversationTask})');if(file){invoke('openFile',file);invoke('navigateToConversationIndex',null,'');const crumbs=run('visibleCrumbs()'),index=crumbs.findIndex(item=>item.view==='conversations'&&item.conversationQuery==='saved query');assert.ok(index>=0,'index snapshot remains in breadcrumb trail');invoke('openCrumb',index);assert.equal(run('JSON.stringify({scope:app.conversationScope,target:app.conversationAssociationTarget,query:app.conversationQuery,task:app.conversationTask})'),expected,'breadcrumb restores scope, target, and filters');history.back();history.back();assert.equal(run('JSON.stringify({scope:app.conversationScope,target:app.conversationAssociationTarget,query:app.conversationQuery,task:app.conversationTask})'),expected,'history restores index context');}
 run(`Object.assign(findNode(${q(target.id)},${q(chapter.id)}),${before})`);invoke('navigateNode',target.id,chapter.id);
})();

if(process.argv.includes('--all-data')){
 // User-facing conversation behavior: filtered cards still open, and new turns
 // start at the top while Back restores the previous turn's independent scroll.
 if(payload.conversations.length>1){
  run('navigateToConversationIndex(null)');const indexHash=location.hash;
  assert.equal(run('initialState().view'),'conversations','an index-only deep link stays in the index');assert.equal(run('initialState().conversationId'),null);
  let cards=$('conversation-list').querySelectorAll('.conversation-result');assert.ok(cards.length>1);cards[0].click();assert.equal($('conversation-dialog').open,true,'a card opens the independent conversation reader');assert.ok($('conversation-dialog-content').textContent.includes('已保存摘录'),'dialog marks saved source coverage');
  $('conversation-dialog-content').scrollTop=137;$('conversation-dialog-content').dispatchEvent({type:'scroll'});const previousId=run('app.conversationId');
  $('conversation-list').querySelectorAll('.conversation-result')[1].click();assert.equal($('conversation-dialog').open,true);assert.equal($('conversation-dialog-content').scrollTop,0,'a new turn starts at its beginning');
  $('conversation-dialog-content').scrollTop=212;$('conversation-dialog-content').dispatchEvent({type:'scroll'});history.back();assert.equal(run('app.conversationId'),previousId);assert.equal($('conversation-dialog-content').scrollTop,137);history.forward();assert.equal($('conversation-dialog-content').scrollTop,212);$('conversation-dialog-close').click();assert.equal(run('app.conversationId'),null,'closing a nested reading turn returns to the index');assert.equal($('conversation-dialog').open,false);assert.equal(doc.activeElement?.dataset?.conversationId, cards[1].dataset.conversationId,'close returns focus to the current card');
  const paired=payload.conversations.find(e=>['助手','assistant'].includes(e.role)&&payload.conversations.some(u=>u.turn_group_id===e.turn_group_id&&['用户','user'].includes(u.role)));
  if(paired){
   const group=payload.conversations.filter(e=>e.turn_group_id===paired.turn_group_id),question=group.find(e=>['用户','user'].includes(e.role));
   const needle=(paired.text.match(/[^\s]{6,20}/g)||[]).find(text=>!question.text.includes(text));assert.ok(needle,'fixture includes an assistant-only search term');
   run(`navigateToConversationIndex(${JSON.stringify(group.map(e=>e.id))},'filtered turn','exact')`);
   const input=$('reader-content').querySelector('input');input.value=needle;input.dispatchEvent({type:'input'});
   assert.equal($('conversation-list').querySelectorAll('.conversation-result').length,1);const result=$('conversation-list').querySelector('.conversation-result');
   assert.equal(result.querySelector('strong').textContent,run(`conversationTitleForEntry(${JSON.stringify(question)})`));result.click();
   assert.equal($('conversation-dialog').open,true,'filtered cards open in the reader dialog');assert.ok(!$('conversation-dialog-content').textContent.includes('点击上方卡片'),'assistant-only filtering still opens the selected turn');assert.equal(run('app.conversationQuery'),needle);
  }
  assert.equal(run("firstConversationSegment({role:'用户',text:'<memory>旧标题</memory>\\n## My request:\\n请调整管理员排行榜'})"),'请调整管理员排行榜','ambient context does not become the title');
  assert.equal(run("firstConversationSegment({role:'用户',text:'请读取 memory\\\\_bank 文档'})"),'请读取 memory_bank 文档','literal underscores survive title cleanup');
  run('navigateToConversationIndex([],"empty","none")');assert.equal(run('initialState().conversationScope.length'),0,'empty scope survives reload');assert.equal(run('initialState().view'),'conversations');
 }
 let nodes=0,resources=0;
 if(payload.conversations?.length){
  // Native close events are queued: a stale event must not dismiss a reader
  // reopened by Forward before that event is delivered.
  run('navigateToConversationIndex(null,"")');let modalCard=$('conversation-list').querySelector('.conversation-result');modalCard.click();
  const dialog=$('conversation-dialog'),originalClose=dialog.close,queuedClose=[];
  dialog.close=function(){this.open=false;this.removeAttribute('open');queuedClose.push(()=>this.dispatchEvent({type:'close',target:this}));};
  $('conversation-dialog-close').click();assert.equal(dialog.open,false);history.forward();const reopenedId=run('app.conversationId');assert.equal(dialog.open,true);
  for(const deliver of queuedClose)deliver();assert.equal(dialog.open,true,'a queued old close does not dismiss a reopened reader');assert.equal(run('app.conversationId'),reopenedId);
  dialog.close=originalClose;const indexBeforeEscape=run('app.conversationDialogReturnIndex');body.dispatchEvent({type:'keydown',key:'Escape',preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}});assert.equal(dialog.open,false,'Escape closes the reader');assert.equal(run('historyCursor'),indexBeforeEscape,'Escape returns once to the original index');
  modalCard=$('conversation-list').querySelector('.conversation-result');modalCard.click();let cancelPrevented=false;dialog.dispatchEvent({type:'cancel',preventDefault(){cancelPrevented=true;}});assert.equal(cancelPrevented,true);assert.equal(dialog.open,false,'native cancel returns to the index');
  const firstEntry=payload.conversations[0],scopedTitle=run(`conversationTitleForEntry(${JSON.stringify(firstEntry)})`);run(`navigateToConversationIndex([${JSON.stringify(firstEntry.id)}],${JSON.stringify('范围测试')})`);assert.equal(run('app.view'),'conversations');assert.ok($('conversation-list').querySelector('.conversation-result'),'scoped index renders a short turn card');assert.equal($('conversation-dialog').open,false,'conversation index does not auto-open the first body');const firstCard=$('conversation-list').querySelector('.conversation-result');assert.equal(firstCard.querySelector('strong').textContent,scopedTitle,'conversation card uses a friendly local title');firstCard.click();assert.equal(run('app.view'),'conversations','selecting a card stays in the same index route');assert.equal($('conversation-dialog').open,true,'selected conversation opens the reader dialog');assert.ok($('conversation-list').querySelector('.conversation-result'),'selected conversation keeps the card list');const bodyNeedle=run(`firstConversationSegment(${JSON.stringify(firstEntry)})`).slice(0,18);assert.ok(!$('conversation-dialog-content').textContent.includes('点击上方卡片')&&(!bodyNeedle||$('conversation-dialog-content').textContent.includes(bodyNeedle)),'selected conversation renders body in the reader dialog');assert.ok($('breadcrumbs').textContent.includes(scopedTitle),'conversation breadcrumb uses the friendly title');const conversationDialogContent=$('conversation-dialog-content');conversationDialogContent.scrollTop=137;conversationDialogContent.dispatchEvent({type:'scroll'});const conversationList=$('conversation-list');conversationList.scrollTop=23;window.dispatchEvent({type:'resize'});assert.equal($('conversation-dialog-content'),conversationDialogContent,'resize keeps conversation dialog DOM');assert.equal(conversationDialogContent.scrollTop,137,'resize preserves conversation reader scroll');assert.equal(conversationList.scrollTop,23,'resize preserves conversation card scroll');$('conversation-dialog-close').click();
  const unlinked=(payload.chapters.flatMap(ch=>ch.record.nodes.map(node=>({ch,node}))).find(({node})=>!((node.conversation_entry_ids||[]).length||(node.conversation_source_entry_ids||[]).length)));if(unlinked){run(`navigateToConversationIndex([],${JSON.stringify(unlinked.node.title||'无关联阶段')},'none')`);assert.ok(location.hash.includes('scope=')&&location.hash.includes('scopeMode=none'),'conversation scope survives in the deep link');assert.equal($('conversation-list').querySelectorAll('.conversation-result').length,0,'empty stage scope does not fall back to global conversations');assert.ok($('conversation-content').textContent.includes('没有已关联的保存摘录'),'empty stage scope is explicit');const allButton=$('conversation-content').querySelectorAll('button').find(node=>node.textContent==='查看全部已收录对话');assert.ok(allButton);allButton.click();assert.equal(run('app.conversationScope'),null,'empty scope can explicitly open all saved conversations');}
  const summaryEntry=payload.conversations.find(entry=>entry.role==='摘要');if(summaryEntry)assert.ok(run(`conversationTitleForEntry(${JSON.stringify(summaryEntry)})`).includes('保存摘要'),'saved summary cards remain marked as summaries');
  const continueEntry=payload.conversations.find(entry=>['用户','user'].includes(String(entry.role||'').toLocaleLowerCase())&&run(`firstConversationSegment(${JSON.stringify(entry)})`)==='继续');if(continueEntry){run(`navigateToConversationIndex([${JSON.stringify(continueEntry.id)}],${JSON.stringify('继续测试')})`);const continueCard=$('conversation-list').querySelector('.conversation-result');assert.equal(continueCard.querySelector('strong').textContent,'继续','short user prompt stays as the card title');assert.ok(continueCard.querySelector('.conversation-card-preview'),'short prompt gets a separate assistant preview line');}
  const assistantEntry=payload.conversations.find(entry=>['助手','assistant'].includes(String(entry.role||'').toLocaleLowerCase()));if(assistantEntry){const friendly=run(`conversationTitleForEntry(${JSON.stringify(assistantEntry)})`),needle=friendly.slice(0,12);$('search').value=needle;$('search').dispatchEvent({type:'input'});const searchConversation=[...$('results').querySelectorAll('.result')].find(node=>node.querySelector('.result-type')?.textContent==='对话摘录');assert.ok(searchConversation,'full-text search returns a conversation card');assert.equal(searchConversation.querySelector('strong').textContent,friendly,'conversation search result uses the complete turn friendly title');}
 }
 for(const item of payload.navigation.items.filter(item=>item.source_node||record.nodes.some(n=>n.id===item.id))){
  const row=$('overview-graph').querySelector(`[data-node-id="${item.source_node||item.id}"]`);assert.ok(row);row.click();assert.equal($('chapter-panel').hidden,false);
  assert.equal(run('app.chapter'),item.chapter);assert.equal(run('app.navItem'),item.id);assert.equal(run('app.view'),'chapter');assert.equal(run('app.node'),null);
  const target=item.node&&$('native-graph').querySelector(`[data-node-id="${item.node}"]`);assert.ok(target||$('native-graph').querySelector('.graph-node'));(target||$('native-graph').querySelector('.graph-node')).click();assert.equal(run('app.view'),'node');if(item.node)assert.equal(run('app.node'),item.node);
  assert.ok(location.hash.includes('nav='+item.id));
 }
 let disclosureHistoryChecked=false;
 for(const ch of payload.chapters){
  run(`navigateChapter(${JSON.stringify(ch.id)})`);
  assert.equal($('native-graph').querySelectorAll('.graph-node').length,ch.record.nodes.length);
  assert.equal($('native-graph').querySelectorAll('.graph-edge').length,ch.record.edges.length);
  for(const n of ch.record.nodes){
   $('native-graph').querySelector(`[data-node-id="${n.id}"]`).click();nodes++;
   assert.equal(run('app.node'),n.id);assert.equal($('reader-title').textContent,n.display_title||n.title);assert.ok(!$('reader-content').querySelectorAll('h3').some(h=>h.textContent==='连接关系'));
   const highlightedEdges=$('native-graph').querySelectorAll('.graph-edge').filter(edge=>edge.dataset.selected==='true');
   const ancestors=new Set([n.id]),pending=[n.id],expectedEdges=new Set();while(pending.length){const target=pending.pop();for(const [index,edge] of ch.layout.edges.entries()){if(edge.to!==target)continue;expectedEdges.add(index);if(!ancestors.has(edge.from)){ancestors.add(edge.from);pending.push(edge.from);}}}
   assert.deepEqual($('native-graph').querySelectorAll('.graph-edge').map((edge,index)=>edge.dataset.selected==='true'?index:null).filter(index=>index!==null),[...expectedEdges].sort((a,b)=>a-b),'highlight follows only recorded upstream edges');
   const graphNode=$('native-graph').querySelector(`[data-node-id="${n.id}"]`),icon=graphNode.querySelector('.graph-icon');assert.ok(icon,'node displays a line icon');
   assert.equal(icon.dataset.kind,['goal','decision','issue','experiment','milestone','module'].includes(n.kind)?n.kind:'unknown','icon follows the recorded kind');
   assert.equal(graphNode.dataset.status,['proposed','in_progress','completed','verified','failed','paused','superseded','unknown'].includes(String(n.status||'').trim().toLocaleLowerCase())?String(n.status).trim().toLocaleLowerCase():'unknown','status style follows the recorded status');
   const conversationButton=$('reader-content').querySelector('.stage-conversation-button');assert.ok(conversationButton&&!conversationButton.closest('details'),'conversation index remains directly accessible');
   const detailDisclosure=$('reader-content').querySelector('.reader-details');assert.ok(detailDisclosure);assert.ok(!detailDisclosure.open,'technical record is collapsed by default');const disclosureKeys=$('reader-content').querySelectorAll('details').map(item=>item.dataset.disclosureKey).filter(Boolean);assert.equal(new Set(disclosureKeys).size>=1,true,'reader disclosures carry stable keys');const statusBadge=$('reader-content').querySelector('.status');assert.ok(statusBadge?.getAttribute('aria-label')?.startsWith('阶段状态：'),'status keeps a text label for assistive technology');
   const visibleResources=$('reader-content').querySelectorAll('.compact-resource').filter(item=>!item.closest('details'));
   assert.equal(visibleResources.length,Math.min(3,(n.artifacts||[]).length),'default detail shows at most three files without losing the remaining links');
   for(const artifact of n.artifacts||[]){if(artifact.file_id&&payload.files[artifact.file_id]?.status==='embedded'){
    const href=run(`resourceURL(E.files[${JSON.stringify(artifact.file_id)}])`);
    assert.ok($('reader-content').querySelectorAll('a').some(a=>a.href===href),'resource is a real hyperlink');resources++;
    if(!disclosureHistoryChecked){const openedKeys=$('reader-content').querySelectorAll('details').filter(item=>item.dataset.disclosureKey).map(item=>{item.open=true;item.dispatchEvent({type:'toggle'});return item.dataset.disclosureKey;});$('reader-content').scrollTop=173;$('reader-content').dispatchEvent({type:'scroll'});$('reader-content').querySelectorAll('a').find(a=>a.href===href).click();assert.equal(run('app.fileId'),artifact.file_id,'node resource opens the saved file');history.back();assert.equal(run('app.view'),'node','history returns to the same node');assert.equal($('reader-content').querySelector('.reader-details').open,true,'history restores the node detail disclosure');assert.equal($('reader-content').scrollTop,173,'history restores the node detail scroll');for(const key of openedKeys)assert.equal($('reader-content').querySelectorAll('details').find(item=>item.dataset.disclosureKey===key)?.open,true,'nested disclosure restores its open state');const nested=$('reader-content').querySelectorAll('details').find(item=>item.dataset.disclosureKey&&item.dataset.disclosureKey!==openedKeys[0]);if(nested){const key=nested.dataset.disclosureKey;nested.open=false;nested.dispatchEvent({type:'toggle'});run(`openFile(${JSON.stringify(artifact.file_id)})`);history.back();assert.equal($('reader-content').querySelectorAll('details').find(item=>item.dataset.disclosureKey===key)?.open,false,'an explicitly collapsed nested disclosure also stays collapsed');}disclosureHistoryChecked=true;}
   }}
  }
 }
 const selectedChapter=payload.chapters.find(c=>(c.record.nodes||[]).some(n=>(n.artifacts||[]).length))||payload.chapters[0],selected=selectedChapter.record.nodes[0];
 run(`navigateNode(${JSON.stringify(selected.id)},${JSON.stringify(selectedChapter.id)})`);
 const keyboardNode=$('native-graph').querySelectorAll('.graph-node').at(-1);
 keyboardNode.dispatchEvent({type:'keydown',key:'Enter',preventDefault(){}});
 assert.equal(run('app.node'),keyboardNode.dataset.nodeId,'keyboard activation selects the graph node');
 run('zoomNativeGraph(.3)');const graphPosition=JSON.stringify(run('nativeGraphState'));
 for(const file of Object.values(payload.files)){
  run(`openFile(${JSON.stringify(file.id)})`);assert.equal(run('app.fileId'),file.id);
  assert.equal(JSON.stringify(run('nativeGraphState')),graphPosition,'opening files preserves graph viewport');
 }
 const readerBeforeDrag=$('reader-content').children[0],historyBeforeDrag=historyRows.length,routeBeforeDrag=run('app.fileId');$('reader-content').scrollTop=187;
 secondSplitter.dispatchEvent({type:'pointerdown',button:0,clientX:700,pointerId:2,preventDefault(){}});secondSplitter.dispatchEvent({type:'pointermove',clientX:668,pointerId:2});secondSplitter.dispatchEvent({type:'pointerup',pointerId:2});
 assert.equal($('reader-content').children[0],readerBeforeDrag,'dragging never rebuilds the file reader');assert.equal($('reader-content').scrollTop,187);assert.equal(run('app.fileId'),routeBeforeDrag);assert.equal(historyRows.length,historyBeforeDrag,'dragging does not add navigation history');
 const originalGet=localStorage.getItem,originalSet=localStorage.setItem;localStorage.getItem=()=>{throw new Error('storage blocked');};localStorage.setItem=()=>{throw new Error('storage blocked');};assert.doesNotThrow(()=>run('loadWorkbenchWidths();saveWorkbenchWidths()'));localStorage.getItem=originalGet;localStorage.setItem=originalSet;
 for(const entry of payload.conversations){run(`navigateToConversationEntry(${JSON.stringify(entry.id)})`);assert.equal(run('app.conversationId'),entry.id);}
 $('rail-overview').click();assert.equal(run('app.chapter'),payload.navigation.source_chapter||payload.chapters[0].id);
 assert.equal(run('app.view'),'overview');history.back();assert.notEqual(run('app.view'),'overview');history.forward();assert.equal(run('app.view'),'overview');run(`navigateNode(${JSON.stringify(selected.id)},${JSON.stringify(selectedChapter.id)})`);
 $('reader-content').scrollTop=214;const detailRoot=$('reader-content').children[0];window.dispatchEvent({type:'resize'});assert.equal($('reader-content').children[0],detailRoot,'resize keeps the detail DOM');assert.equal($('reader-content').scrollTop,214,'resize keeps detail scroll');
 let prevented=false;$('native-graph').querySelector('svg').dispatchEvent({type:'wheel',deltaY:80,preventDefault(){prevented=true;}});assert.equal(prevented,false,'ordinary wheel remains vertical scrolling');
 desktop=false;const mobileRoot=$('reader-content').children[0];window.dispatchEvent({type:'resize'});assert.equal($('reader-panel').hidden,false,'crossing to mobile preserves the active detail panel');assert.equal($('reader-content').children[0],mobileRoot,'breakpoint resize preserves reader DOM');$('mobile-overview').click();assert.equal($('overview-panel').hidden,false);assert.equal($('chapter-panel').hidden,true);assert.equal($('reader-panel').hidden,true);const mobileRow=$('overview-graph').querySelector('.graph-node');mobileRow.click();assert.equal($('workspace').classList.contains('mobile-flow'),true);assert.equal($('overview-panel').hidden,true);assert.equal($('chapter-panel').hidden,false);const mobileNode=$('native-graph').querySelector('.graph-node');mobileNode.click();assert.equal($('workspace').classList.contains('mobile-reader'),true);assert.equal($('reader-panel').hidden,false);$('mobile-map').click();assert.equal($('reader-panel').hidden,true);$('mobile-reader').click();assert.equal($('reader-panel').hidden,false);history.back();assert.notEqual(run('app.view'),'node');history.forward();assert.equal(run('app.view'),'node');desktop=true;window.dispatchEvent({type:'resize'});assert.equal($('reader-panel').hidden,false);
 desktop=false;run('viewOverview()');$('mobile-reader').click();assert.equal(run('app.mobileView'),'overview','initial mobile detail click retains the visible overview');assert.equal($('overview-panel').hidden,false);assert.equal($('mobile-overview').getAttribute('aria-selected'),'true');$('mobile-map').click();assert.equal($('overview-panel').hidden,false);desktop=true;window.dispatchEvent({type:'resize'});
 const allFiles=Object.values(payload.files).filter(f=>f.status==='embedded').length;
 assert.equal(run("INDEX.filter(r=>r.type==='文件').length"),allFiles);
 console.log(JSON.stringify({status:'passed',kind:'in-process DOM model, not browser or visual QA',nodes,resourceLinks:resources,files:allFiles,excerpts:payload.conversations.length,navigationEvents:payload.navigation.items.length,checks:['persistent desktop three-column empty states','overview to chapter flow to detail','splitter pointer and keyboard constraints','local width persistence','all SVG nodes and edges','artifact hyperlinks','file readers and resize retention','mobile view buttons','Back/Forward','full search index']}));
 process.exit(0);
}
const fileChapter=payload.chapters.find(item=>item.record.nodes.some(node=>(node.artifacts||[]).some(artifact=>artifact.file_id&&payload.files[artifact.file_id]?.status==='embedded')));
assert.ok(fileChapter,'fictional demo exposes a chapter with a packaged file');
run(`navigateChapter(${JSON.stringify(fileChapter.id)})`);assert.equal(run('app.view'),'chapter');const fileNode=fileChapter.record.nodes.find(node=>(node.artifacts||[]).some(artifact=>artifact.file_id&&payload.files[artifact.file_id]?.status==='embedded'));
const shape=$('native-graph').querySelector(`[data-node-id="${fileNode.id}"]`);assert.ok(shape);shape.click();
assert.equal(run('app.node'),fileNode.id);assert.equal(run('app.panelOpen'),true,'clicking a node opens its reading panel');
const fileId=fileNode.artifacts.find(item=>item.file_id).file_id;
const artifactLink=$('reader-content').querySelectorAll('a').find(anchor=>anchor.href.startsWith('blob:'));
assert.ok(artifactLink,'the node exposes a true packaged-resource link');
artifactLink.click();assert.equal(run('app.view'),'file');assert.equal(run('app.fileId'),fileId);
const firstFile=$('reader-content').querySelector('#file-render');
assert.ok(firstFile,'artifact opens as a full reader document');
const firstFileObj=payload.files[fileId];
const secondFile=Object.values(payload.files).find(file=>file.name==='review-checklist.md');
assert.ok(firstFileObj.name==='reading-plan.md'&&secondFile,'demo has two mutually linked Markdown files');
const linked=firstFile.querySelectorAll('a').find(anchor=>anchor.href===run(`resourceURL(E.files[${JSON.stringify(secondFile.id)}])`));
assert.ok(linked,'Markdown relative link resolves to the packaged sibling document');
$('reader-content').scrollTop=218;$('reader-content').dispatchEvent({type:'scroll'});linked.click();
assert.equal(run('app.fileId'),secondFile.id);assert.equal($('reader-content').scrollTop,0,'new file route starts at its first line');
$('reader-content').scrollTop=376;$('reader-content').dispatchEvent({type:'scroll'});history.back();
assert.equal(run('app.fileId'),fileId);assert.equal($('reader-content').scrollTop,218,'Back restores the first file position');
history.forward();assert.equal(run('app.fileId'),secondFile.id);assert.equal($('reader-content').scrollTop,376,'Forward restores the second file position');

const search=$('search'),results=$('results');search.value=payload.locale==='en'?'reading':'阅读';search.dispatchEvent({type:'input'});
const kinds=results.querySelectorAll('.search-group-heading').map(node=>node.textContent.split(' · ')[0]);
assert.deepEqual(kinds,['阶段','文件','对话摘录'],'the global search indexes each content kind');
console.log(JSON.stringify({status:'passed',kind:'portable fake-DOM runtime check; not real-browser evidence',checks:['overview-first drill-down','node click opens reader','embedded file link opens in reader','two relative Markdown files navigate A/B with Back/Forward scroll','global search groups stages, files, and saved excerpts']}));

search.value=payload.locale==='en'?'blue whale bookmark':'蓝鲸书签';search.dispatchEvent({type:'input'});
assert.deepEqual(results.querySelectorAll('.search-group-heading').map(n=>n.textContent.split(' · ')[0]),['文件'],'Pro indexes the fourth attachment body');
const bodyHit=results.querySelector('.result');assert.ok(bodyHit);bodyHit.click();
assert.equal(run('app.view'),'file');
assert.equal(payload.files[run('app.fileId')].name,'source-brief.md');
console.log(JSON.stringify({status:'passed',check:'Pro body-only search opens the fourth embedded resource'}));

// Locale changes preserve source data, navigation, scroll and dialog state.
const originalData=run('JSON.stringify(E)'),originalFile=run('app.fileId'),originalText=$('file-render').textContent;
$('reader-content').scrollTop=223;
run("window.ChatArchifyI18n.setLanguage('en')");
assert.equal(doc.documentElement.getAttribute('lang'),'en');
assert.equal($('continuation-open').textContent,'Export handoff');
assert.equal($('search').getAttribute('placeholder'),'Search stages, files, or excerpts');
assert.equal(run('app.fileId'),originalFile);assert.equal($('reader-content').scrollTop,223);
assert.equal($('file-render').textContent,originalText,'source file text is not translated');
assert.ok($('reader-actions').textContent.includes('Download file'));
assert.equal(run('STATUS.verified'),'Verified');assert.ok(location.hash.includes('lang=en'));history.back();assert.ok(location.hash.includes('lang=en'),'history keeps the selected interface language in copied links');history.forward();assert.equal(run('app.fileId'),originalFile);
search.value=payload.locale==='en'?'reading':'阅读';search.dispatchEvent({type:'input'});
assert.deepEqual(results.querySelectorAll('.search-group-heading').map(n=>n.textContent.split(' · ')[0]),['Stage','File','Conversation excerpts']);
run(`navigateNode(${JSON.stringify(fileNode.id)},${JSON.stringify(fileChapter.id)})`);
let detail=$('reader-content').querySelector('.technical-details');detail.open=true;detail.dispatchEvent({type:'toggle'});
$('reader-content').scrollTop=137;
run("window.ChatArchifyI18n.setLanguage('zh-CN')");
assert.equal($('reader-content').querySelector('.technical-details').open,true);assert.equal($('reader-content').scrollTop,137);
const localeEntry=payload.conversations.find(e=>['assistant','助手'].includes(e.role));
run(`navigateToConversationIndex(null);navigateToConversationEntry(${JSON.stringify(localeEntry.id)})`);
$('conversation-dialog-content').scrollTop=91;
const conversationBefore=$('conversation-dialog-content').querySelectorAll('.conversation-message-body').map(n=>n.textContent);
run("window.ChatArchifyI18n.setLanguage('en')");
assert.equal($('conversation-dialog').open,true);assert.equal($('conversation-dialog-content').scrollTop,91);
assert.deepEqual($('conversation-dialog-content').querySelectorAll('.conversation-message-body').map(n=>n.textContent),conversationBefore);
assert.ok($('conversation-dialog-content').querySelector('.conversation-message-head').textContent.includes('Assistant'));
$('conversation-dialog-close').click();$('continuation-open').click();
const goalInput=$('continuation-root').querySelector('input');goalInput.value='Keep my goal';goalInput.dispatchEvent({type:'input'});
run("window.ChatArchifyI18n.setLanguage('zh-CN');window.ChatArchifyI18n.setLanguage('en')");
assert.equal($('continuation-dialog').open,true);assert.equal($('continuation-root').querySelector('input').value,'Keep my goal');
assert.ok($('continuation-root').textContent.includes('# Continuation pack'));
$('continuation-close').click();$('update-review-open').click();
assert.ok($('update-review-root').textContent.includes('Choose a previous version'));
run("window.ChatArchifyI18n.setLanguage('zh-CN');window.ChatArchifyI18n.setLanguage('en')");
assert.equal($('update-review-dialog').open,true);assert.ok($('update-review-root').textContent.includes('Approve entire update'));
$('update-review-close').click();assert.equal(run('JSON.stringify(E)'),originalData,'locale switching must not mutate records, messages or embedded file bytes');
assert.equal(run("window.ChatArchifyI18n.setLanguage('fr')"),false);
console.log(JSON.stringify({status:'passed',check:'Bilingual runtime',kind:'in-process DOM; not browser QA',checks:['default locale','static labels and accessibility','English search after switching','file bytes and reading position','expanded details','conversation roles and original messages','continuation goal','review controls','invalid locale rejection']}));
if(payload.locale==='en'){
 const noChinese=(id)=>assert.ok(!/[\u3400-\u9fff]/.test($(id).textContent),`${id} contains untranslated text: ${$(id).textContent.match(/.{0,25}[\u3400-\u9fff].{0,25}/)?.[0]}`);
 for(const chapter of payload.chapters)for(const node of chapter.record.nodes){run(`navigateNode(${JSON.stringify(node.id)},${JSON.stringify(chapter.id)})`);for(const id of ['reader-content','overview-graph','native-graph','rail-note'])noChinese(id);}
 for(const file of Object.values(payload.files)){run(`openFile(${JSON.stringify(file.id)})`);noChinese('reader-content');}
 run('navigateToConversationIndex(null)');noChinese('reader-content');
 for(const entry of payload.conversations){run(`navigateToConversationEntry(${JSON.stringify(entry.id)})`);noChinese('conversation-dialog-content');$('conversation-dialog-close').click();}
 console.log(JSON.stringify({status:'passed',check:'English demo rendered content',kind:'in-process DOM; not browser QA'}));
}
