// Locale policy and catalog checks; no real browser is used here.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),catalog=JSON.parse(fs.readFileSync(path.join(root,'assets/locales/en.json'),'utf8'));
const script=fs.readFileSync(path.join(root,'assets/i18n.js'),'utf8');
const slots=text=>[...text.matchAll(/\{\d+\}/g)].map(m=>m[0]).sort();
for(const [key,value] of Object.entries(catalog)){assert.ok(value.trim(),key);assert.ok(!/[\u3400-\u9fff]/.test(value),key);assert.deepEqual(slots(value),slots(key),`interpolation slots: ${key}`);}
function host({locale='zh-CN',stored=null,hash='',blocked=false}={}){
 const payload={locale,project_id:'fictional-demo'},doc={getElementById:id=>id==='explorer-data'?{textContent:JSON.stringify(payload)}:id==='locale-data'?{textContent:JSON.stringify(catalog)}:null,querySelectorAll:()=>[]};
 const memory=new Map(stored?[['chat-archify:language:/demo.html',stored]]:[]);
 const context=vm.createContext({document:doc,location:{hash,pathname:'/demo.html'},URLSearchParams,localStorage:{getItem:key=>{if(blocked)throw Error('blocked');return memory.get(key);},setItem:(key,value)=>{if(blocked)throw Error('blocked');memory.set(key,value);}}});
 vm.runInContext(script,context);return {api:context.ChatArchifyI18n,memory};
}
assert.equal(host({locale:'en'}).api.language,'en');
assert.equal(host({locale:'en',stored:'zh-CN'}).api.language,'zh-CN');
assert.equal(host({locale:'zh-CN',stored:'zh-CN',hash:'#node=question&lang=en'}).api.language,'en');
assert.equal(host({locale:'en',hash:'#lang=invalid'}).api.language,'en');
const {api,memory}=host({locale:'en'});let changes=0;api.onChange(()=>changes++);
assert.equal(api.t('当前阶段：{0} · {1}','<b>原文</b>','{0}'),'Current stage: <b>原文</b> · {0}','insertions are not recursively translated or interpolated');
assert.equal(api.setLanguage('zh-CN'),true);assert.equal(memory.get('chat-archify:language:/demo.html'),'zh-CN');assert.equal(api.t('文件'),'文件');
api.setLanguage('zh-CN');assert.equal(changes,1);assert.equal(api.setLanguage('xx'),false);assert.equal(changes,1);
const locked=host({locale:'en',blocked:true});assert.equal(locked.api.setLanguage('zh-CN'),true);assert.equal(locked.api.language,'zh-CN');
console.log(JSON.stringify({status:'passed',catalog_entries:Object.keys(catalog).length,checks:['complete interpolation slots','English catalog','packaged default','saved preference','explicit deep link','blocked storage','unchanged interpolation values']}));
