'use strict';
const E=JSON.parse(document.getElementById('explorer-data').textContent);
const $=id=>document.getElementById(id);
const STATUS={proposed:'提议',in_progress:'进行中',completed:'已完成',verified:'已验证',failed:'该尝试失败',paused:'暂停／延期',superseded:'被替代',unknown:'待确认'};
const KIND={goal:'目标',milestone:'里程碑',module:'模块',experiment:'尝试',decision:'决策',issue:'问题'};
const REL={continues:'延续',branches:'分叉',adds:'增加',pivots:'转向',merges:'汇合',depends_on:'依赖',chronological:'仅先后'};
const C=new Map(E.chapters.map(c=>[c.id,c]));
const resourceURLs=new Map();
let chapter=null,selected=null,currentFile=null,observer=null,generation=0;
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function button(text,fn,cls='button'){const b=el('button',text,cls);b.type='button';b.addEventListener('click',fn);return b;}
function paragraph(parent,text,cls){parent.append(el('p',text,cls));}
function section(parent,title){const s=el('section',undefined,'section');s.append(el('h3',title));parent.append(s);return s;}
function bytes64(data){return Uint8Array.from(atob(data),c=>c.charCodeAt(0));}
function downloadBytes(bytes,name,mime){const blob=new Blob([bytes],{type:mime||'application/octet-stream'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function downloadFile(file){if(file?.status==='embedded')downloadBytes(bytes64(file.data),file.name,file.mime);}
async function copy(value,b){try{await navigator.clipboard.writeText(value);b.textContent='已复制';}catch{let input=b.parentElement.querySelector('.copy-fallback');if(!input){input=el('textarea',undefined,'copy-fallback');input.readOnly=true;b.parentElement.append(input);}input.value=value;input.focus();input.select();b.textContent='请复制下方路径';}}
function showFile(id){const f=E.files[id];if(!f)return;currentFile=f;$('file-title').textContent=f.name;$('file-meta').textContent=f.status==='embedded'?`${Math.ceil(f.bytes/1024)} KB · 本次整理时保存的快照`:'未嵌入内容';$('file-path').textContent=f.path;$('copy-path').textContent='复制原始路径';document.querySelectorAll('.copy-fallback').forEach(n=>n.remove());$('file-download').disabled=f.status!=='embedded';$('file-note').textContent=f.note||(f.is_directory?'这里只展示目录索引；目录内文件没有打包。':'预览与下载使用页面内的文件快照，无需打开本机路径。');$('file-preview').replaceChildren();if(f.status==='embedded'){if(/^image\/(png|jpeg|gif|webp|avif|bmp)$/.test(f.mime)){const img=el('img');img.alt=f.name;img.src=`data:${f.mime};base64,${f.data}`;$('file-preview').append(img);}else if(typeof f.text==='string'){$('file-preview').append(el('pre',f.text));}else{paragraph($('file-preview'),'此格式可下载后用对应应用打开。');}}else{paragraph($('file-preview'),f.note||'原始文件不存在，未生成快照。');}if(!$('file-dialog').open)$('file-dialog').showModal();}
// Opening code/HTML/SVG attachments must display text rather than execute it.
function resourceURL(f){
 if(!resourceURLs.has(f.id)){
  const type=typeof f.text==='string'?'text/plain;charset=utf-8':(/^image\/(png|jpeg|gif|webp|avif|bmp)$/.test(f.mime)?f.mime:'application/octet-stream');
  resourceURLs.set(f.id,URL.createObjectURL(new Blob([bytes64(f.data)],{type})));
 }
 return resourceURLs.get(f.id);
}
function describeItem(parent,item){
 const box=el('div',undefined,'item'),title=item.label||item.title||item.uri,actions=el('div',undefined,'actions');
 if(item.chapter_id){
  const a=el('a',title,'resource-link');a.href='#chapter='+encodeURIComponent(item.chapter_id);a.addEventListener('click',event=>{event.preventDefault();openChapter(item.chapter_id);});box.append(a);paragraph(box,'相关的讨论路线','note');
 }else if(item.file_id){
  const f=E.files[item.file_id];
  if(f?.status==='embedded'){
   const a=el('a',title===f.name?title:title+' · '+f.name,'resource-link');a.href=resourceURL(f);a.target='_blank';a.rel='noopener noreferrer';box.append(a);
   paragraph(box,f.name+(f.is_directory?' · 目录索引':' · 文件快照'),'note');
   actions.append(button('页内预览',()=>showFile(f.id)),button('下载文件',()=>downloadFile(f)),button('复制原始路径',event=>copy(f.path,event.currentTarget)));
  }else{box.append(el('strong',title));paragraph(box,f?.note||'文件未找到，保留原始位置。','note');actions.append(button('查看原始位置',()=>showFile(item.file_id)));}
 }else if(/^https?:\/\//i.test(item.uri||'')){
  const a=el('a',title,'resource-link');a.href=item.uri;a.target='_blank';a.rel='noopener noreferrer';box.append(a);paragraph(box,item.uri,'note');
 }else{box.append(el('strong',title));if(item.uri)actions.append(button('复制链接',event=>copy(item.uri,event.currentTarget)));}
 if(item.version)paragraph(box,item.version,'note');if(actions.children.length)box.append(actions);parent.append(box);return box;
}
function focusNode(id){
 try{
  const frame=$('viewer'),node=frame.contentDocument?.querySelector(`[data-node-id="${id}"]`);
  if(!node)return;const focus=frame.contentWindow?.Archify?.focus;
  if(focus?.set)focus.set(id,{toggle:false,hideChip:true,updateUrl:false});
  else frame.contentDocument.querySelectorAll('[data-node-id]').forEach(n=>n.setAttribute('aria-pressed',String(n===node)));
 }catch{}
}
function showDetails(){if(selected&&!$('node-dialog').open)$('node-dialog').showModal();}
function findNode(id){return chapter.record.nodes.find(n=>n.id===id);}
function choose(id,focusGraph=false,show=false){const n=findNode(id);if(!n)return;selected=id;$('node-picker').value=id;$('node-title').textContent=n.title;const root=$('detail');root.replaceChildren();const head=el('div',undefined,'detail-header');head.append(el('div',`${KIND[n.kind]} · ${n.branch} · ${n.date||'日期未注明'}`,'meta'),el('h2',n.title),el('span',STATUS[n.status],'status'));root.append(head);const artifacts=section(root,`相关资源 · ${n.artifacts.length}`);paragraph(artifacts,'点击带下划线的名称打开资源；也可以在本页预览或下载。','note');if(!n.artifacts.length)paragraph(artifacts,'没有记录相关产物。','note');n.artifacts.forEach(a=>describeItem(artifacts,a));paragraph(section(root,'发生了什么'),n.summary);if(n.reason)paragraph(section(root,'为什么这样走'),n.reason);const sources=new Map(chapter.record.sources.map(s=>[s.id,s]));const evidence=section(root,`依据 · ${n.evidence.length}`);for(const r of n.evidence){const s=sources.get(r.source),box=describeItem(evidence,s);paragraph(box,r.locator,'note');if(r.note)paragraph(box,r.note,'note');}
 const relations=chapter.record.edges.filter(e=>e.from===id||e.to===id);if(relations.length){const sec=section(root,'连接关系');for(const e of relations){const incoming=e.to===id,other=findNode(incoming?e.from:e.to),box=el('div',undefined,'item');paragraph(box,(incoming?'来自':'通向')+' · '+REL[e.type]+(e.confidence==='inferred'?'（推测）':''),'note');box.append(button(other.title,()=>choose(other.id,true,true),'link-button'));paragraph(box,e.reason,'note');sec.append(box);}}
 try{history.replaceState(null,'',`#chapter=${encodeURIComponent(chapter.id)}&node=${encodeURIComponent(id)}`);}catch{}
 $('announce').textContent='已选择：'+n.title;
 if(focusGraph)focusNode(id);if(show){showDetails();$('node-dialog').scrollTop=0;}
}
function coverage(){const root=$('coverage-body');root.replaceChildren();for(const text of chapter.record.coverage)paragraph(root,text);for(const text of chapter.record.open_questions)paragraph(root,'待确认：'+text);paragraph(root,'文件链接打开本页保存的快照；原始路径可复制。验证范围见随附记录，当前环境未完成真实浏览器交互检查。');}
function wireFrame(token){
 if(token!==generation)return;
 try{
  const doc=$('viewer').contentDocument;if(!doc?.querySelector('[data-node-id]'))throw new Error('viewer unavailable');$('viewer-note').hidden=true;
  const activate=event=>{
   if(token!==generation)return;
   if(event.type==='keydown'&&!['Enter',' '].includes(event.key))return;
   if(event.type==='click'&&event.button!==undefined&&event.button!==0)return;
   const node=event.target.closest?.('[data-node-id]');if(!node||!findNode(node.dataset.nodeId))return;
   if(doc.querySelector('[data-just-panned="true"]'))return;
   event.preventDefault();event.stopImmediatePropagation();choose(node.dataset.nodeId,true,true);
  };
  // Run before the native toggle/popover, so repeated clicks reopen resources.
  doc.addEventListener('click',activate,true);doc.addEventListener('keydown',activate,true);
  if(observer)observer.disconnect();observer=new MutationObserver(records=>{
   if(token!==generation||!records.some(r=>r.target.matches?.('[data-node-id]')))return;
   const active=doc.querySelector('[data-node-id][aria-pressed="true"]');
   if(active&&active.dataset.nodeId!==selected&&findNode(active.dataset.nodeId))choose(active.dataset.nodeId);
  });observer.observe(doc.documentElement,{subtree:true,attributes:true,attributeFilter:['aria-pressed']});if(selected)focusNode(selected);
 }catch{$('viewer-note').hidden=false;}
}
function openChapter(id,nodeId,show=false){const next=C.get(id);if(!next)return;if($('node-dialog').open)$('node-dialog').close();chapter=next;selected=null;const token=++generation;if(observer){observer.disconnect();observer=null;}document.querySelectorAll('[data-chapter]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.chapter===id)));$('node-picker').replaceChildren();const placeholder=el('option','选择一个阶段');placeholder.value='';placeholder.disabled=true;$('node-picker').append(placeholder);for(const n of chapter.record.nodes){const option=el('option',n.title);option.value=n.id;$('node-picker').append(option);}$('graph-count').textContent=`${chapter.record.nodes.length} 个阶段 · ${chapter.record.edges.length} 条关系`;$('viewer').onload=()=>wireFrame(token);$('viewer').srcdoc=new TextDecoder().decode(bytes64(chapter.viewer));coverage();choose(findNode(nodeId)?nodeId:chapter.record.nodes[0].id,false,show);$('results').hidden=true;}
function search(){const q=$('search').value.trim().toLocaleLowerCase(),root=$('results');root.replaceChildren();root.hidden=!q;if(!q)return;let count=0;for(const ch of E.chapters){for(const n of ch.record.nodes){if(!n.search_text.includes(q))continue;const b=button('',()=>{openChapter(ch.id,n.id,true);$('search').value='';},'result');b.append(el('strong',n.title),el('small',ch.label+' · '+n.date));root.append(b);count++;}}if(!count)root.append(el('div','没有匹配的阶段或产物。','notice'));}
for(const ch of E.chapters){const b=button(ch.label,()=>openChapter(ch.id),'tab');b.dataset.chapter=ch.id;b.id='tab-'+ch.id;b.setAttribute('role','tab');b.setAttribute('aria-selected','false');b.setAttribute('aria-controls','viewer');$('chapters').append(b);}
$('chapters').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const all=[...$('chapters').querySelectorAll('button')],i=all.indexOf(event.target);if(i<0)return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?all.length-1:(i+(event.key==='ArrowRight'?1:-1)+all.length)%all.length;all[next].focus();all[next].click();});
$('node-picker').addEventListener('change',()=>choose($('node-picker').value,true,true));$('search').addEventListener('input',search);$('search').addEventListener('keydown',event=>{if(event.key==='Escape')$('results').hidden=true;});document.addEventListener('click',event=>{if(!event.target.closest('.search'))$('results').hidden=true;});
$('wide').addEventListener('click',showDetails);$('node-close').addEventListener('click',()=>$('node-dialog').close());$('about').addEventListener('click',()=>{$('coverage').open=true;$('coverage').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});});
$('file-close').addEventListener('click',()=>$('file-dialog').close());$('file-download').addEventListener('click',()=>downloadFile(currentFile));$('copy-path').addEventListener('click',event=>{if(currentFile)copy(currentFile.path,event.currentTarget);});$('file-dialog').addEventListener('click',event=>{if(event.target===$('file-dialog')){const r=$('file-dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('file-dialog').close();}});
$('native-download').addEventListener('click',()=>downloadBytes(bytes64(chapter.viewer),'project-'+chapter.id+'-diagram.html','text/html'));
const initial=new URLSearchParams(location.hash.slice(1));openChapter(C.has(initial.get('chapter'))?initial.get('chapter'):E.chapters[0].id,initial.get('node'),Boolean(initial.get('node')));
