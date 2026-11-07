'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const filename=path.resolve(__dirname,'../scripts/collect_conversations.cjs');
const source=fs.readFileSync(filename,'utf8');
// Exercise exactly the loader available in the isolated host, without Node globals.
const core={exports:{}};new Function('module','exports',source)(core,core.exports);
const {createState,freshRun,collect,audit,exportsForThreads,sanitizeState}=core.exports;
const cfg={projectIds:['wanted'],roots:['D:\\code\\humanity'],threadIds:[],hostId:'local',source:'codex'};
const user=(id,text)=>({type:'userMessage',id,content:[{type:'text',text}]});
const assistant=(id,text)=>({type:'agentMessage',id,phase:'final_answer',text});
const turn=(id,items)=>({id,startedAt:'2026-08-24T01:02:03Z',items});
const readPage=(id,turns,next=null)=>({thread:{id,title:id},page:{order:'newest_first',nextCursor:next,hasMore:next!==null},turns});
async function finish(state,adapter,batch=2){let n=0;do{await collect({state,...adapter,save:async()=>{adapter.saves=(adapter.saves||0)+1;},maxCalls:batch});if(++n>100)throw new Error('Collector did not terminate');}while(audit(state).status==='in_progress');return audit(state);}

async function paginationAndResume(){
 const state=createState(cfg),listCalls=[],readCalls=[];
 const adapter={
  listThreads:async args=>{listCalls.push(args);if(args.archived)return {threads:[{id:'arch',projectId:'wanted'}],nextCursor:null};if(!args.cursor)return {threads:[{id:'first',projectId:'wanted',updatedAt:123},{id:'unrelated',cwd:'D:\\code\\humanity-other'},{id:'escape',cwd:'d:/code/humanity/../private'},{id:'root-child',cwd:'d:/code/humanity/sub'}],nextCursor:'older'};return {threads:[{id:'later',projectId:'wanted'}],nextCursor:null};},
  readThread:async args=>{readCalls.push(args);if(args.threadId==='first'&&!args.cursor)return readPage('first',[turn('later-turn',[user('msg_u2','Second question'),assistant('msg_a2','Second answer')])],'earlier');if(args.threadId==='first')return readPage('first',[turn('earlier-turn',[user('msg_u1','First question'),assistant('msg_a1','First answer')])]);return readPage(args.threadId,[turn('only-'+args.threadId,[user('msg_'+args.threadId,'Question')])]);}
 };
 let out=await collect({state,...adapter,save:async()=>{adapter.saves=(adapter.saves||0)+1;},maxCalls:1});
 assert.equal(out.status,'in_progress');assert.equal(state.discovery.active.cursor,'older');assert.equal(adapter.saves,1);
 const resumed=JSON.parse(JSON.stringify(state)),result=await finish(resumed,adapter,1);
 assert.equal(result.status,'complete');assert.equal(result.discovery_complete,true);assert.equal(result.readable_threads_complete,true);assert.equal(result.full_text_complete,true);assert.equal(result.counts.threads,4);assert.equal(result.counts.unrelated_discovered,2);
 assert.ok(!readCalls.some(c=>['unrelated','escape'].includes(c.threadId)));assert.ok(readCalls.every(c=>c.includeOutputs===false));assert.equal(resumed.threads.first.projectId,'wanted');assert.equal(resumed.threads.first.updatedAt,123);
 assert.deepEqual(exportsForThreads(resumed).first.messages.map(m=>m.content),['First question','First answer','Second question','Second answer']);
 assert.equal(exportsForThreads(resumed).first.messages[0].started_at,'2026-08-24T01:02:03Z');
 const calls=listCalls.length+readCalls.length;await finish(resumed,adapter);assert.equal(listCalls.length+readCalls.length,calls,'completed collection never rereads');
 const fresh=freshRun(resumed);assert.equal(audit(fresh).status,'in_progress');assert.equal(fresh.discovery.active.pages.length,0);assert.equal(audit(resumed).status,'complete');
 assert.throws(()=>createState({projectIds:[],roots:['D:/'],threadIds:[]}),/non-root/);assert.throws(()=>createState({projectIds:[],roots:['relative/folder'],threadIds:[]}),/absolute/);
 const tampered=JSON.parse(JSON.stringify(resumed));tampered.discovery.active.pages[1].requestedCursor='missing';assert.equal(audit(tampered).discovery_complete,false);assert.equal(audit(tampered).status,'partial');
 const missingStream=JSON.parse(JSON.stringify(resumed));delete missingStream.discovery.archived;assert.equal(audit(missingStream).status,'partial');
 const missingMessage=JSON.parse(JSON.stringify(resumed));missingMessage.threads.first.messages.shift();assert.ok(audit(missingMessage).gaps.some(g=>g.reason==='missing_saved_message'));assert.equal(audit(missingMessage).status,'partial');
 const missingCandidate=JSON.parse(JSON.stringify(resumed));delete missingCandidate.threads.later;assert.ok(audit(missingCandidate).gaps.some(g=>g.reason==='unaccounted_candidate'));
 const mutated=JSON.parse(JSON.stringify(resumed));mutated.scope.projectIds.push('different');assert.throws(()=>audit(mutated),/scope/);
}
async function retriesAndBlocked(){
 const state=createState(cfg),attempts=[],read=[];
 const adapter={listThreads:async args=>({threads:args.archived?[]:[{id:'broken',projectId:'wanted'},{id:'good',projectId:'wanted'}],nextCursor:null}),readThread:async args=>{read.push(args.threadId);if(args.threadId==='broken'){attempts.push([args.turnLimit,args.maxOutputCharsPerItem,args.cursor]);throw new Error('sensitive error detail not saved');}return readPage('good',[turn('g',[assistant('msg_g','ok')])]);}};
 const result=await finish(state,adapter,3);assert.equal(result.status,'partial');assert.equal(result.discovery_complete,true);assert.equal(result.readable_threads_complete,false);assert.ok(read.includes('good'));
 assert.deepEqual(attempts.map(a=>a.slice(0,2)),[[10,16000],[3,16000],[1,16000],[1,4000],[1,1000]]);assert.ok(!JSON.stringify(state).includes('sensitive error detail'));
 assert.ok(result.gaps.some(g=>g.reason==='unread_page'&&g.thread_id==='broken'));
}
async function safetyAndTextGaps(){
 const key='sk-proj-'+Array.from({length:28},(_,i)=>String.fromCharCode(65+i%26)).join('');
 const jwt='eyJ'+('a'.repeat(22))+'.'+('b'.repeat(17))+'.'+('c'.repeat(17));
 const url='postgres://user:secret%2Fpass123456@localhost/db';
 const privateKey='-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----';
 const docker=JSON.stringify({auths:{'registry.example':{auth:'ZXhhbXBsZTpwYXNzd29yZA=='}}});
 const assignment='OPENAI_API_KEY = "Abc1234567890ABCDEFGxyz"';
 const secrets=[key,jwt,url,privateKey,docker,assignment,'sk-your_'+('X'.repeat(24))+' '+key,
  '设备登录码是 `AB12-CD34`。','验证码为 872193。','Device authorization code is QW12-ER34'];
 const state=createState({threadIds:['target'],projectIds:[],roots:[]}),snapshots=[];
 const adapter={listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>readPage('target',[turn('t',[
  ...secrets.map((value,i)=>user('msg_secret_'+i,value)),user('item-5','Visible user request'),
  {type:'userMessage',id:'msg_img',content:[{type:'text',text:'With attachment'},{type:'image',url:'secret-url'}]},
  assistant('msg_cut','partial text [truncated]'),{type:'reasoning',id:'reasoning1',summary:['secret reasoning']},
  {type:'tool',id:'tool1',output:'secret tool output'},assistant('msg_ok','Visible response')])]),
  save:async data=>snapshots.push(JSON.stringify(data))};
 const result=await collect({state,...adapter,maxCalls:30});assert.equal(result.status,'partial');assert.equal(result.readable_threads_complete,true);assert.equal(result.full_text_complete,false);assert.equal(result.counts.credential_exclusions,secrets.length);
 for(const secret of secrets)assert.ok(snapshots.every(s=>!s.includes(secret)),'raw credential must not reach durable callback');
 assert.ok(!JSON.stringify(state).includes('secret reasoning'));assert.ok(!JSON.stringify(state).includes('secret tool output'));assert.ok(!JSON.stringify(state).includes('secret-url'));
 assert.ok(result.gaps.some(g=>g.reason==='unsupported_attachment'));assert.ok(result.gaps.some(g=>g.reason==='truncated_message'));assert.ok(result.warnings.some(g=>g.reason==='source_item_identity_only'));
 const local=exportsForThreads(state).target.messages.find(m=>m.source_item_id==='item-5');assert.equal(local.message_id,'');assert.equal(local.content,'Visible user request');
 assert.equal(exportsForThreads(state).target.messages.length,4);assert.ok(!exportsForThreads(state).target.messages.some(m=>m.content.includes('secret')));
}
async function conflictsAndLoops(){
 let state=createState({threadIds:['x'],projectIds:[],roots:[]});
 let adapter={listThreads:async args=>({threads:[],nextCursor:args.archived?null:'loop'}),readThread:async()=>readPage('x',[turn('t',[user('msg_one','one')])])};
 let result=await finish(state,adapter);assert.equal(result.status,'partial');assert.ok(result.gaps.some(g=>g.reason==='discovery_cursor_loop'));
 state=createState({threadIds:['x'],projectIds:[],roots:[]});let pages=0;
 adapter={listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>{pages++;return pages===1?readPage('x',[turn('t',[user('msg_same','short')])],'old'):readPage('x',[turn('t',[user('msg_same','a different longer version')])]);}};
 result=await finish(state,adapter);assert.equal(result.status,'partial');assert.ok(result.gaps.some(g=>g.reason==='conflicting_message_identity'));assert.equal(exportsForThreads(state).x.messages[0].content,'a different longer version');
 state=createState({threadIds:['x'],projectIds:[],roots:[]});adapter={listThreads:async()=>({threads:[]}),readThread:async()=>readPage('x',[])};result=await finish(state,adapter);assert.equal(result.status,'partial');assert.equal(result.discovery_complete,false);
 state=createState({threadIds:['x'],projectIds:[],roots:[]});adapter={listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>readPage('x',[turn('t',[user('item-1','  leading and trailing  ')])])};result=await finish(state,adapter);assert.equal(result.status,'complete');assert.equal(result.full_text_complete,true);assert.ok(result.warnings.some(w=>w.reason==='source_item_identity_only'));assert.equal(exportsForThreads(state).x.messages[0].content,'  leading and trailing  ');
}
async function deviceCodesAndLegacySanitization(){
 const sensitive=[
  'https://login.example.test/device?user_code=ZXQ3-P8W7',
  'https://login.example.test/device?device_code=21a9x',
  'https://login.example.test/oauth?access_token=abc7',
  'https://login.example.test/oauth?refresh_token=abc8',
  'https://login.example.test/oauth?id_token=abc9',
  'https://login.example.test/oauth?client_secret=abc1',
  'https://login.example.test/oauth/callback?code=RX8M7',
  'https://login.example.test/device?%75ser_code=ZXQ3-P8W7',
  'https://login.example.test/device?mode=on&amp;%75ser_code=ZXQ3-P8W7',
  'https://login.example.test/finish#access_token=abc7',
  'https://example.test/redirect?url=https%3A%2F%2Flogin.example.test%2Fdevice%3Fuser_code%3DZXQ3-P8W7',
  'user_code = 7K2',
  'device_code = 1111',
  'user_code = "ZXQ3-P8W7"',
  "device_code: '9PAF-4JHK'"
 ];
 const safe=['https://docs.example.test/?code=1234','user_code = "<YOUR_CODE>"','https://login.example.test/device?user_code=%3CYOUR_CODE%3E'];
 const state=createState({threadIds:['safe-id']}),snapshots=[];
 const adapter={listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>readPage('safe-id',[turn('t',[...sensitive.map((text,i)=>user('msg_secret_'+i,text)),...safe.map((text,i)=>user('msg_safe_'+i,text))])]),save:async x=>snapshots.push(JSON.stringify(x))};
 const result=await collect({state,...adapter,maxCalls:20});assert.equal(result.counts.credential_exclusions,sensitive.length);assert.equal(state.threads['safe-id'].messages.length,safe.length);
 for(const secret of sensitive)assert.ok(snapshots.every(snapshot=>!snapshot.includes(secret)),'new codes must be screened before save');
 for(const id of ['__proto__','constructor','prototype'])assert.throws(()=>createState({threadIds:[id]}),/safe/);
 const old=createState({threadIds:['legacy']});await finish(old,{listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>readPage('legacy',[turn('t',[user('msg_legacy','Initial benign content'),assistant('msg_ok','Keep response')])])});
 old.threads.legacy.messages[0].content=sensitive[0];old.threads.legacy.title=sensitive[1];const before=JSON.stringify(old),clean=sanitizeState(old);
 assert.equal(JSON.stringify(old),before,'sanitization must not mutate existing checkpoints');
 assert.ok(!JSON.stringify(clean).includes(sensitive[0]));assert.ok(!JSON.stringify(clean).includes(sensitive[1]));assert.equal(clean.threads.legacy.title,'');
 assert.equal(clean.threads.legacy.messages.length,1);assert.equal(clean.threads.legacy.excluded.length,1);assert.equal(clean.threads.legacy.pages[0].publicItems.find(x=>x.source_item_id==='msg_legacy').disposition,'excluded');
 assert.equal(audit(clean).status,'partial');assert.equal(audit(clean).readable_threads_complete,true);assert.ok(audit(clean).gaps.some(g=>g.reason==='credential_content'));assert.equal(exportsForThreads(clean).legacy.source.coverage,'excerpt');
}
(async()=>{await paginationAndResume();await retriesAndBlocked();await safetyAndTextGaps();await conflictsAndLoops();await deviceCodesAndLegacySanitization();console.log(JSON.stringify({status:'passed',checks:['pagination and restart','scope boundaries and archived history','bounded fallback and independent threads','credential and attachment gaps','synthetic IDs and truncated text','deduplication and conflicting messages','cursor chains and malformed pages','device and OAuth codes','legacy checkpoint sanitization','unsafe identifier rejection']}));})().catch(error=>{console.error(error);process.exitCode=1;});
