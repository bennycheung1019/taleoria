'use strict';
const $ = id => document.getElementById(id);
const uid = () => crypto.randomUUID();
let state, history = [], busy = false, intent = null, storyPending = false;
let activeTaskMetadata = null;
let actionComposing = false, actionCompositionEnded = -Infinity;
const pendingJobKey = 'taleoria_pending_generation';
let worldDraft = null, filePayload = null, selectedItem = null, toastTimer, selectedMapId = null, creationOptions = null;
const pages = ['adventure','character','world','people','bag','journal','create','settings'];
const itemDefaults = {hunting_knife:{name:'獵刀'},rain_cloak:{name:'雨斗篷'},rope:{name:'繩索'}};

function el(tag, className = '', text = '') {const node=document.createElement(tag);node.className=className;node.textContent=text;return node;}
function add(parent, tag, className, text) {const node=el(tag,className,text);parent.append(node);return node;}
function tags(parent, values) {const row=el('div','tags');for(const value of values)row.append(el('span','tag',value));parent.append(row);return row;}
function card(parent, title, text, cls='') {const node=el('article','reading-card '+cls);add(node,'h3','',title);if(text)add(node,'p','prose',text);parent.append(node);return node;}
function notify(text) {$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
function error(text) {$('pageNotice').textContent=text;$('pageNotice').hidden=false;}
function clearError() {$('pageNotice').hidden=true;}
function connectionInterrupted(e) {return e instanceof TypeError || ['TimeoutError','AbortError'].includes(e?.name) || e?.retryable === true;}
async function api(path, body, headers={}) {
  const response=await (window.TaleoriaConnection?.fetch||fetch)(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-RPG-Token':window.RPG_TOKEN,'X-RPG-Session':state?.session_id||'',...headers},body:body?JSON.stringify({...body,session_id:state?.session_id}):undefined});
  if([408,502,503,504].includes(response.status)){const e=Error('遊戲電腦連線暫時中斷，請稍後再試。');e.retryable=true;throw e;}
  let data;try{data=await response.json();}catch(e){if(connectionInterrupted(e))throw e;const incomplete=Error('連線回應不完整，請重新整理取回結果。');incomplete.retryable=true;throw incomplete;}
  if(!response.ok)throw Error(response.status===403?'頁面已更新，請重新整理後繼續。':(data.error||'這次操作沒有完成，請再試一次。'));
  return data;
}
function setBusy(value) {busy=value;document.querySelectorAll('[data-mutation], #useItem').forEach(b=>b.disabled=value);$('actionInput').disabled=value;$('sendAction').disabled=value||!state||!!state?.setup_required;if($('saveFile'))$('saveFile').disabled=value||!state||!!state?.setup_required;document.body.setAttribute('aria-busy',String(value));}

async function run(fn) {if(busy)return;clearError();setBusy(true);try{await fn();}catch(e){error(connectionInterrupted(e)?'與遊戲電腦的連線暫時中斷。進度已保留；請重新整理以取回結果。':e.message);}finally{setBusy(false);}}
function go(page) {if(location.hash==='#'+page)route();else location.hash=page;}
function route() {let page=location.hash.slice(1)||'adventure';if(!pages.includes(page))page='adventure';if(!state&&window.TaleoriaConnection?.needsPairing())page='settings';if(state?.setup_required&&!['create','settings'].includes(page))page='create';document.documentElement.dataset.page=page;$('cancelCreate').hidden=!!state?.setup_required;document.querySelector('.sidebar').hidden=!state||page==='create'||!!state?.setup_required;renderTaskLink();document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='page-'+page);document.querySelectorAll('[data-route]').forEach(a=>{a.classList.toggle('active',a.dataset.route===page);a.setAttribute('aria-current',a.dataset.route===page?'page':'false');});window.scrollTo({top:0,behavior:'instant'});}
function playerBackground() {return state.pc.background||`你目前確認的本領是${state.pc.capabilities.join('、')}。${state.pc.goal?'你的抱負：'+state.pc.goal+'。':''}`;}
function items() {return Object.entries(state.pc.inventory).filter(([,quantity])=>quantity>0).map(([id,quantity])=>({id,quantity,...(state.item_catalog?.[id]||itemDefaults[id]||{name:id.replaceAll('_',' ')})}));}
function powers() {const learned=state.pc.spells.map(id=>({id,...state.abilities[id]}));return [...learned,...(state.pc.known_powers||[]).filter(power=>!learned.some(item=>item.id===power.id))];}
function powerHint(node,power) {const text=[power.effect||power.description,power.limits?'限制：'+power.limits:''].filter(Boolean).join('\n')||'尚未記錄能力說明。';node.title=text;node.tabIndex=0;node.setAttribute('aria-label',power.name+'：'+text);return node;}
function title() {return state.contract.title||'一段未完的冒險';}
function renderProfile() {
  $('playerName').textContent=state.pc.name;$('playerRole').textContent=[state.pc.species,state.pc.role].filter(Boolean).join(' · ')||'自由旅人';
  $('portraitInitial').textContent=state.pc.name.trim().slice(0,1);$('sideLocation').textContent=state.locations[state.pc.location].name;
  const background=playerBackground();$('sideBackground').textContent=background.length>110?background.slice(0,110)+'…':background;
  $('sideSkills').replaceChildren();for(const skill of state.pc.capabilities)$('sideSkills').append(el('span','tag',skill));
  $('sidePowers').replaceChildren();if(!powers().length)add($('sidePowers'),'p','','尚未擁有超自然能力');for(const power of powers())powerHint(add($('sidePowers'),'div','power-line','✧ '+power.name),power);
  $('sideCondition').textContent=state.pc.alive?(state.pc.conditions.join('、')||'尚無已記錄的異常狀況'):'已死亡';
  $('bagCount').textContent=items().length+' 種物品';
  const sheet=$('characterSheet');sheet.replaceChildren();const profile=card(sheet,state.pc.name,playerBackground(),'wide character-intro');
  const portrait=el('button','character-portrait',state.pc.name.slice(0,1));portrait.type='button';portrait.dataset.mediaKind='portrait';portrait.dataset.mediaKey=state.pc.id;portrait.setAttribute('aria-label','查看'+state.pc.name+'的肖像');profile.prepend(portrait);
  card(sheet,'身分與願望',[state.pc.role,state.pc.species,state.pc.goal].filter(Boolean).join('\n'));
  card(sheet,'目前狀況',state.pc.alive?(state.pc.conditions.join('、')||'存活，尚無已記錄的異常。'):'已死亡。');
  const skills=card(sheet,'擅長的事','');tags(skills,state.pc.capabilities);
  const ability=card(sheet,'超自然能力','');if(!powers().length)add(ability,'p','subtle','尚未擁有。故事中的宣告不會自行賦予新能力。');
  for(const power of powers()){powerHint(add(ability,'h4','',power.name),power);add(ability,'p','prose',power.effect||power.description||'');}
  const goals=card(sheet,'隨身物品','');tags(goals,items().map(i=>i.name+' × '+i.quantity));
}
function renderTimeline(parent, rows, all=false) {parent.replaceChildren();const selected=all?rows:rows.slice(-6);if(!selected.length){add(parent,'p','empty-state','故事已準備好。描述你想做的事，踏出第一步。');return;}
  for(const row of selected){const turn=el('article','story-turn');turn.dataset.revision=String(row.revision);if(row.declaration)add(turn,'div','player-line',row.declaration);add(turn,'div','turn-caption',({approved:'故事',routine:'眼前所見',blocked:'這次嘗試',clarify:'尚待釐清',rewound:'回到較早的時刻',maintenance:'世界紀錄更新'}[row.status]||'故事'));add(turn,'div','prose',row.narration);if(row.narration&&row.status!=='maintenance'){const moment=add(turn,'div','turn-illustration','');moment.dataset.mediaKey=String(row.revision);add(moment,'div','turn-illustration-art','');}parent.append(turn);}
}
function renderAdventure() {$('adventureTitle').textContent=title();$('campaignGenre').textContent=state.contract.genre+' · '+(state.contract.play_form||'自由探索');$('sceneName').textContent=state.locations[state.pc.location].name;$('sceneDescription').textContent=state.locations[state.pc.location].description;document.querySelector('.scene-banner').dataset.mediaKey=state.pc.location;document.querySelector('.portrait').dataset.mediaKey=state.pc.id;$('chapterCount').textContent=history.length?'已留下 '+history.length+' 段記錄':'第一幕';renderTimeline($('storyTimeline'),history);renderTimeline($('journalTimeline'),history,true);}
function svgElement(tag,attributes={},text=''){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attributes))node.setAttribute(key,value);node.textContent=text;return node;}
function mapDetail(id){const node=state.atlas.nodes.find(n=>n.id===id);if(!node)return;selectedMapId=id;const panel=$('mapDetails');panel.replaceChildren();add(panel,'span','overline',node.current?'地點詳情':node.visited?'曾經抵達':'已知地點');add(panel,'div','map-place-symbol',/渡|船|港/.test(node.name)?'≋':'⌂');add(panel,'h3','',node.name);add(panel,'p','prose',node.description);const button=add(panel,'button',node.current||node.can_travel?'primary':'secondary',node.current?'回到冒險 →':'嘗試前往這裡 →');button.disabled=false;button.onclick=()=>{go('adventure');if(!node.current){$('actionInput').value='我前往'+node.name+'。';intent={kind:'travel',destination:node.id};$('actionInput').focus();}};document.querySelectorAll('.map-node').forEach(g=>g.classList.toggle('selected',g.dataset.locationId===id));}
function renderWorld(){const atlas=state.atlas||{nodes:[],links:[]},svg=$('worldMap');svg.replaceChildren();const defs=svgElement('defs');const marker=svgElement('marker',{id:'mapArrow',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'});marker.append(svgElement('path',{d:'M0 0L10 5L0 10Z',fill:'#8d9f7e'}));defs.append(marker);svg.append(defs);const nodes=new Map(atlas.nodes.map(n=>[n.id,n]));
for(const link of atlas.links){const a=nodes.get(link.from),b=nodes.get(link.to);if(!a||!b)continue;const middle=(a.x+b.x)/2;svg.append(svgElement('path',{d:`M${a.x} ${a.y} C${middle} ${a.y},${middle} ${b.y},${b.x} ${b.y}`,class:'map-route',...(link.two_way?{}:{'marker-end':'url(#mapArrow)'})}));}
for(const node of atlas.nodes){const group=svgElement('g',{transform:`translate(${node.x} ${node.y})`,class:'map-node '+(node.current?'current':node.visited?'visited':'known'),role:'button',tabindex:0,'aria-current':node.current?'location':'false','aria-label':'查看'+node.name+(node.current?'，目前位置':'')});group.dataset.locationId=node.id;group.append(svgElement('circle',{r:48,class:'map-halo'}));group.append(svgElement('circle',{r:33,class:'map-marker'}));group.append(svgElement('text',{y:9,'text-anchor':'middle',class:'map-symbol'},/渡|船|港/.test(node.name)?'≋':'⌂'));const pair=node.name.match(/^(.+?)[（(]([^）)]+)[）)]$/),label=svgElement('text',{y:67,'text-anchor':'middle',class:'map-label'},pair?pair[1]:node.name);if(pair)label.append(svgElement('tspan',{x:0,dy:23,class:'map-english'},'('+pair[2]+')'));group.append(label);group.onclick=()=>mapDetail(node.id);group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();mapDetail(node.id);}};svg.append(group);}
if(atlas.nodes.length)mapDetail(atlas.nodes.some(n=>n.id===selectedMapId)?selectedMapId:state.pc.location);}

