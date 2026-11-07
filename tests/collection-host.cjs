'use strict';
const assert=require('node:assert/strict'),collector=require('../scripts/collect_conversations.cjs'),journal=require('../scripts/collection_checkpoint.cjs'),bridge=require('../scripts/collect_codex_host.cjs');
(async()=>{
 const state=collector.createState({projectIds:['p']}),saved=[];
 const result=await bridge.runBatch({collector,journal,state,
  listThreads:async args=>({content:[{type:'text',text:JSON.stringify({threads:args.archived?[]:[{id:'t',projectId:'p'}],nextCursor:null})}]}),
  readThread:async()=>({content:[{type:'text',text:JSON.stringify({thread:{id:'t'},page:{order:'newest_first',nextCursor:null,hasMore:false},turns:[]})}]}),
  writeCheckpoint:async(name,text)=>saved.push(JSON.parse(text))});
 assert.equal(result.audit.status,'complete');assert.deepEqual(journal.restore(saved),result.state);
 assert.throws(()=>bridge.unpack({isError:true,content:[]}));
 await assert.rejects(()=>bridge.runBatch({collector,journal,state:collector.createState({projectIds:['p']}),listThreads:async()=>({threads:[],nextCursor:null}),readThread:async()=>{},writeCheckpoint:async()=>{throw new Error('disk full');}}),/disk full/);
 console.log(JSON.stringify({status:'passed',checks:['host tool response adapter','durable checkpoint bridge','write failure is not completion']}));
})().catch(error=>{console.error(error);process.exitCode=1;});
