'use strict';
// Marked supplies tokens only. Markdown never enters an HTML execution sink.
function markdownText(value){return String(value||'').replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi,(all,key)=>{const named={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:'\u00a0'};if(key[0]!=='#')return named[key.toLowerCase()]||all;const number=key[1].toLowerCase()==='x'?parseInt(key.slice(2),16):parseInt(key.slice(1),10);return number>0&&number<=0x10ffff&&!(number>=0xd800&&number<=0xdfff)?String.fromCodePoint(number):all;});}
function markdownPath(value){const parts=[];for(const part of value.replace(/\\/g,'/').split('/')){if(part==='..')parts.pop();else if(part&&part!=='.')parts.push(part);}return parts.join('/').toLowerCase();}
function markdownFile(href,file){
 if(!file||/^[a-z][a-z\d+.-]*:/i.test(href)&&!/^([a-z]:[\\/]|file:\/\/\/)/i.test(href))return null;
 let target;try{target=decodeURIComponent(href.split('#')[0]).replace(/^file:\/\/\//i,'').replace(/:\d+(?::\d+)?$/,'');}catch{return null;}
 if(!target)return null;
 if(!/^[a-z]:[\\/]/i.test(target)&&!target.startsWith('/'))target=file.path.replace(/[\\/][^\\/]*$/,'')+'/'+target;
 const normalized=markdownPath(target);return Object.values(E.files).find(f=>markdownPath(f.path)===normalized)||null;
}
let markdownRenderSerial=0;
function renderMarkdown(text,container,file=null){
 const renderId=++markdownRenderSerial;
 const source=String(text),locationSource=source.replace(/\r\n?/g,'\n'),headings=[],anchors=[];let counter=0;
 const plain=(target,value)=>target.append(el('span',markdownText(value)));
 function inline(tokens,target){for(const token of tokens||[]){
  if(['strong','em','del','codespan'].includes(token.type)){const tag=token.type==='codespan'?'code':token.type,child=el(tag);if(token.tokens)inline(token.tokens,child);else child.textContent=markdownText(token.text);target.append(child);}
  else if(token.type==='br')target.append(el('br'));
  else if(token.type==='link'||token.type==='image'){
   const href=markdownText(token.href).trim(),local=markdownFile(href,file),label=markdownText(token.text||href);
   if(token.type==='image'&&local?.status==='embedded'&&/^image\/(png|jpeg|gif|webp|avif|bmp)$/.test(local.mime)){const img=el('img');img.src=`data:${local.mime};base64,${local.data}`;img.alt=label;img.loading='lazy';target.append(img);}
   else if(local?.status==='embedded'){const a=el('a');a.href=resourceURL(local);a.target='_blank';a.rel='noopener noreferrer';a.addEventListener('click',event=>{if(event.button===0&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){event.preventDefault();openFile(local.id,{from:app});}});inline(token.tokens||[{type:'text',text:label}],a);target.append(a);}
   else if(/^https?:\/\/[^\s]+$/i.test(href)){const a=el('a');a.href=href;a.target='_blank';a.rel='noopener noreferrer';if(token.type==='image')a.textContent='图片：'+label;else inline(token.tokens||[{type:'text',text:label}],a);target.append(a);}
   else if(href.startsWith('#')){const a=el('a',label);a.href=href;anchors.push({a,href});target.append(a);}
   else {const span=el('span',label);span.title='未打包的本地资源或不支持的链接';target.append(span);}
  }else if(token.type==='html'){plain(target,token.raw||token.text);}
  else if(token.tokens)inline(token.tokens,target);
  else plain(target,token.text||token.raw||'');
 }}
 function blocks(tokens,target,searchFrom=0){let cursor=searchFrom;for(const token of tokens){
  if(token.type==='space'||token.type==='def')continue;
  const raw=token.raw||token.text||'';const sourceOffset=raw?locationSource.indexOf(raw,cursor):-1;
  if(token.type==='heading'){const h=el('h'+Math.max(1,Math.min(6,token.depth)));h.id='md-'+renderId+'-heading-'+(++counter);inline(token.tokens,h);target.append(h);headings.push({element:h,label:markdownText(token.text),depth:token.depth});}
  else if(token.type==='paragraph'||token.type==='text'){const p=el('p');inline(token.tokens||[{type:'text',text:token.text}],p);target.append(p);}
  else if(token.type==='code'){const pre=el('pre'),code=el('code',token.text);pre.append(code);target.append(pre);}
  else if(token.type==='blockquote'){const quote=el('blockquote');blocks(token.tokens,quote,sourceOffset>=0?sourceOffset:source.length+1);target.append(quote);}
  else if(token.type==='list'){const list=el(token.ordered?'ol':'ul');if(token.ordered&&Number.isInteger(token.start))list.start=token.start;let itemCursor=sourceOffset>=0?sourceOffset:source.length+1;for(const item of token.items){const li=el('li');if(item.task){const checkbox=el('input');checkbox.type='checkbox';checkbox.checked=Boolean(item.checked);checkbox.disabled=true;checkbox.setAttribute('aria-label',item.checked?'已完成':'未完成');li.append(checkbox);}const next=blocks(item.tokens,li,itemCursor);if(next>itemCursor)itemCursor=next;list.append(li);}target.append(list);}
  else if(token.type==='table'){const wrap=el('div',undefined,'md-table'),table=el('table'),head=el('thead'),row=el('tr'),body=el('tbody');token.header.forEach(cell=>{const th=el('th');th.scope='col';inline(cell.tokens,th);row.append(th);});head.append(row);table.append(head);for(const cells of token.rows){const tr=el('tr');cells.forEach(cell=>{const td=el('td');inline(cell.tokens,td);tr.append(td);});body.append(tr);}table.append(body);wrap.append(table);target.append(wrap);}
  else if(token.type==='hr')target.append(el('hr'));
  else if(token.type==='html')target.append(el('pre',token.text||token.raw,'md-literal'));
  else target.append(el('p',token.raw||token.text||''));
  const block=target.childNodes[target.childNodes.length-1];if(block&&sourceOffset>=0){const start=locationSource.slice(0,sourceOffset).split('\n').length,newlines=(raw.match(/\n/g)||[]).length,end=Math.max(start,start+newlines-(raw.endsWith('\n')?1:0));block.dataset.sourceStart=String(start);block.dataset.sourceEnd=String(end);}
  if(sourceOffset>=0)cursor=sourceOffset+raw.length;
 }return cursor;}
 container.className='markdown-body';blocks(marked.lexer(source,{gfm:true}),container,0);
 const slug=value=>value.toLowerCase().replace(/[^\p{L}\p{N}_\- ]/gu,'').trim().replace(/\s+/g,'-');
 for(const {a,href} of anchors){let decoded;try{decoded=decodeURIComponent(href.slice(1));}catch{decoded='';}const match=headings.find(h=>slug(h.label)===decoded);if(match){a.href='#'+match.element.id;a.addEventListener('click',event=>{event.preventDefault();match.element.scrollIntoView({block:'start'});});}else{a.removeAttribute('href');a.title='未找到对应标题';}}
 return headings;
}
