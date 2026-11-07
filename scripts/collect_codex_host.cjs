/* Bridge the portable collector to approved host tools, never a private DB. */
'use strict';
function unpack(result){
 if(result?.isError)throw new Error('Provider returned an error');
 if(result&&Array.isArray(result.threads))return result;
 if(result?.thread&&result?.page)return result;
 for(const item of result?.content||[]){if(item.type==='text'){try{return JSON.parse(item.text);}catch{}}}
 throw new Error('Provider did not return a readable page');
}
async function runBatch({collector,journal,state,previous=null,sequence=0,listThreads,readThread,writeCheckpoint,maxCalls=20}){
 if(!Number.isInteger(sequence)||sequence<0||typeof writeCheckpoint!=='function')throw new Error('A durable checkpoint writer and sequence are required');
 let prior=previous,index=sequence;
 const result=await collector.collect({state,maxCalls,
  listThreads:async args=>unpack(await listThreads(args)),readThread:async args=>unpack(await readThread(args)),
  save:async next=>{
   const item={sequence:index,previous:index-1,changes:journal.delta(prior,next)};
   await writeCheckpoint('checkpoint-'+String(index).padStart(6,'0')+'.json',JSON.stringify(item)+'\n');
   prior=JSON.parse(JSON.stringify(next));index++;
  }});
 return {state,previous:prior,sequence:index,audit:result};
}
module.exports={runBatch,unpack};
