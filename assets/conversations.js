'use strict';
let conversationUI=null;
const MANUAL_CONVERSATION_LINKS_SCHEMA='chat-archify-manual-conversation-links';
const MANUAL_CONVERSATION_LINKS_VERSION=1;
const MANUAL_CONVERSATION_STORAGE_PREFIX='chat-archify:conversation-links:v1:';
let manualConversationLinksState={links:[],pending:[],raw_backup:[],storage:'pending',data_status:'unknown'};
let manualConversationLinksHydrated=false;
let conversationLinkNotice={kind:'',text:''};
const MANUAL_CONVERSATION_MAX_BYTES=1000000;
function conversationAlias(kind,id){
 const aliases=kind==='group'?E?.conversation_group_aliases:E?.conversation_entry_aliases;
 let current=typeof id==='string'?id:'';const seen=new Set();
 while(current&&aliases&&typeof aliases==='object'&&typeof aliases[current]==='string'&&!seen.has(current)){
  seen.add(current);current=aliases[current];
 }
 return current||id;
}
function manualConversationProjectId(){
 const explicit=E?.project_id||E?.project?.id||E?.manifest?.project_id;
 if(typeof explicit==='string'&&/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(explicit.trim()))return explicit.trim();
 const title=typeof E?.title==='string'?E.title.trim():'';
 let source='';
 for(const ch of Array.isArray(E?.chapters)?E.chapters:[]){
  for(const item of Array.isArray(ch?.record?.sources)?ch.record.sources:[]){
   source=String(item?.locator||item?.uri||item?.original_url||'').trim();
   if(source)break;
  }
  if(source)break;
 }
 const input=`${title}\n${source}`||'chat-archify-project';let hash=2166136261;
 for(const char of input){hash^=char.charCodeAt(0);hash=Math.imul(hash,16777619)>>>0;}
 return `legacy:${hash.toString(16).padStart(8,'0')}`;
}
let MANUAL_CONVERSATION_PROJECT_ID='';
function currentManualConversationProjectId(){if(!MANUAL_CONVERSATION_PROJECT_ID)MANUAL_CONVERSATION_PROJECT_ID=manualConversationProjectId();return MANUAL_CONVERSATION_PROJECT_ID;}
function manualConversationStorageKey(){
 const projectId=currentManualConversationProjectId();let hash=2166136261;for(const char of projectId){hash^=char.charCodeAt(0);hash=Math.imul(hash,16777619)>>>0;}
 return `${MANUAL_CONVERSATION_STORAGE_PREFIX}${hash.toString(16).padStart(8,'0')}`;
}
function manualConversationBackupKey(){return `${manualConversationStorageKey()}:raw-backup`;}
function manualConversationGroupId(entry){return typeof entry?.turn_group_id==='string'&&entry.turn_group_id?entry.turn_group_id:(typeof entry?.id==='string'?entry.id:'');}
function manualConversationGroups(){
 const groups=new Map();for(const entry of E.conversations||[]){const id=manualConversationGroupId(entry);if(!id)continue;if(!groups.has(id))groups.set(id,[]);groups.get(id).push(entry);}
 for(const group of groups.values())group.sort((a,b)=>(a.line||0)-(b.line||0));return groups;
}
function manualConversationKnownGroup(id){return typeof id==='string'&&manualConversationGroups().has(conversationAlias('group',id));}
function manualConversationKnownTarget(chapterId,nodeId){
 if(typeof chapterId!=='string'||typeof nodeId!=='string')return false;
 const chapter=(E.chapters||[]).find(item=>item?.id===chapterId);return Boolean(chapter?.record?.nodes?.some(node=>node?.id===nodeId));
}
function canonicalManualConversationLink(link){return {chapter_id:String(link.chapter_id),node_id:String(link.node_id),group_id:conversationAlias('group',String(link.group_id))};}
function manualConversationLinkKey(link){return `${link.chapter_id}\u0000${link.node_id}\u0000${link.group_id}`;}
function validateManualConversationLinksDocument(value,{allowPending=false}={}){
 let parsed=value;
 if(typeof value==='string'&&value.length>MANUAL_CONVERSATION_MAX_BYTES)return {ok:false,error:'关联文件过大，未导入。'};
 if(typeof value==='string'){try{parsed=JSON.parse(value);}catch{return {ok:false,error:'关联文件不是有效 JSON。'};}}
 if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return {ok:false,error:'关联文件格式不正确。'};
 if(parsed.schema!==MANUAL_CONVERSATION_LINKS_SCHEMA||parsed.version!==MANUAL_CONVERSATION_LINKS_VERSION)return {ok:false,error:'关联文件版本不受支持。'};
 if(parsed.project_id!==currentManualConversationProjectId())return {ok:false,error:'关联文件属于另一个项目。'};
 if(!Array.isArray(parsed.links)||parsed.links.length>5000)return {ok:false,error:'关联文件的链接列表无效或过大。'};
 if(parsed.pending!==undefined&&!Array.isArray(parsed.pending))return {ok:false,error:'关联文件的待处理列表无效。'};
 if(!allowPending&&Array.isArray(parsed.pending)&&parsed.pending.length)return {ok:false,error:'关联文件含待处理链接，请使用恢复入口。'};
 if(parsed.raw_backup!==undefined&&!Array.isArray(parsed.raw_backup))return {ok:false,error:'关联文件的原始备份无效。'};
 if(!allowPending&&Array.isArray(parsed.raw_backup)&&parsed.raw_backup.length)return {ok:false,error:'关联文件含原始备份，请使用恢复入口。'};
 const links=[],pending=[],seen=new Set();
 const consume=(raw,isPending=false)=>{
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||typeof raw.chapter_id!=='string'||typeof raw.node_id!=='string'||typeof raw.group_id!=='string')return {error:'关联文件包含格式错误的链接。'};
  const link=canonicalManualConversationLink(raw),knownTarget=manualConversationKnownTarget(link.chapter_id,link.node_id),knownGroup=manualConversationKnownGroup(link.group_id);
  if(!link.chapter_id||!link.node_id||!link.group_id||!knownTarget||!knownGroup){
   if(!allowPending&&!isPending)return {error:'关联文件包含当前项目不存在的模块或对话轮次。'};
   const key=manualConversationLinkKey(raw);if(!seen.has(key)){seen.add(key);pending.push({chapter_id:String(raw.chapter_id),node_id:String(raw.node_id),group_id:String(raw.group_id),reason:!knownTarget?'unknown-target':'unknown-group'});}return null;
  }
  const key=manualConversationLinkKey(link);if(!seen.has(key)){seen.add(key);links.push(link);}return null;
 };
 for(const raw of parsed.links){const issue=consume(raw);if(issue)return {ok:false,error:issue.error};}
 for(const raw of parsed.pending||[]){const issue=consume(raw,true);if(issue)return {ok:false,error:issue.error};}
 return {ok:true,project_id:currentManualConversationProjectId(),links,pending,raw_backup:Array.isArray(parsed.raw_backup)?parsed.raw_backup:[]};
}
function ensureManualConversationLinks(){
 if(manualConversationLinksHydrated){if(!Array.isArray(manualConversationLinksState.pending))manualConversationLinksState.pending=[];if(!Array.isArray(manualConversationLinksState.raw_backup))manualConversationLinksState.raw_backup=[];return manualConversationLinksState;}
 manualConversationLinksHydrated=true;manualConversationLinksState={links:[],pending:[],raw_backup:[],storage:'local',data_status:'empty'};
 try{
  if(typeof localStorage==='undefined')throw new Error('storage unavailable');
  const raw=localStorage.getItem(manualConversationStorageKey());
  const backup=localStorage.getItem(manualConversationBackupKey());
  if(backup){try{const parsedBackup=JSON.parse(backup);manualConversationLinksState.raw_backup=Array.isArray(parsedBackup)?parsedBackup:[parsedBackup];}catch{manualConversationLinksState.raw_backup=[{raw:backup,error:'raw backup is not JSON'}];}}
  if(!raw)return manualConversationLinksState;
  const parsed=validateManualConversationLinksDocument(raw,{allowPending:true});
  if(parsed.ok){manualConversationLinksState.links=parsed.links;manualConversationLinksState.pending=parsed.pending;const backups=new Set(manualConversationLinksState.raw_backup.map(item=>JSON.stringify(item)));for(const item of parsed.raw_backup){const key=JSON.stringify(item);if(!backups.has(key)){backups.add(key);manualConversationLinksState.raw_backup.push(item);}}manualConversationLinksState.data_status=parsed.pending.length?'pending':'valid';}
  else{
   manualConversationLinksState.data_status='invalid';manualConversationLinksState.raw_backup.push({raw,error:parsed.error,source:'localStorage',project_id:currentManualConversationProjectId()});
   try{localStorage.setItem(manualConversationBackupKey(),JSON.stringify(manualConversationLinksState.raw_backup));}catch{}
   setConversationLinkNotice('error',`本地关联数据无效，已保留原始备份；可导出恢复。${parsed.error||''}`);
  }
 }catch(error){manualConversationLinksState.storage='session';manualConversationLinksState.storage_reason='storage-unavailable';manualConversationLinksState.data_status='unknown';}
 return manualConversationLinksState;
}
function persistManualConversationLinks(){
 ensureManualConversationLinks();
 const payload={schema:MANUAL_CONVERSATION_LINKS_SCHEMA,version:MANUAL_CONVERSATION_LINKS_VERSION,project_id:currentManualConversationProjectId(),links:manualConversationLinksState.links.map(canonicalManualConversationLink)};
 if(manualConversationLinksState.pending.length)payload.pending=manualConversationLinksState.pending.map(item=>({...item}));
 if(manualConversationLinksState.raw_backup.length)payload.raw_backup=manualConversationLinksState.raw_backup.map(item=>({...item}));
 if(manualConversationLinksState.storage==='session')return false;
 try{if(typeof localStorage==='undefined')throw new Error('storage unavailable');localStorage.setItem(manualConversationStorageKey(),JSON.stringify(payload));manualConversationLinksState.data_status=manualConversationLinksState.pending.length?'pending':'valid';return true;}
 catch{manualConversationLinksState.storage='session';manualConversationLinksState.storage_reason='storage-unavailable';return false;}
}
function manualConversationLinksForNode(chapterId,nodeId){return ensureManualConversationLinks().links.filter(link=>link.chapter_id===chapterId&&link.node_id===nodeId);}
function manualConversationLinksForGroup(groupId){const current=conversationAlias('group',groupId);return ensureManualConversationLinks().links.filter(link=>conversationAlias('group',link.group_id)===current);}
function manualConversationLinkExists(chapterId,nodeId,groupId){const current=conversationAlias('group',groupId);return manualConversationLinksForNode(chapterId,nodeId).some(link=>conversationAlias('group',link.group_id)===current);}
function conversationTarget(target){
 if(!target||typeof target!=='object'||!manualConversationKnownTarget(target.chapter,target.node))return null;
 return {chapter:String(target.chapter),node:String(target.node)};
}
function manualConversationTargetLabel(target){const normalized=conversationTarget(target);if(!normalized)return '当前模块';const chapter=(E.chapters||[]).find(item=>item.id===normalized.chapter),node=chapter?.record?.nodes?.find(item=>item.id===normalized.node);return node?.display_title||node?.title||normalized.node;}
function conversationIdentityLabel(entry){
 const localPosition=entry?.position_kind==='message'?`本地消息序号 ${entry.message_index||'?'}`:`本地行号 ${entry?.line_range||`L${entry?.line||'?'}`}`;
 if(entry?.identity_kind==='local')return localPosition;
 const ids=[entry?.task_id&&`任务 ID：${entry.task_id}`,entry?.turn_id&&`轮次 ID：${entry.turn_id}`,entry?.message_id&&`消息 ID：${entry.message_id}`].filter(Boolean);
 return ids.length?`原始 ID · ${ids.join(' · ')}`:localPosition;
}
function linkedConversationModuleRecords(groupEntries){
 const ids=new Set((groupEntries||[]).map(entry=>entry?.id).filter(Boolean)),records=new Map(),ensure=(chapter,node)=>{
  const key=`${chapter}\u0000${node}`;if(!records.has(key))records.set(key,{chapter,node,labels:new Set(),manual:false});return records.get(key);
 };
 for(const chapter of E.chapters||[]){
  for(const node of chapter?.record?.nodes||[]){
   const exact=(node.conversation_entry_ids||[]).some(id=>ids.has(id)),source=(node.conversation_source_entry_ids||[]).some(id=>ids.has(id));
    if(exact){const matched=(node.conversation_entry_ids||[]).map(conversationEntry).filter(entry=>ids.has(entry?.id));ensure(chapter.id,node.id).labels.add(matched.some(entry=>entry?.identity_kind==='local')?'本地行号关联':'原始 ID 精确关联');}
  }
 }
 const groups=new Set((groupEntries||[]).map(manualConversationGroupId).filter(Boolean));for(const groupId of groups){for(const link of manualConversationLinksForGroup(groupId)){const record=ensure(link.chapter_id,link.node_id);record.labels.add('手动关联');record.manual=true;}}
 for(const entry of groupEntries||[]){for(const item of Array.isArray(entry?.nodes)?entry.nodes:[]){if(!item?.chapter||!item?.node||!manualConversationKnownTarget(item.chapter,item.node))continue;const record=ensure(item.chapter,item.node);if(!record.labels.size)record.labels.add('原始记录关联');}}
 return [...records.values()].map(record=>({...record,labels:[...record.labels]})).sort((a,b)=>`${a.chapter}/${a.node}`.localeCompare(`${b.chapter}/${b.node}`));
}
function linkedConversationModuleCandidates(groupEntries){
 const ids=new Set((groupEntries||[]).map(entry=>entry?.id).filter(Boolean)),records=new Map(),confirmed=new Set(linkedConversationModuleRecords(groupEntries).map(record=>`${record.chapter}\u0000${record.node}`)),ensure=(chapter,node)=>{const key=`${chapter}\u0000${node}`;if(!records.has(key))records.set(key,{chapter,node,labels:['同来源摘录（原始未精确对应）']});return records.get(key);};
 for(const chapter of E.chapters||[]){for(const node of chapter?.record?.nodes||[]){const exact=(node.conversation_entry_ids||[]).some(id=>ids.has(id));const source=(node.conversation_source_entry_ids||[]).some(id=>ids.has(id));if(source&&!exact&&!confirmed.has(`${chapter.id}\u0000${node.id}`))ensure(chapter.id,node.id);}}
 return [...records.values()].sort((a,b)=>`${a.chapter}/${a.node}`.localeCompare(`${b.chapter}/${b.node}`));
}
function conversationModuleLabel(record){
 const chapter=(E.chapters||[]).find(item=>item.id===record.chapter),node=chapter?.record?.nodes?.find(item=>item.id===record.node);return node?.display_title||node?.title||record.node;
}
function conversationModuleSummary(groupEntries){
 const records=linkedConversationModuleRecords(groupEntries);if(!records.length)return '';
 const manual=records.filter(record=>record.labels.includes('手动关联')).length,original=records.filter(record=>record.labels.some(label=>label.startsWith('原始'))).length,source=records.filter(record=>record.labels.some(label=>label.startsWith('同来源'))).length;
 const parts=[];if(manual)parts.push(`手动 ${manual}`);if(original)parts.push(`原始 ${original}`);if(source)parts.push(`同来源 ${source}`);return `${records.length} 个关联模块 · ${parts.join(' · ')}`;
}
function conversationScopeForNode(node,chapterId=app.chapter){
 const exact=Array.isArray(node?.conversation_entry_ids)?node.conversation_entry_ids.filter(id=>typeof id==='string'&&conversationEntry(id)):[];
 const source=Array.isArray(node?.conversation_source_entry_ids)?node.conversation_source_entry_ids.filter(id=>typeof id==='string'&&conversationEntry(id)):[];
 const manual=manualConversationLinksForNode(chapterId,node?.id).flatMap(link=>manualConversationGroups().get(link.group_id)||[]).map(entry=>entry.id);
 const ids=expandConversationIds([...exact,...manual]),confirmed=new Set(ids),sourceIds=expandConversationIds(source).filter(id=>!confirmed.has(id)),lineExact=exact.length&&exact.every(id=>conversationEntry(id)?.identity_kind==='local');
 return {ids,mode:ids.length?(manual.length&&exact.length?'mixed':manual.length?'manual':lineExact?'line':exact.length?'exact':'none'):'none',sourceIds};
}
function expandConversationIds(ids){
 const result=[],seen=new Set(),groups=manualConversationGroups();for(const id of ids||[]){const entry=conversationEntry(id);const group=entry?[...(groups.get(manualConversationGroupId(entry))||[entry])]:[];for(const item of group){if(item?.id&&!seen.has(item.id)){seen.add(item.id);result.push(item.id);}}}return result;
}
function manualConversationAssociationNotice(){
 if(!conversationLinkNotice.text)return null;const box=el('p',conversationLinkNotice.text,`conversation-link-notice ${conversationLinkNotice.kind||''}`);box.setAttribute('role','status');return box;
}
function setConversationLinkNotice(kind,text){conversationLinkNotice={kind:String(kind||''),text:String(text||'')};}
function associationTargetFromApp(){return conversationTarget(app.conversationAssociationTarget);}
function startConversationAssociationPicker(){
 if(app.conversationAssociationPicker){updateConversationScopeForTarget();return;}
 const target=associationTargetFromApp();if(!target)return;saveCurrentPosition();app.conversationAssociationPicker=true;app.conversationTask='';app.conversationQuery='';app.listScroll=0;app.conversationScope=null;app.conversationScopeMode='picker';app.conversationLabel=manualConversationTargetLabel(target);persistState();renderRoute({restoreScroll:true});
}
function updateConversationScopeForTarget({preservePosition=true}={}){
 const target=associationTargetFromApp();if(!target)return;
 const chapter=(E.chapters||[]).find(item=>item.id===target.chapter),node=chapter?.record?.nodes?.find(item=>item.id===target.node);if(!node)return;
 const scope=conversationScopeForNode(node,target.chapter);app.conversationTask='';app.conversationQuery='';app.listScroll=0;app.conversationScope=scope.ids;app.conversationScopeMode=scope.mode;app.conversationAssociationPicker=false;app.conversationLabel=nodeTitleForConversation(node);if(preservePosition){saveCurrentPosition();}persistState();renderRoute({restoreScroll:preservePosition});
}
function nodeTitleForConversation(node){return node?.display_title||node?.title||'当前模块';}
function syncConversationModuleScope(){
 const target=associationTargetFromApp();if(!target||app.conversationAssociationPicker||app.conversationScopeMode==='source')return;
 const node=findNode(target.node,target.chapter),scope=conversationScopeForNode(node,target.chapter);app.conversationScope=scope.ids;app.conversationScopeMode=scope.mode;app.conversationLabel=nodeTitleForConversation(node);
}
function refreshConversationAssociations(){
 saveCurrentPosition();syncConversationModuleScope();persistState();renderRoute({restoreScroll:true});if(app.conversationId){refreshConversationDialogEntry(app.conversationId);$('conversation-dialog-close')?.focus({preventScroll:true});}
}
function addManualConversationLink(chapterId,nodeId,groupId,{refresh=true}={}){
 ensureManualConversationLinks();const target={chapter:chapterId,node:nodeId};if(!conversationTarget(target)||!manualConversationKnownGroup(groupId))return {ok:false,error:'找不到目标模块或对话轮次。'};
 if(manualConversationLinkExists(chapterId,nodeId,groupId))return {ok:true,added:false,duplicate:true};if(manualConversationLinksState.links.length>=5000){setConversationLinkNotice('error','关联数量超过上限，未添加。');return {ok:false,error:'关联数量超过上限，未添加。'};}manualConversationLinksState.links.push({chapter_id:String(chapterId),node_id:String(nodeId),group_id:String(groupId)});const persisted=persistManualConversationLinks();setConversationLinkNotice(persisted?'success':'session',persisted?'已关联此对话轮次。':'已关联此对话轮次；当前浏览器未允许本地保存，关闭页面后会丢失。');if(refresh)refreshConversationAssociations();return {ok:true,added:true,persisted};
}
function removeManualConversationLink(chapterId,nodeId,groupId,{refresh=true}={}){
 ensureManualConversationLinks();const current=conversationAlias('group',groupId),before=manualConversationLinksState.links.length;manualConversationLinksState.links=manualConversationLinksState.links.filter(link=>!(link.chapter_id===chapterId&&link.node_id===nodeId&&conversationAlias('group',link.group_id)===current));if(before===manualConversationLinksState.links.length)return {ok:true,removed:false};const persisted=persistManualConversationLinks();setConversationLinkNotice(persisted?'success':'session',persisted?'已移除手动关联。':'已移除手动关联；当前浏览器未允许本地保存。');if(refresh)refreshConversationAssociations();return {ok:true,removed:true,persisted};
}
function manualConversationExportPayload(){
 ensureManualConversationLinks();const payload={schema:MANUAL_CONVERSATION_LINKS_SCHEMA,version:MANUAL_CONVERSATION_LINKS_VERSION,project_id:currentManualConversationProjectId(),links:manualConversationLinksState.links.map(canonicalManualConversationLink)};
 if(manualConversationLinksState.pending.length)payload.pending=manualConversationLinksState.pending.map(item=>({...item}));
 if(manualConversationLinksState.raw_backup.length)payload.raw_backup=manualConversationLinksState.raw_backup.map(item=>({...item}));
 return payload;
}
function exportManualConversationLinks(){
 const bytes=new TextEncoder().encode(JSON.stringify(manualConversationExportPayload(),null,2));downloadBytes(bytes,'chat-archify-conversation-links.json','application/json;charset=utf-8');setConversationLinkNotice('success','已导出手动关联元数据；文件不包含对话正文或项目文件。');if(app.view==='conversations')renderRoute({restoreScroll:true});
}
function importManualConversationLinks(value,{allowPending=false}={}){
 if(typeof value==='string'&&value.length>MANUAL_CONVERSATION_MAX_BYTES){setConversationLinkNotice('error','关联文件过大，未导入。');return {ok:false,error:'关联文件过大，未导入。'};}
 const parsed=validateManualConversationLinksDocument(value,{allowPending});if(!parsed.ok){setConversationLinkNotice('error',parsed.error);return parsed;}
 ensureManualConversationLinks();if(allowPending&&parsed.raw_backup.length)manualConversationLinksState.raw_backup.push(...parsed.raw_backup);const existing=new Set(manualConversationLinksState.links.map(manualConversationLinkKey));const pendingKeys=new Set(manualConversationLinksState.pending.map(manualConversationLinkKey));const additions=parsed.links.filter(link=>!existing.has(manualConversationLinkKey(link)));if(manualConversationLinksState.links.length+additions.length>5000){setConversationLinkNotice('error','关联数量超过上限，未导入。');return {ok:false,error:'关联数量超过上限，未导入。'};}let added=0;for(const link of additions){existing.add(manualConversationLinkKey(link));manualConversationLinksState.links.push(link);added++;}let pendingAdded=0;for(const link of parsed.pending){const key=manualConversationLinkKey(link);if(pendingKeys.has(key))continue;pendingKeys.add(key);manualConversationLinksState.pending.push(link);pendingAdded++;}const persisted=persistManualConversationLinks();setConversationLinkNotice(persisted?'success':'session',`${added?`已导入 ${added} 条手动关联。`:''}${pendingAdded?`已保留 ${pendingAdded} 条待处理关联。`:'没有新增关联。'} 文件只包含元数据，不包含对话正文或项目文件。${persisted?'':'当前浏览器未允许本地保存，关闭页面后会丢失。'}`);if(app.view==='conversations')refreshConversationAssociations();return {ok:true,added, pendingAdded,duplicates:parsed.links.length-added,persisted};
}
function recoverManualConversationLinks(value){return importManualConversationLinks(value,{allowPending:true});}
function openManualConversationImport(){
 const input=document.createElement('input');input.type='file';input.accept='application/json,.json';input.addEventListener('change',async event=>{const file=event.target?.files?.[0];if(!file)return;if(Number(file.size)>1000000){setConversationLinkNotice('error','关联文件过大，未导入。');if(app.view==='conversations')renderRoute({restoreScroll:true});return;}try{const text=typeof file.text==='function'?await file.text():'';if(!text)throw new Error('无法读取关联文件。');importManualConversationLinks(text);}catch(error){setConversationLinkNotice('error',error?.message||'无法读取关联文件。');}if(app.view==='conversations')renderRoute({restoreScroll:true});});input.click();
}
function openManualConversationRecovery(){
 const input=document.createElement('input');input.type='file';input.accept='application/json,.json';input.addEventListener('change',async event=>{const file=event.target?.files?.[0];if(!file)return;if(Number(file.size)>MANUAL_CONVERSATION_MAX_BYTES){setConversationLinkNotice('error','关联文件过大，未恢复。');if(app.view==='conversations')renderRoute({restoreScroll:true});return;}try{const text=typeof file.text==='function'?await file.text():'';if(!text)throw new Error('无法读取关联文件。');recoverManualConversationLinks(text);}catch(error){setConversationLinkNotice('error',error?.message||'无法读取关联文件。');}if(app.view==='conversations')renderRoute({restoreScroll:true});});input.click();
}
function removePendingManualConversationLink(index,{refresh=true}={}){
 ensureManualConversationLinks();const at=Number(index);if(!Number.isInteger(at)||at<0||at>=manualConversationLinksState.pending.length)return {ok:false,error:'找不到待处理关联。'};manualConversationLinksState.pending.splice(at,1);const persisted=persistManualConversationLinks();setConversationLinkNotice(persisted?'success':'session','已移除待处理关联。');if(refresh&&app.view==='conversations')renderRoute({restoreScroll:true});return {ok:true,persisted};
}
function rebindPendingManualConversationLink(index,chapterId,nodeId,groupId,{refresh=true}={}){
 ensureManualConversationLinks();const at=Number(index),target={chapter:chapterId,node:nodeId};if(!Number.isInteger(at)||at<0||at>=manualConversationLinksState.pending.length)return {ok:false,error:'找不到待处理关联。'};if(!conversationTarget(target)||!manualConversationKnownGroup(groupId))return {ok:false,error:'找不到新的目标模块或对话轮次。'};const link={chapter_id:String(chapterId),node_id:String(nodeId),group_id:conversationAlias('group',String(groupId))};if(!manualConversationLinkExists(link.chapter_id,link.node_id,link.group_id))manualConversationLinksState.links.push(link);manualConversationLinksState.pending.splice(at,1);const persisted=persistManualConversationLinks();setConversationLinkNotice(persisted?'success':'session','已重新绑定待处理关联。');if(refresh&&app.view==='conversations')refreshConversationAssociations();return {ok:true,persisted};
}
function renderPendingManualConversationLinks(root){
 ensureManualConversationLinks();if(!manualConversationLinksState.pending.length&&!manualConversationLinksState.raw_backup.length)return;
 const box=section(root,`待处理关联 · ${manualConversationLinksState.pending.length}`);paragraph(box,'这些关联记录仍保留，但当前页面找不到原模块或对话轮次；可导出备份、移除或重新绑定。','note');
 if(manualConversationLinksState.raw_backup.length)box.append(button('导出原始备份',exportManualConversationLinks,'button'));
 for(let index=0;index<manualConversationLinksState.pending.length;index++){
  const item=manualConversationLinksState.pending[index],row=el('div',undefined,'conversation-module-link');row.append(el('span',`模块 ${item.chapter_id||'未记录'} / 目标 ${item.node_id||'未记录'} / 对话 ${item.group_id||'未记录'} · ${item.reason||'待处理'}`,'conversation-link-labels'));
  const targets=el('select');targets.setAttribute('aria-label','待处理关联的新模块');const firstTarget=el('option','选择模块');firstTarget.value='';targets.append(firstTarget);for(const chapter of E.chapters||[]){for(const node of chapter?.record?.nodes||[]){const option=el('option',`${chapter.label||chapter.id} · ${nodeTitleForConversation(node)}`);option.value=`${chapter.id}\u0000${node.id}`;targets.append(option);}}
  const groups=el('select');groups.setAttribute('aria-label','待处理关联的新对话轮次');const firstGroup=el('option','选择对话轮次');firstGroup.value='';groups.append(firstGroup);for(const [groupId,entries] of manualConversationGroups()){const option=el('option',conversationTitleForGroup(entries));option.value=groupId;groups.append(option);}
  row.append(targets,groups,button('重新绑定',()=>{const [chapter,node]=String(targets.value||'').split('\u0000');if(chapter&&node&&groups.value)rebindPendingManualConversationLink(index,chapter,node,groups.value);},'link-button'),button('移除',()=>removePendingManualConversationLink(index),'link-button'));box.append(row);
 }
 root.append(box);
}
function conversationRole(entry){return String(entry?.role||'').trim().toLocaleLowerCase();}
function isUserConversation(entry){return ['用户','user','human','request'].includes(conversationRole(entry));}
function isSummaryConversation(entry){return ['摘要','summary','summarized'].includes(conversationRole(entry));}
function cleanConversationTitleText(value){
 return String(value||'').replace(/\r/g,'').replace(/\\([_*#>\[\]])/g,'$1').replace(/\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/`/g,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/__([^_]+)__/g,'$1').replace(/(^|[\s(])\*([^*]+)\*(?=$|[\s).])/g,'$1$2').replace(/(^|[\s(])_([^_]+)_(?=$|[\s).])/g,'$1$2').replace(/^\s*[-*>#|]+\s*/,'').replace(/\s+/g,' ').trim();
}
function conversationTitleSource(entry){
 const raw=String(entry?.text||'').replace(/\r/g,'').trim();
 if(isSummaryConversation(entry)){
  const quoted=raw.split('\n').map(line=>line.trim()).find(line=>/^>\s*/.test(line));
  if(quoted)return quoted.replace(/^>\s*/,'');
  const withoutProvenance=raw.split('\n').filter(line=>!/^来源：?\s*Codex\s+read_thread/i.test(line.trim())).join('\n').trim();
  return withoutProvenance||raw;
 }
 const marked=raw.split(/(?:^|\n)\s*##\s*My request\s*:\s*/i),withoutMarker=(marked.length>1?marked.at(-1):raw.replace(/<(?:in-app-browser-context|environment_context|memory)(?:\s[^>]*)?>[\s\S]*?<\/(?:in-app-browser-context|environment_context|memory)>/gi,'')).trim();
 return withoutMarker||raw;
}
function firstConversationSegment(entry){
 const source=conversationTitleSource(entry),parts=source.split(/\n\s*\n|\n/).map(part=>cleanConversationTitleText(part)).filter(Boolean);
 const first=parts[0]||'',sentence=first.match(/^(.+?[。！？；])/);return (sentence?sentence[1].replace(/[。！？；]$/,''):first).trim();
}
function truncateConversationTitle(value,max=74){const text=cleanConversationTitleText(value);return text.length>max?text.slice(0,max-1)+'…':text;}
function conversationLead(group){return group.find(isUserConversation)||group.find(isSummaryConversation)||group[0]||null;}
function conversationTitleForGroup(group){
 const lead=conversationLead(group);
 if(!lead)return '未命名对话轮次';
 const title=truncateConversationTitle(firstConversationSegment(lead))||'未提供可识别内容';
 if(isSummaryConversation(lead))return `保存摘要｜${title}`;
 if(!isUserConversation(lead))return `已记录结果｜${title}`;
 return title;
}
function conversationTitleForEntry(entry){
 if(!entry)return '对话摘录';
 const group=entry.turn_group_id?(E.conversations||[]).filter(item=>item.turn_group_id===entry.turn_group_id):[entry];
 return conversationTitleForGroup(group.length?group:[entry]);
}
function conversationCardPreview(group){
 const lead=conversationLead(group),title=firstConversationSegment(lead);if(!isUserConversation(lead)||title.length>12)return '';
 const assistant=group.find(entry=>conversationRole(entry)==='助手'||conversationRole(entry)==='assistant');return assistant?truncateConversationTitle(firstConversationSegment(assistant),70):'';
}
function conversationCardMeta(group){
 const lead=conversationLead(group),roleLabel=isSummaryConversation(lead)?'保存摘要':isUserConversation(lead)?'用户提问':'已记录结果',parts=[lead?.date||'时间未收录',roleLabel,`${group.length}段消息`];
 return parts.filter(Boolean).join(' · ');
}
function excerptSummary(entry){return truncateConversationTitle(firstConversationSegment(entry),150);}
function conversationIdsFor(node,chapterId=app.chapter){
 return conversationScopeForNode(node,chapterId).ids;
}
function conversationEntry(id){const direct=(E.conversations||[]).find(entry=>entry.id===id);if(direct)return direct;const migrated=conversationAlias('entry',id);return migrated===id?null:(E.conversations||[]).find(entry=>entry.id===migrated)||null;}
function conversationScopeEntries(){
 syncConversationModuleScope();
 const scope=Array.isArray(app.conversationScope)?new Set(expandConversationIds(app.conversationScope)):null;
 return (E.conversations||[]).filter(e=>!scope||scope.has(e.id));
}
function conversationMatches(entry,q){
 return !q||[entry.source_title,entry.date,entry.role,entry.task_id,entry.text].join(' ').toLocaleLowerCase().includes(q.toLocaleLowerCase());
}
function conversationGroups(entries){
 const groups=new Map();for(const entry of entries){const key=entry.turn_group_id||entry.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(entry);}
 return [...groups.values()].map(group=>group.sort((a,b)=>(a.line||0)-(b.line||0))).sort((a,b)=>(a[0].line||0)-(b[0].line||0));
}
function completeConversationGroup(group){
 const keys=new Set(group.map(entry=>entry.turn_group_id).filter(Boolean));if(!keys.size)return group;
 return (E.conversations||[]).filter(entry=>keys.has(entry.turn_group_id)).sort((a,b)=>(a.conversation_order??a.line??0)-(b.conversation_order??b.line??0));
}
function renderConversationIndex(root){
 syncConversationModuleScope();
 ensureManualConversationLinks();root.replaceChildren();
 const collection=E.collection_audit?.audit;if(collection){const counts=collection.counts,details=el('details',undefined,'technical-details');details.append(el('summary',`收录情况 · ${counts.threads} 个对话，${counts.read_complete} 个已读到结尾`));paragraph(details,E.collection_audit.status==='complete'?'分页和导出一致性检查通过。':'本次为部分收录；可读内容已保存，以下缺口仍保留。','note');const failed=new Set((collection.gaps||[]).filter(g=>g.reason==='unread_page').map(g=>g.thread_id));for(const id of failed){const entry=(E.conversations||[]).find(e=>e.task_id===id);paragraph(details,`${entry?.source_title||'来源对话'}：部分历史无法继续读取。`,'note');}const attachments=(collection.gaps||[]).filter(g=>g.reason==='unsupported_attachment').length;if(attachments)paragraph(details,`${attachments} 条消息包含未导入的图片等附件；已保存可读取的文字。`,'note');if(counts.credential_exclusions)paragraph(details,`${counts.credential_exclusions} 条疑似包含凭据的消息已过滤。`,'note');root.append(details);}
  if(Array.isArray(app.conversationScope)){const scopeText=app.conversationScopeMode==='exact'?'仅显示与此阶段按原始 ID 精确对应的摘录':app.conversationScopeMode==='line'?'仅显示与此阶段按本地行号精确对应的摘录':app.conversationScopeMode==='source'?'仅显示同来源任务摘录；原记录未精确对应到此阶段':app.conversationScopeMode==='mixed'?'显示原记录与手动关联的摘录':app.conversationScopeMode==='manual'?'显示手动关联的摘录':'仅显示此阶段已关联的摘录';const scopeNote=el('p',app.conversationLabel?`当前阶段：${app.conversationLabel} · ${scopeText}`:scopeText,'conversation-scope-note');root.append(scopeNote);}
 const controls=el('div',undefined,'conversation-controls');
 const task=el('select');task.setAttribute('aria-label','按任务标题筛选');const all=el('option','全部已收录任务');all.value='';task.append(all);
 const entries=conversationScopeEntries(),titles=[...new Set(entries.map(e=>e.source_title).filter(Boolean))];for(const title of titles){const option=el('option',title);option.value=title;task.append(option);}if(app.conversationTask&&!titles.includes(app.conversationTask)){app.conversationTask='';persistState();}task.value=app.conversationTask||'';
 task.addEventListener('change',()=>{app.conversationTask=task.value;app.listScroll=0;persistState();renderConversationList();});
 const searchInput=el('input');searchInput.type='search';searchInput.placeholder='搜索已保存摘录';searchInput.setAttribute('aria-label','搜索已保存对话摘录');searchInput.value=app.conversationQuery||'';
 searchInput.addEventListener('input',()=>{app.conversationQuery=searchInput.value;app.listScroll=0;persistState();renderConversationList();});
 const reset=button('清除筛选',()=>{app.conversationTask='';app.conversationQuery='';persistState();task.value='';searchInput.value='';renderConversationList();});
 const count=el('span','', 'note');controls.append(task,searchInput,reset);
 const target=associationTargetFromApp();if(target){controls.append(button(app.conversationAssociationPicker?'退出关联选择':'关联已有对话',()=>startConversationAssociationPicker(),'button association-picker-toggle'));if(!app.conversationAssociationPicker){const node=findNode(target.node,target.chapter),scope=conversationScopeForNode(node,target.chapter);if(app.conversationScopeMode==='source')controls.append(button('返回已关联对话',()=>navigateToConversationIndex(scope.ids,nodeTitleForConversation(node),scope.mode,target),'button'));else if(scope.sourceIds.length)controls.append(button('查看同来源候选（未确认关联）',()=>navigateToConversationIndex(scope.sourceIds,nodeTitleForConversation(node),'source',target),'button'));}}
 const tools=el('details',undefined,'conversation-secondary-tools');tools.append(el('summary','关联数据'));tools.append(button('导出关联',exportManualConversationLinks,'button'),button('导入关联',openManualConversationImport,'button'),button('恢复待处理',openManualConversationRecovery,'button'));controls.append(tools,count);root.append(controls);
  paragraph(root,'手动关联可在本地保存；换浏览器或更新 HTML 前，请先导出关联。','note conversation-storage-note');if(manualConversationLinksState.storage==='session')paragraph(root,'当前浏览器未允许本地保存；关联仍可使用并导出。','note');const notice=manualConversationAssociationNotice();if(notice)root.append(notice);renderPendingManualConversationLinks(root);
 const grid=el('div',undefined,'conversation-grid'),list=el('div',undefined,'conversation-list');list.id='conversation-list';list.setAttribute('aria-label','按任务和轮次分组的已保存摘录');grid.append(list);root.append(grid);
 list.addEventListener('scroll',()=>{app.listScroll=list.scrollTop;savePositionSoon();});conversationUI={task,searchInput,count,list};renderConversationList();
}
function renderConversationList(){
 const ui=conversationUI;if(!ui)return;const q=(ui.searchInput?.value||app.conversationQuery||'').trim(),task=ui.task?.value||app.conversationTask||'';
 const scoped=conversationScopeEntries().filter(e=>!task||e.source_title===task),entries=scoped.filter(e=>conversationMatches(e,q)),matchedIds=new Set(entries.map(entry=>entry.id));const groups=conversationGroups(scoped).filter(group=>group.some(entry=>matchedIds.has(entry.id)));
 ui.list.replaceChildren();ui.list.hidden=false;ui.list.parentElement.classList.remove('has-conversation');ui.count.textContent=`${groups.length} 轮 · ${entries.length} 段已保存摘录`;
 if(!entries.length){const empty=el('div',undefined,'conversation-empty');if(Array.isArray(app.conversationScope)&&conversationScopeEntries().length===0){paragraph(empty,app.conversationLabel?`“${app.conversationLabel}”未收录此阶段的原始对话，也没有已关联的保存摘录。`:'未收录此阶段的原始对话，也没有已关联的保存摘录。','notice');const target=associationTargetFromApp();if(target){empty.append(button('关联已有对话',startConversationAssociationPicker,'button primary'));const node=findNode(target.node,target.chapter),chapter=C.get(target.chapter),sources=new Map((chapter?.record?.sources||[]).map(source=>[source.id,source])),shown=new Set();for(const ref of node?.evidence||[]){const source=sources.get(ref.source),fileId=source?.file_id;if(!fileId||!E.files[fileId]||shown.has(fileId))continue;shown.add(fileId);empty.append(button(source.title||E.files[fileId].name||'查看阶段来源资料',()=>openFile(fileId,{from:app,note:source.note||'',locator:ref.locator||''}),'link-button'));}}empty.append(button('查看全部已收录对话',()=>navigateToConversationIndex(null,''),'button'));}else paragraph(empty,q?'没有匹配的已保存摘录。':'当前筛选没有可显示的摘录。','notice');ui.list.append(empty);return;}
 const active=groups.some(group=>group.some(e=>e.id===app.conversationId))?app.conversationId:null;
 for(const group of groups){const fullGroup=completeConversationGroup(group),lead=conversationLead(fullGroup),target=associationTargetFromApp(),node=target&&findNode(target.node,target.chapter),exactIds=new Set((node?.conversation_entry_ids||[]).map(resolveConversationEntryId)),exact=app.conversationScopeMode!=='source'&&!app.conversationAssociationPicker?fullGroup.find(entry=>exactIds.has(entry.id)):null,selection=exact||conversationLead(group)||group[0],selected=active&&group.some(e=>e.id===active),picker=Boolean(app.conversationAssociationPicker&&associationTargetFromApp());let b;
  if(picker){b=el('div',undefined,'conversation-result');b.tabIndex=0;b.setAttribute('role','button');b.addEventListener('click',event=>{if(event.target?.closest?.('button'))return;navigateToConversationEntry(selection.id);});b.addEventListener('keydown',event=>{if(event.target!==b)return;if(['Enter',' '].includes(event.key)){event.preventDefault();navigateToConversationEntry(selection.id);}});}else b=button('',()=>navigateToConversationEntry(selection.id),'conversation-result');
  b.dataset.conversationId=selection.id;b.setAttribute('aria-pressed',String(Boolean(selected)));b.title=conversationTitleForGroup(fullGroup);
  b.append(el('strong',conversationTitleForGroup(fullGroup)),el('span',conversationCardMeta(fullGroup)));const preview=exact?firstConversationSegment(exact):conversationCardPreview(fullGroup);if(preview)b.append(el('span',`${exact?'阶段匹配片段':'助手摘要'}：${preview}`,'conversation-card-preview'));const modules=conversationModuleSummary(fullGroup);if(modules)b.append(el('span',modules,'conversation-card-associations'));if(fullGroup.some(isSummaryConversation)&&!fullGroup.some(isUserConversation))b.append(el('span','这是已保存摘要；原始问答未收录。','conversation-card-coverage'));else if(!fullGroup.some(isUserConversation))b.append(el('span','未收录用户提问；仅显示已保存结果。','conversation-card-coverage'));else if(!fullGroup.some(entry=>['助手','assistant'].includes(conversationRole(entry))))b.append(el('span','回答未收录；仅显示已保存问题。','conversation-card-coverage'));
  if(picker){const target=associationTargetFromApp(),linked=manualConversationLinkExists(target.chapter,target.node,manualConversationGroupId(selection));b.append(button(linked?'移除手动关联':'关联此对话',event=>{event.stopPropagation?.();const result=linked?removeManualConversationLink(target.chapter,target.node,manualConversationGroupId(selection),{refresh:false}):addManualConversationLink(target.chapter,target.node,manualConversationGroupId(selection),{refresh:false});if(result.ok){app.conversationAssociationPicker=false;app.conversationTask='';app.conversationQuery='';app.listScroll=0;}refreshConversationAssociations();},'button association-card-action'));}
  ui.list.append(b);
 }
 ui.list.parentElement.classList.toggle('has-conversation',Boolean(active));
}
function relatedTurnEntries(entry){
 if(Array.isArray(entry.turn_entry_ids)&&entry.turn_entry_ids.length)return entry.turn_entry_ids.map(conversationEntry).filter(Boolean);
 if(entry.turn_id)return (E.conversations||[]).filter(e=>e.file_id===entry.file_id&&e.task_id===entry.task_id&&e.turn_id===entry.turn_id).sort((a,b)=>(a.line||0)-(b.line||0));
 return [];
}
function neighborEntries(entry){
 if(Array.isArray(entry.context_entry_ids))return entry.context_entry_ids.map(conversationEntry).filter(Boolean);
 const same=(E.conversations||[]).filter(e=>e.file_id===entry.file_id&&e.task_id===entry.task_id).sort((a,b)=>(a.line||0)-(b.line||0)),i=same.findIndex(e=>e.id===entry.id);return [...(i>0?[same[i-1]]:[]),...(i>=0&&i+1<same.length?[same[i+1]]:[])];
}
function refreshConversationDialogEntry(entryId){
 const content=$('conversation-dialog-content');if(!content||!entryId)return;const scroll=Number(content.scrollTop)||0;renderConversationEntry(content,entryId);content.scrollTop=scroll;app.conversationDialogScroll=scroll;
}
function linkConversationGroupToTarget(entry,target){
 const normalized=conversationTarget(target);if(!normalized)return;const result=addManualConversationLink(normalized.chapter,normalized.node,manualConversationGroupId(entry),{refresh:false});if(result.ok&&!result.duplicate){const persisted=result.persisted;setConversationLinkNotice(persisted?'success':'session',persisted?'已关联此对话轮次。':'已关联此对话轮次；当前浏览器未允许本地保存，关闭页面后会丢失。');refreshConversationAssociations();}
}
function renderConversationModuleLinks(parent,group,entry){
 const records=linkedConversationModuleRecords(group),candidates=linkedConversationModuleCandidates(group),target=associationTargetFromApp(),sectionRoot=section(parent,`关联模块 · ${records.length}`);const notice=manualConversationAssociationNotice();if(notice)sectionRoot.append(notice);
 if(!records.length)paragraph(sectionRoot,'这组已保存摘录还没有已确认的模块关联。','note');
 for(const record of records){
  const row=el('div',undefined,'conversation-module-link'),meta=el('div',undefined,'conversation-module-link-meta');meta.append(el('strong',conversationModuleLabel(record)));const labels=el('span',record.labels.join(' · '),'conversation-link-labels');meta.append(labels);row.append(meta,button('查看模块',()=>navigateNode(record.node,record.chapter),'link-button'));
  if(record.manual)row.append(button('移除手动关联',()=>removeManualConversationLink(record.chapter,record.node,manualConversationGroupId(entry)),'link-button association-remove'));
  sectionRoot.append(row);
 }
 if(candidates.length){const details=disclosureDetails(`同来源候选 · ${candidates.length}`,disclosureKey('conversation',entry.id,'module-candidates'),'technical-details conversation-module-candidates');paragraph(details,'这些模块共享来源摘录，但原记录没有精确对应；仅供人工判断。','note');for(const candidate of candidates){const row=el('div',undefined,'conversation-module-link');row.append(el('strong',conversationModuleLabel(candidate)),el('span','同来源摘录（原始未精确对应）','conversation-link-labels'),button('查看模块',()=>navigateNode(candidate.node,candidate.chapter),'link-button'));details.append(row);}sectionRoot.append(details);}
 if(target&&!records.some(record=>record.chapter===target.chapter&&record.node===target.node)){const action=el('div',undefined,'conversation-association-inline');paragraph(action,`当前目标：${manualConversationTargetLabel(target)}`,'note');action.append(button('关联到当前模块',()=>linkConversationGroupToTarget(entry,target),'button primary'));sectionRoot.append(action);}
 if(!target){const action=el('div',undefined,'conversation-association-inline');paragraph(action,'选择一个现有模块后，手动关联这整组已保存摘录。','note');const picker=el('select');picker.setAttribute('aria-label','选择要关联的模块');const first=el('option','选择模块');first.value='';picker.append(first);for(const chapter of E.chapters||[]){for(const node of chapter?.record?.nodes||[]){const option=el('option',`${chapter.label||chapter.id} · ${nodeTitleForConversation(node)}`);option.value=`${chapter.id}\u0000${node.id}`;picker.append(option);}}const actionButton=button('关联到所选模块',()=>{const [chapter,node]=String(picker.value||'').split('\u0000');if(chapter&&node)linkConversationGroupToTarget(entry,{chapter,node});},'button primary');action.append(picker,actionButton);sectionRoot.append(action);}
}
function renderConversationEntry(root,id){
 root.replaceChildren();const entry=conversationEntry(id);if(!entry){paragraph(root,'找不到这段已保存摘录。','notice');return;}
 const related=relatedTurnEntries(entry),group=completeConversationGroup(related.length?related:[entry]),title=conversationTitleForGroup(group),dialogTitle=$('conversation-dialog-title'),dialogMeta=$('conversation-dialog-meta');if(dialogTitle)dialogTitle.textContent=title;if(dialogMeta)dialogMeta.textContent=`${entry.date||'时间未收录'} · ${group.length} 段已保存消息`;
 paragraph(root,'以下内容仅来自已保存摘录；未收录的轮次不会补写。','conversation-dialog-note');const hasUser=group.some(isUserConversation),hasAssistant=group.some(item=>['助手','assistant'].includes(conversationRole(item))),hasSummary=group.some(isSummaryConversation);if(hasSummary&&!hasUser&&!hasAssistant)paragraph(root,'这是已保存摘要；原始问题与回答未收录。','conversation-gap');else if(!hasUser)paragraph(root,'未收录用户提问；以下仅显示已保存的助手或结果消息。','conversation-gap');else if(!hasAssistant)paragraph(root,'回答未收录；以下仅显示已保存的问题。','conversation-gap');
 const messages=el('div',undefined,'conversation-messages');for(const part of group){const role=conversationRole(part),roleClass=isUserConversation(part)?'user':isSummaryConversation(part)?'summary':['助手','assistant'].includes(role)?'assistant':'unknown',card=el('article',undefined,`conversation-message conversation-message-${roleClass}`);card.dataset.entryId=part.id;card.setAttribute('aria-current',String(part.id===entry.id));const head=el('div',undefined,'conversation-message-head');head.append(el('strong',isUserConversation(part)?'用户':isSummaryConversation(part)?'保存摘要':['助手','assistant'].includes(role)?'助手':part.role||'角色未注明'),el('span',conversationIdentityLabel(part),'meta'),el('span',`${part.date||'时间未收录'}${part.id===entry.id?' · 当前摘录':''}`,'meta'));const body=el('div',undefined,'conversation-message-body');renderMarkdown(part.text||'（该消息未保存正文。）',body,E.files[part.file_id]);card.append(head,body);messages.append(card);}root.append(messages);renderConversationModuleLinks(root,group,entry);
 const actions=el('div',undefined,'reading-links');const locator=[entry.source_title,entry.task_id?`任务 ID：${entry.task_id}`:'',entry.turn_id?`轮次 ID：${entry.turn_id}`:'',entry.message_id?`消息 ID：${entry.message_id}`:''].filter(Boolean).join('\n');const taskUrl=verifiedHttpsUrl(entry.original_url,entry.original_url_verified);if(taskUrl){const a=el('a','打开原任务','button primary');a.href=taskUrl;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);}else{actions.append(button('复制人工定位信息',event=>copy(locator||entry.source_title||'未记录的来源任务',event.currentTarget),'button primary'));actions.append(el('span','尚未提供已验证的原任务链接；请在原应用中按标题或任务 ID 查找。','note'));}if(entry.file_id&&E.files[entry.file_id])actions.append(button('打开完整摘录文件',()=>openFile(entry.file_id,{from:app,origin:{label:'已保存摘录',view:'conversation-entry',chapter:app.chapter,node:app.node},locator:entry.line?`L${entry.line}`:''}),'button'));
  const technical=disclosureDetails('来源定位信息',disclosureKey('conversation',entry.id,'source'),'technical-details');paragraph(technical,entry.source_title?`来源任务：${entry.source_title}`:'来源任务标题未记录','note');technical.append(actions);paragraph(technical,'身份：'+conversationIdentityLabel(entry),'note');paragraph(technical,'任务：'+(entry.task_id||entry.source_locator||'未记录'),'note');if(entry.turn_id)paragraph(technical,'轮次：'+entry.turn_id,'note');if(entry.message_id)paragraph(technical,'消息：'+entry.message_id,'note');if(entry.file_id)paragraph(technical,'摘录文件 '+(entry.line_range||`L${entry.line||'?'}`),'note');if(entry.coverage)paragraph(technical,'来源覆盖：'+entry.coverage,'note');technical.append(button('复制对话定位',event=>copy(locator,event.currentTarget),'button'));paragraph(technical,'原任务入口只使用数据记录提供且标记已验证的 HTTPS 地址。','note');root.append(technical);
  const neighbors=neighborEntries(entry);if(neighbors.length){const context=section(root,'同来源的前后片段');for(const other of neighbors){const row=el('div',undefined,'resource-line');paragraph(row,`${other.date||'时间未收录'} · ${other.role||'角色未注明'} · ${conversationIdentityLabel(other)}`,'note');paragraph(row,excerptSummary(other));row.append(button('查看此片段',()=>navigateToConversationEntry(other.id),'link-button'));context.append(row);}paragraph(context,'这些片段按同一摘录文件中的顺序排列；缺少的轮次不会补写。','note');}
 if(app.searchQuery)highlightTextMatch(root,app.searchQuery);
}
function setupConversations(){
 currentManualConversationProjectId();ensureManualConversationLinks();$('conversation-open').addEventListener('click',()=>navigateToConversationIndex(null,''));
}
