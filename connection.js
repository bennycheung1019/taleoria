/* Browser-to-companion transport. Credentials never enter a URL or build file. */
(() => {
  'use strict';
  const local = window.RPG_TOKEN && !['HOSTED_COMPANION','__SESSION_TOKEN__'].includes(window.RPG_TOKEN);
  const storageKey='taleoria_companion_v1';
  const nativeFetch=window.fetch.bind(window);
  let profile={companion_url:local?location.origin:'http://127.0.0.1:8787',key:'',model_url:'http://127.0.0.1:5001'};
  function endpoint(value){
    let url;try{url=new URL(value);}catch(e){throw Error('請填入完整的遊戲電腦網址。');}
    const loopback=['127.0.0.1','localhost','[::1]'].includes(url.hostname);
    if(!['http:','https:'].includes(url.protocol)||(!loopback&&url.protocol!=='https:')||url.username||url.password||url.search||url.hash||!['','/'].includes(url.pathname))throw Error('遠端電腦請使用 HTTPS 網址；本機可用 http://127.0.0.1:8787。');
    return url.origin;
  }
  function needsPairing(){return !local&&!profile.key;}
  async function request(path,options={},selected=profile){
    if(typeof path!=='string'||!path.startsWith('/api/'))throw Error('不支援的遊戲請求。');
    const base=endpoint(selected.companion_url);
    const same=local&&base===location.origin;
    if(!same&&!selected.key)throw Error('請先在設定輸入遊戲電腦的網址與配對碼。');
    const headers=new Headers(options.headers||{});
    if(!same)headers.set('X-Taleoria-Key',selected.key);
    const timeout=AbortSignal.timeout?AbortSignal.timeout(20000):undefined;
    return nativeFetch(base+path,{...options,headers,credentials:'omit',referrerPolicy:'no-referrer',signal:options.signal||timeout});
  }
  const ready=(async()=>{
    if(!local){
      try{const response=await nativeFetch('/deployment.json',{cache:'no-store'});if(response.ok){const defaults=await response.json();profile.companion_url=endpoint(defaults.companion_url);profile.model_url=defaults.model_url||profile.model_url;}}catch(e){}
      try{const saved=JSON.parse(localStorage.getItem(storageKey));if(saved&&saved.companion_url){profile={...profile,...saved,companion_url:endpoint(saved.companion_url)};}}catch(e){}
    }
    return profile;
  })();
  function save(value){profile={companion_url:endpoint(value.companion_url),key:value.key||'',model_url:value.model_url};if(!local)localStorage.setItem(storageKey,JSON.stringify(profile));}
  window.TaleoriaConnection={ready,fetch:request,endpoint,save,needsPairing,isLocal:local,get:()=>({...profile}),scope:()=>profile.companion_url};
})();
