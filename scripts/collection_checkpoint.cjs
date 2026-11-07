/* Small append-only checkpoints for hosts that expose file tools, not Node fs. */
'use strict';
const unsafe=new Set(['__proto__','prototype','constructor']);
function same(a,b){return JSON.stringify(a)===JSON.stringify(b);}
function delta(previous,next){
 const changes=[];
 function visit(a,b,path){
  if(same(a,b))return;
  if(Array.isArray(a)&&Array.isArray(b)&&b.length>=a.length&&a.every((item,index)=>same(item,b[index]))){changes.push({op:'append',path,value:b.slice(a.length)});return;}
  if(a&&b&&typeof a==='object'&&typeof b==='object'&&!Array.isArray(a)&&!Array.isArray(b)&&Object.keys(a).every(key=>Object.hasOwn(b,key))){for(const key of Object.keys(b)){if(unsafe.has(key))throw new Error('Unsafe checkpoint key');visit(a[key],b[key],[...path,key]);}return;}
  changes.push({op:'set',path,value:b});
 }
 visit(previous,next,[]);return changes;
}
function replay(state,changes){
 let result=state;
 for(const change of changes){
  if(!Array.isArray(change.path)||!['set','append'].includes(change.op)||change.path.some(key=>typeof key!=='string'||unsafe.has(key)))throw new Error('Invalid checkpoint operation');
  const value=JSON.parse(JSON.stringify(change.value));
  if(!change.path.length){if(change.op!=='set')throw new Error('Invalid root operation');result=value;continue;}
  let current=result;for(const key of change.path.slice(0,-1)){if(!current||!Object.hasOwn(current,key))throw new Error('Checkpoint path is missing');current=current[key];}
  const key=change.path.at(-1);
  if(change.op==='append'){if(!Object.hasOwn(current,key)||!Array.isArray(current[key])||!Array.isArray(value))throw new Error('Checkpoint array is missing');current[key].push(...value);}else current[key]=value;
 }
 return result;
}
function restore(checkpoints){
 let state=null;
 for(let i=0;i<checkpoints.length;i++){const item=checkpoints[i];if(item.superseded)throw new Error('Checkpoint was superseded by a sanitized checkpoint');if(item.sequence!==i||item.previous!==i-1)throw new Error('Checkpoint sequence is incomplete');state=replay(state,item.changes);}
 return state;
}
module.exports={delta,replay,restore};