function renderPeople(){
  const people=Object.values(state.people||{}),parent=$('peopleList');parent.replaceChildren();
  $('peopleCount').textContent=people.length+' 位已遇見的人';
  if(!people.length){add(parent,'p','empty-state','隨著冒險展開，你遇見的人會記錄在這裡。');return;}
  for(const person of people){
    const node=el('article','person-card'),heading=add(node,'div','person-heading','');
    const portrait=add(heading,'div','person-portrait',person.name.slice(0,1));portrait.dataset.mediaKind='portrait';portrait.dataset.mediaKey=person.id;
    const name=add(heading,'div','','');add(name,'h3','',person.name);
    add(node,'h4','','初次印象');add(node,'p','prose',person.description);
    parent.append(node);
  }
}
function renderBag() {$('inventoryGrid').replaceChildren();$('inventoryCount').textContent=items().length+' 種隨身物品';
  if(!items().length)add($('inventoryGrid'),'p','empty-state','目前沒有已記錄的隨身物品。');
  for(const item of items()){const entry=el('article','item-card');entry.dataset.mediaKind='item';entry.dataset.mediaKey=item.id;const button=add(entry,'button','item-open','');button.type='button';button.setAttribute('aria-label','查看'+item.name);const image=add(button,'div','item-image','◇');add(image,'small','','物品圖片');add(button,'span','item-count','× '+item.quantity);const caption=add(button,'div','item-caption','');add(caption,'h3','',item.name);button.onclick=()=>openItem(item);$('inventoryGrid').append(entry);}
  $('resourceList').replaceChildren();if(!Object.keys(state.pc.resources).length)add($('resourceList'),'p','subtle','沒有額外設定的數值資源。');for(const [name,value] of Object.entries(state.pc.resources))add($('resourceList'),'p','',name+'：'+value);
}
function openItem(item) {selectedItem=item;$('itemTitle').textContent=item.name;$('itemQuantity').textContent='持有數量：'+item.quantity;const image=$('itemDialog').querySelector('.item-image');image.dataset.mediaKind='item';image.dataset.mediaKey=item.id;$('itemDialog').showModal();document.dispatchEvent(new Event('taleoria:media'));}
let panelSignatures={};
function renderChangedPanels() {
  const groups=[
    ['profile',[state.pc,state.abilities,state.item_catalog,state.locations[state.pc.location]?.name],renderProfile],
    ['background',[state.world,state.contract,history.find(row=>row.status==='approved'&&!row.declaration)?.narration],renderWorldSheet],
    ['map',state.atlas,renderWorld],['people',Object.fromEntries(Object.entries(state.people||{}).map(([id,person])=>[id,{name:person.name,description:person.description}])),renderPeople],
    ['bag',[state.pc.inventory,state.pc.resources,Object.fromEntries(Object.entries(state.item_catalog||{}).map(([id,item])=>[id,item.name]))],renderBag]
  ];
  for(const [key,value,render] of groups){const signature=JSON.stringify([state.session_id,value]);if(panelSignatures[key]!==signature){render();panelSignatures[key]=signature;}}
}

