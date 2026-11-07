/* Portable Codex collector. Tool calls and persistence are supplied by the host. */
'use strict';

const RETRIES = [[10,16000],[3,16000],[1,16000],[1,4000],[1,1000]];
const PRIVATE_KEY = /-----BEGIN (?:(?:[A-Z0-9]+ )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----/i;
const PROVIDER_TOKEN = /\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{15,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{20,}|npm_[A-Za-z0-9]{20,}|(?:AKIA|ASIA)[0-9A-Z]{16})\b/;
const JWT = /\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b/;
const ASSIGNMENT = /["']?\b([a-z][a-z0-9_.-]*(?:api[_-]?key|access[_-]?key|secret|token|password|credential|private[_-]?key)|api[_-]?key|access[_-]?key|secret|token|password|credential)\b["']?\s*(?:=|:)\s*("[^"\r\n]*"|'[^'\r\n]*'|[^\s,;#}]+)/gi;
const DEVICE_CODE_ASSIGNMENT = /["']?\b(?:user[_-]code|device[_-]code)\b["']?\s*(?:=|:)\s*("[^"\r\n]*"|'[^'\r\n]*'|[^\s,;#}]+)/gi;
function placeholder(value){
 const s=String(value||'').trim().replace(/^["'` ]+|["'` ,;]+$/g,'').toLowerCase();
 return !s||/\$\{|\{\{|os\.getenv|os\.environ|process\.env|env\.get\(/.test(s)||/^(?:none|null|nil|undefined|false|true|api[_-]key|token|secret|password)$/.test(s)||/(?:example|examplekey)$/.test(s)||/^[<\[]|[>\]]$/.test(s)||/(?:^|[_\-.])(?:your|example|placeholder|changeme|change-me|replace|insert|dummy|sample|redacted|fake|todo|none|null|undefined)(?:$|[_\-.])/.test(s)||(/^(.)\1{3,}$/.test(s));
}
function codePlaceholder(value){const clean=String(value||'').trim().replace(/^["'` ]+|["'` ,;]+$/g,'');return placeholder(clean)&&!/^\d{3,}$/.test(clean);}
function hasCredential(text){
 if(typeof text!=='string')return false;
 if(PRIVATE_KEY.test(text))return true;
 if(/(?:设备(?:登录|授权|验证)?码|登录码|授权码|验证码|device\s+(?:login\s+|authorization\s+)?code|verification\s+code|one.time\s+code)\s*(?:是|为|is|[:：=])\s*[:：]?\s*[`"']*(?:[A-Z0-9]{4}-[A-Z0-9]{4}|[0-9]{6,10})(?![A-Z0-9-])/i.test(text))return true;
 for(const pattern of [PROVIDER_TOKEN,JWT])for(const match of text.matchAll(new RegExp(pattern.source,'g')))if(!placeholder(match[0]))return true;
 // Device authorization codes and OAuth tokens remain sensitive even when short.
 for(const match of text.matchAll(new RegExp(DEVICE_CODE_ASSIGNMENT.source,'gi'))){let value=match[1].replace(/^["']|["']$/g,'').trim();try{value=decodeURIComponent(value);}catch{}if(value.length>=3&&!codePlaceholder(value))return true;}
 for(const match of text.matchAll(/https?:\/\/[^\s"'<>]+/gi)){
  let url=match[0].replace(/&amp;/gi,'&');for(let i=0;i<2;i++){try{const decoded=decodeURIComponent(url);if(decoded===url)break;url=decoded;}catch{break;}}
  for(const parameter of url.matchAll(/[?&#]([^=&#?\s]+)=([^&#?\s]+)/g)){
   const name=parameter[1].toLowerCase(),value=parameter[2].replace(/\+/g,' ').trim();
   const authContext=/(?:oauth|authoriz(?:e|ation)|callback|device[\/_-](?:login|code))/i.test(url.slice(0,parameter.index));
   if((/^(?:user[_-]code|device[_-]code|access[_-]token|refresh[_-]token|id[_-]token|client[_-]secret)$/.test(name)||(name==='code'&&authContext))&&value&&!codePlaceholder(value))return true;
  }
 }
 // Encoded Docker auth is excluded conservatively without decoding or persisting it.
 try{const json=JSON.parse(text);if(json&&typeof json.auths==='object'&&json.auths){for(const value of Object.values(json.auths)){if(value&&typeof value.auth==='string'&&!placeholder(value.auth))return true;}}}catch{}
 const connection=/\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?):\/\/[^\s"'<>]+/gi;
 for(const m of text.matchAll(connection)){const auth=m[0].split('://')[1].split('@');if(auth.length>1){const colon=auth[0].indexOf(':');if(colon>=0){let pass=auth[0].slice(colon+1);try{pass=decodeURIComponent(pass);}catch{}if(pass&&!placeholder(pass))return true;}}}
 ASSIGNMENT.lastIndex=0;let match;
 while((match=ASSIGNMENT.exec(text))){const key=match[1].toLowerCase(), value=match[2].trim().replace(/^["'` ]+|["'` ,;]+$/g,'');if(placeholder(value)||value.length<16||/\s/.test(value))continue;const classes=[/[a-z]/,/[A-Z]/,/[0-9]/,/[^A-Za-z0-9]/].filter(p=>p.test(value)).length;if(classes>=2&&(value.length>=20||/(?:openai|aws|github|gitlab|slack|stripe|google|azure|anthropic|cohere|huggingface|npm|docker)/.test(key)))return true;}
 return false;
}
function safeMeta(v){return typeof v==='string'&&!hasCredential(v)?v:'';}
function normalizePath(v){let s=String(v||'').trim().replace(/\\/g,'/'),windows=/^[A-Za-z]:\//.test(s),unc=s.startsWith('//'),absolute=windows||s.startsWith('/');if(windows||unc)s=s.toLowerCase();const prefix=windows?s.slice(0,2):unc?'/':'';const parts=(windows?s.slice(2):s).split('/'),stack=[];for(const part of parts){if(!part||part==='.')continue;if(part==='..'){if(stack.length)stack.pop();else return '';}else stack.push(part);}return absolute?prefix+'/'+stack.join('/'):stack.join('/');}
function uniq(values){return [...new Set(values.filter(x=>typeof x==='string'&&x))].sort();}
function normalizeScope(config){
 if(!config||typeof config!=='object')throw new Error('A scoped configuration is required');
 if(config.threadIds!==undefined&&(!Array.isArray(config.threadIds)||config.threadIds.some(id=>!safeId(id))))throw new Error('Explicit thread IDs must be safe nonempty identifiers');
 if(config.projectIds!==undefined&&(!Array.isArray(config.projectIds)||config.projectIds.some(id=>!safeId(id))))throw new Error('Project IDs must be safe nonempty identifiers');
 const scope={projectIds:uniq(config.projectIds||[]),roots:uniq((config.roots||[]).map(normalizePath)),threadIds:uniq(config.threadIds||[]),hostId:config.hostId||'local',source:config.source||'codex'};
 if(!scope.projectIds.length&&!scope.roots.length&&!scope.threadIds.length)throw new Error('At least one project, root or explicit thread is required');
 if(scope.roots.some(p=>!(/^(?:[a-z]:\/|\/)/i.test(p))||p==='/'||/^[a-z]:\/?$/i.test(p)))throw new Error('Roots must be absolute non-root directories');
 return scope;
}
function emptyStream(){return {status:'pending',cursor:null,pages:[],issue:''};}
function newThread(id){return {id,title:'',cwd:'',projectId:'',updatedAt:null,hostId:'',status:'pending',cursor:null,pages:[],retry:0,messages:[],issues:[],warnings:[],excluded:[],origin:[]};}
function createState(config){
 const scope=normalizeScope(config),state={version:1,scope,scopeFingerprint:JSON.stringify(scope),discovery:{active:emptyStream(),archived:emptyStream()},threads:{},excludedDiscoveryIds:[],issues:[]};
 for(const id of scope.threadIds){state.threads[id]=newThread(id);state.threads[id].origin=['explicit'];}
 return state;
}
// Create a distinct run for a fresh inventory; never mutate or reuse old cursors.
function freshRun(state){validateScope(state);return createState(state.scope);}
function validateScope(state){if(!state||state.version!==1||JSON.stringify(state.scope)!==state.scopeFingerprint)throw new Error('Collector state scope was changed or is invalid');}
function inScope(scope,thread){
 if(scope.threadIds.includes(thread.id))return 'explicit';
 if(thread.projectId&&scope.projectIds.includes(thread.projectId))return 'project';
 const cwd=normalizePath(thread.cwd);if(cwd&&scope.roots.some(root=>cwd===root||cwd.startsWith(root+'/')))return 'root';
 return '';
}
function cursorValid(v){return v===null||(typeof v==='string'&&v.length>0);}
function receiptValid(pages,status,discovery){
 if(status!=='done'||!Array.isArray(pages)||!pages.length)return false;
 let expected=null;const seen=new Set();
 for(const page of pages){const ids=discovery?page?.ids:page?.turnIds;if(!page||page.requestedCursor!==expected||!cursorValid(page.nextCursor)||seen.has(String(expected))||!Array.isArray(ids)||page.count!==ids.length||ids.some(id=>!safeId(id)))return false;seen.add(String(expected));if(!discovery&&(typeof page.hasMore!=='boolean'||page.hasMore!==(page.nextCursor!==null)||!Array.isArray(page.publicItems)))return false;expected=page.nextCursor;}
 return expected===null;
}
function safeId(v){return typeof v==='string'&&v.length>0&&v.length<=256&&!['__proto__','constructor','prototype'].includes(v)&&!hasCredential(v)?v:'';}
function strippedAmbient(value){return value.replace(/<(?:in-app-browser-context|external_browser_tabs|external_codex_apps_open_page|external_codex_apps_selected_page_part_[^\s>]*)\b[^>]*>[\s\S]*?<\/(?:in-app-browser-context|external_browser_tabs|external_codex_apps_open_page|external_codex_apps_selected_page_part_[^\s>]*)\s*>/gi,'').replace(/<external_codex_apps_open_page\b[^>]*\/>/gi,'');}
function truncated(value,item,part,limit){return Boolean(item?.truncated===true||part?.truncated===true||item?.isTruncated===true||part?.isTruncated===true||value.length>=limit||/\[(?:\.\.\.|…)?\s*(?:output |text |content )?truncated(?:[^\]]*)\]/i.test(value)||/\[(?:内容)?已截断[^\]]*\]/.test(value));}
function mark(thread,code,turnId,messageId){const finding={code,turn_id:turnId||'',message_id:messageId||''};if(!thread.issues.some(x=>JSON.stringify(x)===JSON.stringify(finding)))thread.issues.push(finding);}
function warn(thread,code,turnId,messageId){const finding={code,turn_id:turnId||'',message_id:messageId||''};if(!thread.warnings.some(x=>JSON.stringify(x)===JSON.stringify(finding)))thread.warnings.push(finding);}
function addMessage(thread,turn,item,limit){
 const turnId=safeId(turn.id),sourceItemId=safeId(item.id),messageId=/^item-\d+$/i.test(sourceItemId)?'':sourceItemId,isUser=item.type==='userMessage',phase=isUser?'user':item.phase;
 if(!isUser&&!['commentary','final_answer'].includes(phase)){mark(thread,'unsupported_assistant_phase',turnId,messageId);return 'unsupported';}
 let pieces=[];if(isUser){if(!Array.isArray(item.content)){mark(thread,'unsupported_content',turnId,messageId);return 'unsupported';}for(const part of item.content){if(part&&part.type==='text'&&typeof part.text==='string')pieces.push(part.text);else mark(thread,'unsupported_attachment',turnId,messageId);}}else if(typeof item.text==='string')pieces=[item.text];else{mark(thread,'unsupported_content',turnId,messageId);return 'unsupported';}
 const raw=pieces.join('\n'),body=isUser?strippedAmbient(raw):raw;
 if(!body.trim()){if(isUser&&raw.trim()&&raw!==body)return 'ambient';mark(thread,'empty_message_content',turnId,messageId);return 'unsupported';}
 if(!turnId||!sourceItemId){mark(thread,'missing_original_identity',turnId,messageId);return 'invalid';}
 if(!messageId)warn(thread,'source_item_identity_only',turnId,sourceItemId);
 if(hasCredential(raw)) {if(thread.messages.some(m=>m.turn_id===turnId&&m.source_item_id===sourceItemId))mark(thread,'conflicting_message_identity',turnId,sourceItemId);const exclusion={turn_id:turnId,message_id:messageId,source_item_id:sourceItemId,reason:'credential_content'};if(!thread.excluded.some(x=>x.turn_id===turnId&&x.source_item_id===sourceItemId))thread.excluded.push(exclusion);return 'excluded';}
 const cut=truncated(raw,item,null,limit)||(isUser&&item.content.some(part=>part?.type==='text'&&truncated(part.text||'',item,part,limit)));
 if(cut)mark(thread,'truncated_message',turnId,messageId);
 let startedAt=turn.startedAt===null||turn.startedAt===undefined?'':turn.startedAt;
 if(!['string','number'].includes(typeof startedAt)||hasCredential(startedAt)){startedAt='';mark(thread,'invalid_turn_timestamp',turnId,messageId);}
 const message={task_id:thread.id,turn_id:turnId,message_id:messageId,source_item_id:sourceItemId,role:isUser?'user':'assistant',phase,content:body,started_at:startedAt,partial:cut};
 const prior=thread.messages.find(m=>m.turn_id===turnId&&m.source_item_id===sourceItemId);
 if(prior){if(JSON.stringify(prior)!==JSON.stringify(message)){mark(thread,'conflicting_message_identity',turnId,sourceItemId);if(message.content.length>prior.content.length)Object.assign(prior,message);}return 'message';}
 if(thread.excluded.some(x=>x.turn_id===turnId&&x.source_item_id===sourceItemId))mark(thread,'conflicting_message_identity',turnId,sourceItemId);
 thread.messages.push(message);return 'message';
}
function applyDiscovery(state,name,result){
 const stream=state.discovery[name],request=stream.cursor;
 if(!result||!Array.isArray(result.threads)||!Object.prototype.hasOwnProperty.call(result,'nextCursor')||!cursorValid(result.nextCursor)){stream.status='blocked';stream.issue='invalid_discovery_page';return;}
 const ids=[];
 for(const candidate of result.threads){if(!candidate||!safeId(candidate.id)){state.issues.push({code:'discovery_missing_id',stream:name});continue;}const id=candidate.id;ids.push(id);const why=inScope(state.scope,candidate);if(!why){if(!state.threads[id]&&!state.excludedDiscoveryIds.includes(id))state.excludedDiscoveryIds.push(id);continue;}state.excludedDiscoveryIds=state.excludedDiscoveryIds.filter(x=>x!==id);if(!state.threads[id])state.threads[id]=newThread(id);const thread=state.threads[id];if(!thread.origin.includes(why))thread.origin.push(why);thread.title=safeMeta(candidate.title)||thread.title;thread.cwd=safeMeta(candidate.cwd)||thread.cwd;thread.projectId=safeId(candidate.projectId)||thread.projectId;thread.hostId=safeMeta(candidate.hostId)||thread.hostId;if((typeof candidate.updatedAt==='number'&&Number.isFinite(candidate.updatedAt))||(typeof candidate.updatedAt==='string'&&!hasCredential(candidate.updatedAt)))thread.updatedAt=candidate.updatedAt;}
 const next=result.nextCursor,receipt={requestedCursor:request,nextCursor:next,ids,count:ids.length};stream.pages.push(receipt);
 if(next!==null&&(next===request||stream.pages.some(p=>p.requestedCursor===next))){stream.status='blocked';stream.issue='discovery_cursor_loop';return;}
 stream.cursor=next;stream.status=next===null?'done':'pending';
}
function applyRead(thread,result){
 const request=thread.cursor,p=result?.page;
 if(!result||!result.thread||safeId(result.thread.id)!==thread.id||!Array.isArray(result.turns)||!p||typeof p.hasMore!=='boolean'||!Object.prototype.hasOwnProperty.call(p,'nextCursor')||!cursorValid(p.nextCursor)||p.hasMore!==(p.nextCursor!==null)||p.order!=='newest_first'){
  thread.status='blocked';mark(thread,'invalid_thread_page');return;
 }
 const turns=[],publicItems=[],limit=RETRIES[thread.retry][1];thread.title=safeMeta(result.thread.title)||thread.title;thread.cwd=safeMeta(result.thread.cwd)||thread.cwd;
 // Provider pages and their turns are newest first; preserve page and within-turn order for later reversal.
 for(const turn of result.turns){if(!turn||!safeId(turn.id)||!Array.isArray(turn.items)){mark(thread,'invalid_turn');continue;}turns.push(turn.id);for(const item of turn.items){if(item&&(item.type==='userMessage'||item.type==='agentMessage'))publicItems.push({turn_id:turn.id,source_item_id:safeId(item.id),disposition:addMessage(thread,turn,item,limit)});}}
 const next=p.nextCursor;thread.pages.push({requestedCursor:request,nextCursor:next,hasMore:p.hasMore,turnIds:turns,count:turns.length,publicItems,turnLimit:RETRIES[thread.retry][0],maxChars:limit});thread.retry=0;
 if(next!==null&&(next===request||thread.pages.some(page=>page.requestedCursor===next))){thread.status='blocked';mark(thread,'thread_cursor_loop');return;}
 thread.cursor=next;thread.status=next===null?'done':'pending';
}
async function collect({state,listThreads,readThread,save,maxCalls=20,now}){
 validateScope(state);if(typeof listThreads!=='function'||typeof readThread!=='function'||typeof save!=='function')throw new Error('Collector requires listing, reading and durable save callbacks');
 if(!Number.isInteger(maxCalls)||maxCalls<1)throw new Error('maxCalls must be a positive integer');
 let calls=0;
 for(const name of ['active','archived']){const stream=state.discovery[name];while(stream.status==='pending'&&calls<maxCalls){calls++;const args={mode:'history',source:state.scope.source,hostId:state.scope.hostId,archived:name==='archived',limit:50};if(stream.cursor!==null)args.cursor=stream.cursor;try{applyDiscovery(state,name,await listThreads(args));}catch{stream.status='blocked';stream.issue='discovery_read_failed';}await save(state);}}
 // Do not start candidate reads until both discovery streams have ended or blocked.
 if(['active','archived'].some(name=>state.discovery[name].status==='pending'))return audit(state);
 for(const thread of Object.values(state.threads)){
  while(thread.status==='pending'&&calls<maxCalls){calls++;const [turnLimit,maxOutputCharsPerItem]=RETRIES[thread.retry],args={threadId:thread.id,hostId:thread.hostId||state.scope.hostId,turnLimit,includeOutputs:false,maxOutputCharsPerItem};if(thread.cursor!==null)args.cursor=thread.cursor;
   try{applyRead(thread,await readThread(args));}catch{thread.retry++;if(thread.retry>=RETRIES.length){thread.retry=RETRIES.length-1;thread.status='blocked';mark(thread,'thread_read_failed');}}
   await save(state);
  }
  if(calls>=maxCalls)break;
 }
 return audit(state);
}
function audit(state){
 validateScope(state);const gaps=[],warnings=[],discovery=state.discovery||{},streams=['active','archived'].map(name=>[name,discovery[name]]);
 for(const [name,stream] of streams){if(!stream||!Array.isArray(stream.pages)||!['pending','done','blocked'].includes(stream.status)){gaps.push({type:'discovery',stream:name,reason:'missing_or_invalid_stream'});continue;}if(stream.status==='blocked')gaps.push({type:'discovery',stream:name,reason:stream.issue||'blocked',cursor:stream.cursor});else if(stream.status==='done'&&!receiptValid(stream.pages,stream.status,true))gaps.push({type:'discovery',stream:name,reason:'invalid_page_chain'});}
 for(const item of state.issues||[])gaps.push({type:'discovery',reason:item.code,stream:item.stream||''});
 const listed=new Set(streams.flatMap(([,stream])=>Array.isArray(stream?.pages)?stream.pages.flatMap(page=>Array.isArray(page.ids)?page.ids:[]):[]));
 for(const id of listed)if(!state.threads[id]&&!state.excludedDiscoveryIds.includes(id))gaps.push({type:'discovery',reason:'unaccounted_candidate',thread_id:id});
 for(const id of state.excludedDiscoveryIds)if(!listed.has(id)||state.threads[id])gaps.push({type:'discovery',reason:'invalid_excluded_candidate',thread_id:id});
 for(const id of state.scope.threadIds)if(!state.threads[id])gaps.push({type:'discovery',reason:'missing_explicit_thread',thread_id:id});
 for(const thread of Object.values(state.threads))if((!listed.has(thread.id)&&!state.scope.threadIds.includes(thread.id))||!inScope(state.scope,thread))gaps.push({type:'discovery',reason:'unaccounted_included_thread',thread_id:thread.id});
 const discovery_complete=streams.every(([,stream])=>stream&&receiptValid(stream.pages,stream.status,true))&&!gaps.some(g=>g.type==='discovery');
 let messages=0,exclusions=0;
 for(const thread of Object.values(state.threads)){
  messages+=thread.messages.length;exclusions+=thread.excluded.length;
  if(thread.status==='blocked')gaps.push({type:'thread',thread_id:thread.id,reason:'unread_page',cursor:thread.cursor});
  else if(thread.status==='done'&&!receiptValid(thread.pages,thread.status,false))gaps.push({type:'thread',thread_id:thread.id,reason:'invalid_page_chain'});
  for(const item of thread.issues)gaps.push({type:'message',thread_id:thread.id,reason:item.code,turn_id:item.turn_id,message_id:item.message_id});
  for(const item of thread.warnings||[])warnings.push({type:'message',thread_id:thread.id,reason:item.code,turn_id:item.turn_id,message_id:item.message_id});
  for(const item of thread.excluded)gaps.push({type:'message',thread_id:thread.id,reason:item.reason,turn_id:item.turn_id,message_id:item.message_id});
  const seenTurns=new Set(thread.pages.flatMap(page=>Array.isArray(page.turnIds)?page.turnIds:[])),seenMessages=new Set(),seenExcluded=new Set(),expectedMessages=new Set(),expectedExcluded=new Set();
  for(const page of thread.pages)for(const item of (page.publicItems||[])){
   const key=item.turn_id+'\u0000'+item.source_item_id;
   if(!page.turnIds.includes(item.turn_id)||!['message','excluded','ambient','unsupported','invalid'].includes(item.disposition)||(item.disposition!=='invalid'&&!safeId(item.source_item_id)))gaps.push({type:'message',thread_id:thread.id,reason:'invalid_item_receipt'});
   if(item.disposition==='message')expectedMessages.add(key);else if(item.disposition==='excluded')expectedExcluded.add(key);else if(['unsupported','invalid'].includes(item.disposition))gaps.push({type:'message',thread_id:thread.id,reason:'unsupported_public_item',turn_id:item.turn_id||''});
  }
  for(const item of thread.messages){const key=item.turn_id+'\u0000'+item.source_item_id;if(item.task_id!==thread.id||!seenTurns.has(item.turn_id)||!safeId(item.source_item_id)||seenMessages.has(key)||!expectedMessages.has(key)||typeof item.content!=='string'||hasCredential(item.content))gaps.push({type:'message',thread_id:thread.id,reason:'unaccounted_message',turn_id:item.turn_id||'',message_id:item.message_id||''});seenMessages.add(key);}
  for(const item of thread.excluded)seenExcluded.add(item.turn_id+'\u0000'+item.source_item_id);
  for(const key of expectedMessages)if(!seenMessages.has(key))gaps.push({type:'message',thread_id:thread.id,reason:'missing_saved_message'});
  for(const key of expectedExcluded)if(!seenExcluded.has(key))gaps.push({type:'message',thread_id:thread.id,reason:'missing_excluded_record'});
  for(const key of seenExcluded)if(!expectedExcluded.has(key))gaps.push({type:'message',thread_id:thread.id,reason:'unaccounted_excluded_record'});
 }
 const threads=Object.values(state.threads),readable_threads_complete=threads.every(t=>receiptValid(t.pages,t.status,false)),full_text_complete=readable_threads_complete&&threads.every(t=>!t.issues.length&&!t.excluded.length)&&!gaps.some(g=>g.type==='message');
 const pending=streams.some(([,s])=>s?.status==='pending')||threads.some(t=>t.status==='pending');
 return {status:pending?'in_progress':discovery_complete&&full_text_complete?'complete':'partial',discovery_complete,readable_threads_complete,full_text_complete,counts:{threads:threads.length,read_complete:threads.filter(t=>receiptValid(t.pages,t.status,false)).length,messages,credential_exclusions:exclusions,unrelated_discovered:state.excludedDiscoveryIds.length},gaps,warnings};
}
function exportsForThreads(state){
 validateScope(state);const output={},result=audit(state);for(const thread of Object.values(state.threads)){
  const turnOrder=[];for(const page of [...thread.pages].reverse()){for(const id of [...page.turnIds].reverse()){if(!turnOrder.includes(id))turnOrder.push(id);}}
  const rank=new Map(turnOrder.map((id,index)=>[id,index]));const original=thread.messages.map((message,index)=>({message,index}));original.sort((a,b)=>(rank.get(a.message.turn_id)??Number.MAX_SAFE_INTEGER)-(rank.get(b.message.turn_id)??Number.MAX_SAFE_INTEGER)||a.index-b.index);
  const complete=receiptValid(thread.pages,thread.status,false)&&!result.gaps.some(g=>g.thread_id===thread.id);
  output[thread.id]={source:{provider:'Codex read_thread',thread_id:thread.id,title:thread.title,coverage:complete?'complete':'excerpt',read_status:thread.status,date_basis:'Turn start date in UTC; individual message timestamps were not provided'},messages:original.map((x,index)=>{const stamp=x.message.started_at,date=typeof stamp==='number'?new Date(stamp*1000):stamp?new Date(stamp):null;return {...x.message,collection_order:index,date:date&&!isNaN(date.getTime())?date.toISOString().slice(0,10):''};})};
 }return output;
}
// Clean old checkpoints without changing them or inserting fabricated messages.
function sanitizeState(state){
 validateScope(state);const copy=JSON.parse(JSON.stringify(state));
 for(const value of [...copy.scope.projectIds,...copy.scope.roots,...copy.scope.threadIds,copy.scope.hostId,copy.scope.source])if(hasCredential(value))throw new Error('Collector scope contains sensitive material and cannot be saved');
 for(const thread of Object.values(copy.threads)){
  for(const key of ['title','cwd','projectId','hostId'])if(typeof thread[key]==='string'&&hasCredential(thread[key]))thread[key]='';
  if(typeof thread.updatedAt==='string'&&hasCredential(thread.updatedAt))thread.updatedAt=null;
  const removed=new Set();thread.messages=thread.messages.filter(message=>{
   if(!hasCredential(message.content))return true;
   const key=message.turn_id+'\u0000'+message.source_item_id;removed.add(key);
   if(!thread.excluded.some(x=>x.turn_id===message.turn_id&&x.source_item_id===message.source_item_id))thread.excluded.push({turn_id:message.turn_id,message_id:message.message_id||'',source_item_id:message.source_item_id,reason:'credential_content'});
   return false;
  });
  for(const page of thread.pages)for(const item of page.publicItems||[])if(item.disposition==='message'&&removed.has(item.turn_id+'\u0000'+item.source_item_id))item.disposition='excluded';
 }
 return copy;
}
module.exports={createState,freshRun,collect,audit,exportsForThreads,sanitizeState};
