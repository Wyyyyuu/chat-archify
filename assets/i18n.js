'use strict';
// Only authored interface strings are translated. Source data never enters
// this catalog, and locale changes do not rewrite embedded files or records.
(function(root){
  const normalize=value=>value==='en'?'en':value==='zh'||value==='zh-CN'?'zh-CN':null;
  const read=id=>{try{return JSON.parse(document.getElementById(id)?.textContent||'{}');}catch{return {};}};
  const catalog=read('locale-data'),payload=read('explorer-data');
  const location=typeof globalThis.location==='object'?globalThis.location:{};
  const storageKey='chat-archify:language:'+String(location.pathname||payload.project_id||payload.title||'viewer');
  let stored=null;try{stored=localStorage.getItem(storageKey);}catch{}
  let requested=null;try{requested=new URLSearchParams(location.hash?.slice(1)||'').get('lang');}catch{}
  let language=normalize(requested)||normalize(stored)||normalize(payload.locale)||'zh-CN';
  const listeners=new Set();
  function t(key,...values){
    const text=language==='en'&&Object.prototype.hasOwnProperty.call(catalog,key)?catalog[key]:key;
    return String(text).replace(/\{(\d+)\}/g,(match,index)=>index<values.length?String(values[index]):match);
  }
  function applyStatic(){
    if(typeof document==='undefined')return;
    document.documentElement?.setAttribute('lang',language);
    for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=t(node.getAttribute('data-i18n'));
    for(const attr of ['aria-label','title','placeholder']){
      for(const node of document.querySelectorAll('[data-i18n-'+attr+']'))node.setAttribute(attr,t(node.getAttribute('data-i18n-'+attr)));
    }
    const selector=document.getElementById('language-select');if(selector)selector.value=language;
  }
  function setLanguage(value){
    const next=normalize(value);if(!next)return false;
    if(next===language){applyStatic();return true;}
    language=next;try{localStorage.setItem(storageKey,next);}catch{}
    applyStatic();for(const listener of listeners)listener(next);return true;
  }
  function bind(){
    applyStatic();const selector=document.getElementById('language-select');
    if(selector&&!selector.dataset.languageBound){selector.dataset.languageBound='1';selector.addEventListener('change',()=>setLanguage(selector.value));}
  }
  const api={t,setLanguage,applyStatic,bind,get language(){return language;},onChange(fn){listeners.add(fn);return ()=>listeners.delete(fn);}};
  root.ChatArchifyI18n=api;if(typeof globalThis!=='undefined')globalThis.ChatArchifyI18n=api;
})(typeof window!=='undefined'?window:globalThis);