function applyFrame(f) {if(!f)return;const previousLocation=state?.pc?.location;if(previousLocation!==f.pc.location&&(!selectedMapId||selectedMapId===previousLocation))selectedMapId=f.pc.location;state={...(state||{}),campaign_id:f.campaign_id,revision:f.revision,session_id:f.session_id,contract:f.contract,pc:{...(state?.pc||{}),...f.pc},locations:{...(state?.locations||{}),[f.pc.location]:{...f.scene,exits:{}}}};$('playerName').textContent=f.pc.name;$('portraitInitial').textContent=f.pc.name.slice(0,1);$('playerRole').textContent=[f.pc.species,f.pc.role].filter(Boolean).join(' · ');}
function renderPanels() {renderChangedPanels();$('autosaveText').textContent='已保存在這台電腦 · '+history.length+' 段記錄';document.dispatchEvent(new Event('taleoria:media'));}
async function load(preserveScroll=false) {const data=await api('/api/session');const oldSession=state?.session_id;history=data.history;state=data.state;renderAdventure();renderPanels();if(oldSession&&oldSession!==state.session_id){intent=null;worldDraft=null;selectedMapId=null;$('actionInput').value='';}setBusy(busy);if(state?.setup_required)go('create');else if(!preserveScroll)route();}
function scrollLatest() {if((location.hash.slice(1)||'adventure')!=='adventure')return;requestAnimationFrame(()=>{const panel=document.querySelector('#page-adventure .story-panel');if(!panel)return;const turn=$('storyTimeline').lastElementChild;const target=$('thinking').hidden?(turn?.querySelector('.player-line')||turn):$('thinking');if(target)panel.scrollTop=Math.max(0,panel.scrollTop+target.getBoundingClientRect().top-panel.getBoundingClientRect().top-panel.clientTop-16);});}
function progressView(parent) {parent.replaceChildren();const box=add(parent,'div','progress-display','');const head=add(box,'div','progress-heading','');const name=add(head,'strong','','準備中');const percent=add(head,'span','','0%（估計）');const bar=add(box,'progress','','');bar.max=100;bar.value=0;bar.setAttribute('aria-label','處理進度（估計）');const detail=add(box,'p','subtle','正在連接主持人…');return {name,percent,bar,detail};}
function savedJob() {try{return JSON.parse(sessionStorage.getItem(pendingJobKey+(window.TaleoriaConnection?.scope()||'')));}catch(e){return null;}}
function storeJob(value) {try{if(value)sessionStorage.setItem(pendingJobKey+(window.TaleoriaConnection?.scope()||''),JSON.stringify(value));else sessionStorage.removeItem(pendingJobKey+(window.TaleoriaConnection?.scope()||''));}catch(e){}}
function renderTaskLink(progress) {
  const button=$('activeTask');if(!activeTaskMetadata){button.hidden=true;return;}
  const world=activeTaskMetadata.path==='/api/world/draft',page=world?'create':'adventure';
  button.hidden=(location.hash.slice(1)||'adventure')===page;
  button.textContent=(world?'世界正在成形':'故事正在生成')+(progress?' · '+progress.percent+'%':'')+' · 查看進度';
}
async function trackedApi(path,body,parent) {
  const request=body.request_id||uid(),view=progressView(parent),started=Date.now();
  const metadata={path,body:{...body,request_id:request},session_id:state.session_id};
  activeTaskMetadata=metadata;storeJob(metadata);renderTaskLink();
  if(body.text)parent.prepend(el('div','sent-action player-line',body.text));
  const pause=()=>new Promise(resolve=>setTimeout(resolve,800));
  let settled=false;
  try {
    // Reusing this identifier after reload attaches to the same server task.
    for(;;){try{await api(path,metadata.body,{'Prefer':'respond-async'});break;}catch(e){if(!connectionInterrupted(e)) {settled=true;throw e;}view.detail.textContent='連線暫時中斷，正在重新連接同一次生成…';await pause();}}
    for(;;){
      let job;
      try{job=await api('/api/jobs?request_id='+encodeURIComponent(request));}
      catch(e){if(!connectionInterrupted(e)){settled=true;throw e;}view.detail.textContent='連線暫時中斷，生成會在伺服器繼續；正在重新連接…';await pause();continue;}
      const p=job.progress;
      view.name.textContent=p.stage+' · '+p.phase;view.percent.textContent=p.percent+'%'+(p.estimated?'（估計）':'');view.bar.value=p.percent;renderTaskLink(p);
      let detail='已等待 '+Math.max(p.elapsed_seconds,Math.floor((Date.now()-started)/1000))+' 秒';
      if(p.stage_remaining_upper_seconds!=null&&p.status==='running')detail+=' · 本階段依輸出上限最長約 '+Math.ceil(p.stage_remaining_upper_seconds/60)+' 分鐘，可能提早完成';
      view.detail.textContent=detail;
      if(job.status!=='running'){
        settled=true;
        if(job.status==='error')throw Error(job.result.error||'這次生成沒有完成。');
        view.percent.textContent='100%';view.bar.value=100;return job.result;
      }
      await pause();
    }
  } finally {if(settled)storeJob(null);activeTaskMetadata=null;renderTaskLink();}
}
async function sendText(play,resume=null) {if(!resume&&!play?.text?.trim())throw Error('先寫下你想做的事。');storyPending=true;$('itemDialog').close();$('thinking').hidden=false;$('actionInput').value='';intent=null;scrollLatest();try{const result=await trackedApi('/api/play',resume?.body||{text:play.text,intent:play.intent,revision:state.revision,request_id:uid()},$('thinking'));storyPending=false;applyFrame(result.frame);if(result.panel_snapshot)state=result.panel_snapshot;if(!history.some(row=>row.revision===result.turn.revision))history.push(result.turn);renderAdventure();renderPanels();$('thinking').hidden=true;scrollLatest();if((location.hash.slice(1)||'adventure')!=='adventure')notify('新一段故事已完成，可以回到冒險閱讀。');}catch(e){storyPending=false;await load(true).catch(()=>{});throw e;}finally{storyPending=false;$('thinking').hidden=true;scrollLatest();}}

