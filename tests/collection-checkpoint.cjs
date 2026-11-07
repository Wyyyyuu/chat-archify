'use strict';
const assert=require('node:assert/strict'),j=require('../scripts/collection_checkpoint.cjs');
const first={scope:{id:'a'},messages:[]},second={scope:{id:'a'},messages:[{text:'one'}]},third={scope:{id:'a'},messages:[{text:'one'},{text:'two'}],done:true};
const states=[first,second,third],checkpoints=states.map((state,i)=>({sequence:i,previous:i-1,changes:j.delta(i?states[i-1]:null,state)}));
assert.deepEqual(j.restore(JSON.parse(JSON.stringify(checkpoints))),third);
assert.throws(()=>j.restore([checkpoints[0],checkpoints[2]]));
assert.throws(()=>j.replay({},[{op:'set',path:['__proto__','polluted'],value:true}]));
assert.equal({}.polluted,undefined);
console.log(JSON.stringify({status:'passed',checks:['append-only replay','missing checkpoint rejected','unsafe property rejected']}));