function applyReadingPreferences(theme,size) {theme=['light','dark'].includes(theme)?theme:'light';size=['small','medium','large'].includes(size)?size:'medium';document.documentElement.dataset.theme=theme;document.documentElement.dataset.textSize=size;$('themeSelect').value=theme;$('textSizeSelect').value=size;try{localStorage.setItem('rpg_theme',theme);localStorage.setItem('rpg_text_size',size);}catch(e){}}

function resetWorldForm() {worldDraft=null;$('worldPreview').hidden=true;$('worldForm').hidden=false;$('worldThinking').hidden=true;$('stepPreferences').classList.add('active');$('stepPreview').classList.remove('active');}
function startWorld() {if(busy)return;if(!worldDraft)resetWorldForm();go('create');}
function worldPrefs(){return {genre:$('worldGenre').value,difficulty:$('worldDifficulty').value,player_name:$('worldPlayerName').value,player_background:$('worldPlayerBackground').value,wishes:$('worldWishes').value,permadeath:$('worldPermadeath').checked};}
function showWorldPreview(result) {worldDraft=result;const p=result.plan;$('previewTitle').textContent=p.title;$('previewBackground').textContent=p.background;$('previewOpening').textContent=p.opening;$('previewRules').replaceChildren();for(const rule of p.rules)add($('previewRules'),'li','',rule);const player=$('previewCharacter');player.replaceChildren();add(player,'span','overline','你將扮演');add(player,'h3','',p.player.name+' · '+p.player.role);add(player,'p','prose',p.player.background);add(player,'p','subtle','願望：'+p.player.goal);tags(player,p.player.skills);for(const power of p.player.powers){add(player,'h4','',power.name);add(player,'p','prose',power.effect+'；限制：'+power.limits);}if(!p.player.powers.length)add(player,'p','subtle','起始沒有超自然能力。');add(player,'p','subtle','隨身物品：'+(p.player.items.map(i=>i.name).join('、')||'無'));add(player,'p','subtle','第一位在場人物：'+p.npc.name+' · '+p.npc.description);$('worldForm').hidden=true;$('worldPreview').hidden=false;$('stepPreferences').classList.remove('active');$('stepPreview').classList.add('active');if(location.hash==='#create')window.scrollTo({top:0,behavior:'smooth'});}
async function connection() {try{const data=await api('/api/connection');$('connectionText').textContent=data.connected?'主持人已就緒':'主持人尚未連接';$('connectionDot').classList.toggle('ready',data.connected);$('modelDetails').textContent=data.connected?'目前使用：'+data.model:'請先在遊戲電腦啟動 KoboldCpp，再重新連接。';if(document.activeElement!==$('modelUrl'))$('modelUrl').value=data.model_url;}catch(e){$('connectionText').textContent='暫時無法連接主持人';}}
async function loadCreationOptions(){creationOptions=await api('/api/creation-options');updateCreationHelp();if(state?.pc?.inventory)renderWorldSheet();}
function updateCreationHelp(){const profile=creationOptions?.story_types[$('worldGenre').value];$('genreHelp').textContent=profile?'題材預設：'+profile.tone+'；'+profile.magic+'。可在故事描述中另作設定。':'';const level=creationOptions?.difficulties[$('worldDifficulty').value];$('difficultyHelp').textContent=level?.description||'';}
function renderWorldSheet() {
  if(!state?.world && !state?.locations?.[state.pc.location])return;
  $('sideWorldName').textContent=title();
  $('sideWorldGenre').textContent=[state.contract.genre,state.contract.play_form].filter(Boolean).join(' · ');
  const opening=history.find(row=>row.status==='approved'&&!row.declaration)?.narration;
  const background=state.world?.background||`這是一個${state.contract.genre}的世界，故事以${state.contract.play_form||'自由探索'}展開。\n\n${opening||state.locations[state.pc.location].description}\n\n尚未接觸的地方與往事，將隨著探索逐漸揭開。`;
  $('sideWorldBackground').replaceChildren();
  for(const paragraph of background.split(/\n\s*\n|\n/).filter(Boolean))add($('sideWorldBackground'),'p','',paragraph);
  const key={Hard:'困難',Normal:'一般','故事體驗':'以故事體驗為主'}[state.contract.difficulty]||state.contract.difficulty;
  const level=creationOptions?.difficulties[key],panel=$('sideWorldInfo');panel.replaceChildren();
  const settings=add(panel,'dl','world-settings','');
  for(const [name,value] of [['挑戰程度',level?.label||key],['永久死亡',state.contract.permadeath?'開啟':'未開啟']]){
    const row=add(settings,'div','','');add(row,'dt','',name);add(row,'dd','',value);
  }
  add(panel,'h3','','挑戰與後果');
  add(panel,'p','',level?.description||state.contract.difficulty_guidance||'依已建立的背景、資源與危險裁定。');
  add(panel,'p','',state.contract.permadeath?'角色死亡後，不能在這條故事線復活。你仍可載入之前的存檔重新開始。':'不預先指定永久死亡；後果仍依世界規則與已建立的情境處理。');
  if(state.world?.rules?.length){add(panel,'h3','','世界的法則');for(const rule of state.world.rules)add(panel,'p','',rule);}
  add(panel,'p','world-agency','你決定角色的行動與台詞；身分與能力先建立，後裁定。難度不會臨時改寫已定事實。');
}
function setSheetTab(name,focus=false) {
  for(const [value,id,panel] of [['character','characterTab','characterPanel'],['world','worldTab','worldSheet']]){
    const active=value===name,button=$(id);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;$(panel).hidden=!active;
    if(active&&focus)button.focus();
  }
}

async function downloadSave(){const response=await (window.TaleoriaConnection?.fetch||fetch)('/api/save-file',{headers:{'X-RPG-Token':window.RPG_TOKEN,'X-RPG-Session':state.session_id}});const data=await response.json();if(!response.ok)throw Error(data.error||'存檔未完成。');const url=URL.createObjectURL(new Blob([JSON.stringify(data)],{type:'application/json'}));const link=el('a');link.href=url;link.download=title().replace(/[\\/:*?"<>|]/g,'_')+'-'+new Date().toISOString().replace(/[:.]/g,'-')+'.rpgsave';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('完整存檔已下載到電腦（.rpgsave）。');}
async function chooseSave(file){if(!file)return;if(file.size>16*1024*1024)throw Error('目前支援 16 MB 以內的遊戲存檔。');let data;try{data=JSON.parse(await file.text());}catch(e){throw Error('無法讀取這份檔案，請選擇 .rpgsave 遊戲檔。');}if(data?.format!=='kobold-rpg-save'||data?.version!==1||!data.state?.pc)throw Error('這不是完整的 RPG 存檔，請選擇新的 .rpgsave 遊戲檔。');filePayload=data;$('fileLoadTitle').textContent=typeof data.state.contract?.title==='string'?data.state.contract.title:'載入冒險';$('fileLoadDescription').textContent=String(data.state.pc.name||'角色')+' · '+String(data.state.locations?.[data.state.pc.location]?.name||'未知地點');$('fileLoadError').textContent='';$('fileLoadDialog').showModal();}
function setCollapsed(collapsed) {if(collapsed)setSheetTab('character');document.body.classList.toggle('compact',collapsed);$('toggleSheet').textContent=collapsed?'›':'‹';$('toggleSheet').setAttribute('aria-expanded',String(!collapsed));$('toggleSheet').setAttribute('aria-label',collapsed?'展開側欄':'收合側欄');$('toggleSheet').title=collapsed?'展開側欄':'收合側欄';try{localStorage.setItem('rpg_sheet_collapsed',String(collapsed));}catch(e){}}

window.addEventListener('hashchange',route);$('pageNotice').onclick=clearError;
$('activeTask').onclick=()=>{if(activeTaskMetadata)go(activeTaskMetadata.path==='/api/world/draft'?'create':'adventure');};
$('toggleSheet').onclick=()=>setCollapsed(!document.body.classList.contains('compact'));
for(const [id,name] of [['characterTab','character'],['worldTab','world']]){
  $(id).onclick=()=>setSheetTab(name);
  $(id).onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();setSheetTab(e.key==='Home'?'character':e.key==='End'?'world':name==='world'?'character':'world',true);}};
}

for(const id of ['openCharacter','readCharacter'])$(id).onclick=()=>go('character');$('openBag').onclick=()=>go('bag');$('openSettings').onclick=()=>go('settings');$('newWorld').onclick=startWorld;$('cancelCreate').onclick=()=>go('adventure');
$('actionInput').addEventListener('input',()=>{intent=null;});$('sendAction').onclick=()=>run(()=>sendText({text:$('actionInput').value,intent}));
$('actionInput').addEventListener('compositionstart',()=>{actionComposing=true;});
$('actionInput').addEventListener('compositionend',e=>{actionComposing=false;actionCompositionEnded=e.timeStamp;});
function handleActionKeydown(e) {
  if(e.key!=='Enter'||e.shiftKey||e.altKey||e.isComposing||e.keyCode===229||actionComposing)return;
  if(e.timeStamp>=actionCompositionEnded&&e.timeStamp-actionCompositionEnded<50)return;
  e.preventDefault();
  if(!e.repeat&&!$('sendAction').disabled&&$('actionInput').value.trim())$('sendAction').click();
}
$('actionInput').onkeydown=handleActionKeydown;
$('saveFile').onclick=()=>run(downloadSave);$('loadFile').onclick=()=>{if(!busy)$('saveFileInput').click();};$('saveFileInput').onchange=()=>{const file=$('saveFileInput').files[0];$('saveFileInput').value='';run(()=>chooseSave(file));};$('cancelFileLoad').onclick=()=>{if(!busy){filePayload=null;$('fileLoadDialog').close();clearError();}};$('confirmFileLoad').onclick=()=>run(async()=>{if(!filePayload)return;try{await api('/api/import-file',{save:filePayload});}catch(e){$('fileLoadError').textContent=e.message;throw e;}$('fileLoadDialog').close();filePayload=null;resetWorldForm();await load();go('adventure');notify('存檔已載入，從這一刻繼續。');});
$('worldGenre').onchange=updateCreationHelp;$('worldDifficulty').onchange=updateCreationHelp;
$('worldInspiration').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('worldGenre').value=b.dataset.genre;updateCreationHelp();});
async function createWorldDraft(resume=null) {
  if(resume){const p=resume.body.preferences;for(const [id,key] of [['worldGenre','genre'],['worldDifficulty','difficulty'],['worldPlayerName','player_name'],['worldPlayerBackground','player_background'],['worldWishes','wishes']])$(id).value=p[key]||'';$('worldPermadeath').checked=!!p.permadeath;updateCreationHelp();}
  $('worldThinking').hidden=false;$('worldForm').hidden=true;$('worldPreview').hidden=true;
  try {
    if(location.hash==='#create')$('worldThinking').scrollIntoView({block:'nearest'});
    showWorldPreview(await trackedApi('/api/world/draft',resume?.body||{preferences:worldPrefs()},$('worldThinking')));
    if(location.hash!=='#create')notify('新世界草案已完成，回到建立世界即可預覽。');
  } catch(e){$('worldForm').hidden=false;throw e;}
  finally{$('worldThinking').hidden=true;}
}
$('worldForm').onsubmit=e=>{e.preventDefault();run(()=>createWorldDraft());};
$('editWorld').onclick=resetWorldForm;$('confirmWorld').onclick=()=>run(async()=>{if(!worldDraft)return;await api('/api/world/create',{preview_id:worldDraft.preview_id});resetWorldForm();await load();go('adventure');notify('新世界已建立。你的冒險開始了。');});
$('closeItem').onclick=()=>$('itemDialog').close();$('useItem').onclick=()=>{if(!selectedItem||busy)return;$('itemDialog').close();go('adventure');$('actionInput').value='我使用'+selectedItem.name+'，';intent={kind:'use_item',item:selectedItem.id};$('actionInput').focus();};
$('refreshConnection').onclick=()=>connection();
$('themeSelect').onchange=$('textSizeSelect').onchange=()=>applyReadingPreferences($('themeSelect').value,$('textSizeSelect').value);
applyReadingPreferences(document.documentElement.dataset.theme,document.documentElement.dataset.textSize);
try{setCollapsed(localStorage.getItem('rpg_sheet_collapsed')==='true');}catch(e){}
route();
async function startGame(){await load();await connection();await loadCreationOptions();
  await (async()=>{
  const pending=savedJob();
  if(!pending)return;
  if(pending.session_id!==state.session_id){storeJob(null);notify('遊戲服務已更新，請確認目前故事進度後繼續。');return;}
  if(!['/api/play','/api/world/draft'].includes(pending.path)){storeJob(null);return;}
  await run(()=>pending.path==='/api/play'?sendText(null,pending):createWorldDraft(pending));
})();}
initializeConnection().catch(e=>error(e.message));

async function initializeConnection(){
  const transport=window.TaleoriaConnection;
  if(transport)await transport.ready;
  const config=transport?.get()||{companion_url:location.origin,key:'',model_url:'http://127.0.0.1:5001'};
  $('companionUrl').value=config.companion_url;$('companionKey').value=config.key;$('modelUrl').value=config.model_url;
  $('pairingKeyLabel').hidden=!!transport?.isLocal;
  $('saveConnection').onclick=async()=>{
    const button=$('saveConnection');if(busy)return;button.disabled=true;clearError();
    try{
      const selected={companion_url:$('companionUrl').value.trim(),key:$('companionKey').value.trim(),model_url:$('modelUrl').value.trim()};
      if(transport?.isLocal&&transport.endpoint(selected.companion_url)!==location.origin)throw Error('切換另一部電腦，請在 Vercel 網站的設定操作。');
      const headers={'X-RPG-Token':window.RPG_TOKEN,'Content-Type':'application/json'};
      const response=await transport.fetch('/api/session',{headers},selected);
      const data=await response.json();if(!response.ok)throw Error(data.error||'未能連接遊戲電腦。');
      const session=(data.state||data.panel_snapshot)?.session_id||data.frame?.session_id;
      const changed=await transport.fetch('/api/connection/settings',{method:'POST',headers:{...headers,'X-RPG-Session':session},body:JSON.stringify({session_id:session,model_url:selected.model_url})},selected);
      const saved=await changed.json();if(!changed.ok)throw Error(saved.error||'模型設定未能儲存。');
      transport.save(selected);
      await load();await connection();await loadCreationOptions();
      $('autosaveText').textContent='已保存在遊戲電腦';notify('連線已儲存。');go('settings');
    }catch(e){$('modelDetails').textContent=e instanceof TypeError?'無法連接：確認遊戲電腦已開啟、網址正確及已允許此網站。':e.message;}
    finally{button.disabled=false;go('settings');}
  };
  if(transport?.needsPairing()){
    go('settings');for(const id of ['saveFile','loadFile','newWorld','sendAction'])$(id).disabled=true;$('connectionText').textContent='請先配對遊戲電腦';$('modelDetails').textContent='填入這部電腦的配對碼後，按「儲存並連線」。';return;
  }
  try{await startGame();}catch(e){go('settings');$('modelDetails').textContent='無法連接遊戲電腦，請檢查網址與配對碼。';}
  if(transport?.isLocal){
    try{
      const data=await api('/api/companion/pairing');$('localPairing').hidden=false;$('localPairingKey').value=data.key;$('localRemoteUrl').value=data.remote?.status==='running'?data.remote.url:'';
      $('trustedWebsite').value=data.allowed_origins[0]||'';$('pairingStatus').textContent=data.allowed_origins.join('、');
      $('showPairing').onclick=()=>{$('localPairingKey').type=$('localPairingKey').type==='password'?'text':'password';};
      $('allowWebsite').onclick=async()=>{try{const result=await api('/api/companion/pairing',{website:$('trustedWebsite').value.trim()});$('pairingStatus').textContent='已允許：'+result.allowed_origins.join('、');}catch(e){$('pairingStatus').textContent=e.message;}};
    }catch(e){}
  }
}
