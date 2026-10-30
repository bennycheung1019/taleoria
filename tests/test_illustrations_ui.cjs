/* Small DOM harness for image delivery, scope isolation and modal interactions. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.className='';this.textContent='';this.hidden=false;this.disabled=false;this.value='';this.listeners={};this.open=false;}
  append(...nodes){for(const n of nodes){n.remove();n.parentNode=this;this.children.push(n);}}
  prepend(n){n.remove();n.parentNode=this;this.children.unshift(n);}
  before(n){const p=this.parentNode;n.remove();n.parentNode=p;p.children.splice(p.children.indexOf(this),0,n);}
  replaceWith(n){this.before(n);this.remove();}
  replaceChildren(...nodes){for(const n of this.children)n.parentNode=null;this.children=[];this.append(...nodes);}
  remove(){if(this.parentNode){const p=this.parentNode;p.children.splice(p.children.indexOf(this),1);this.parentNode=null;}}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];if(k==='src')delete this.src;}
  get classList(){const n=this;return{contains(c){return n.className.split(' ').includes(c);},add(c){if(!this.contains(c))n.className+=' '+c;},remove(c){n.className=n.className.split(' ').filter(x=>x!==c).join(' ');},toggle(c,on){if(on)this.add(c);else this.remove(c);}};}
  matches(selector){return selector.split(',').some(s=>{const parts=s.trim().split(/\s+/),last=parts.pop();if(!this.simple(last))return false;let p=this.parentNode;while(parts.length){const needle=parts.pop();while(p&&!p.simple(needle))p=p.parentNode;if(!p)return false;p=p.parentNode;}return true;});}
  simple(s){if(!s)return false;const tag=s.match(/^[\w-]+/)?.[0];if(tag&&tag!==this.tagName)return false;const id=s.match(/#([\w-]+)/)?.[1];if(id&&id!==this.id)return false;for(const c of s.matchAll(/\.([\w-]+)/g))if(!this.classList.contains(c[1]))return false;for(const a of s.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)){const key=a[1].startsWith('data-')?a[1].slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()):null;const v=key?this.dataset[key]:this.attributes[a[1]];if(v===undefined||(a[2]!==undefined&&v!==a[2]))return false;}return true;}
  querySelectorAll(s){return this.children.flatMap(n=>[...(n.matches(s)?[n]:[]),...n.querySelectorAll(s)]);}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  closest(s){return this.matches(s)?this:this.parentNode?.closest(s);}
  contains(n){return this===n||this.children.some(c=>c.contains(n));}
  get isConnected(){return this===body||Boolean(this.parentNode?.isConnected);}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  showModal(){this.open=true;}
  close(){if(!this.open)return;this.open=false;for(const fn of this.listeners.close||[])fn({target:this});}
}
const body=new Element('body'),add=(p,t,c='')=>{const n=new Element(t);n.className=c;p.append(n);return n;};
const banner=add(body,'div','scene-banner');add(banner,'div','scene-art');add(banner,'span','image-reserved');
const sidebar=add(body,'div','character-panel'),avatar=add(sidebar,'button','portrait');
const sheet=add(body,'article','character-intro');add(sheet,'button','character-portrait');
let heading=add(body,'div','person-heading'),portrait=add(heading,'div','person-portrait');portrait.dataset.mediaKey='hark';
const bag=add(body,'article','item-card');bag.dataset.mediaKey='hunting_knife';add(bag,'div','item-image');
const itemDialog=add(body,'dialog');itemDialog.id='itemDialog';const itemImage=add(itemDialog,'div','item-image');itemImage.dataset.mediaKey='hunting_knife';
const moment=add(body,'div','turn-illustration');moment.dataset.mediaKey='1';const momentArt=add(moment,'div','turn-illustration-art');
const settings=add(body,'section');settings.id='page-settings';
const timers=[],requests=[],revoked=[],listeners={};
let data={campaign_id:'campaign',revision:0,session_id:'session',moments:[{subject:'1',name:'第一段故事',fingerprint:'moment-one'}],scene:{subject:'gate',name:'Gate',fingerprint:'scene-one'},characters:[{id:'ben',name:'Ben',fingerprint:'ben-one'},{id:'hark',name:'Hark',fingerprint:'hark-one'}],items:[{id:'hunting_knife',name:'Knife',fingerprint:'knife-one'}],images:[],settings:{endpoint:'http://127.0.0.1:7860',style:'painterly'}};
const document={body,hidden:false,activeElement:null,createElement:t=>new Element(t),createElementNS:(ns,t)=>{const n=new Element(t);n.namespaceURI=ns;return n;},getElementById:id=>body.querySelector('#'+id),querySelectorAll:s=>body.querySelectorAll(s),querySelector:s=>body.querySelector(s),addEventListener:(k,fn)=>listeners[k]=fn};
let fail=false;
const context=vm.createContext({document,window:{RPG_TOKEN:'token',addEventListener:(k,fn)=>listeners[k]=fn},state:{session_id:'session',campaign_id:'campaign',revision:0,pc:{id:'ben',location:'gate'}},busy:false,syncing:false,crypto:{randomUUID:()=> 'request-image-one'},setInterval:fn=>timers.push(fn),URL:{createObjectURL:()=> 'blob:image-'+Math.random(),revokeObjectURL:u=>revoked.push(u)},fetch:async(url,options)=>{requests.push({url,options});if(fail&&url.endsWith('/generate'))return{ok:false,json:async()=>({error:'Draw Things unavailable'})};return{ok:true,json:async()=>{if(url.endsWith('/generate')){const payload=JSON.parse(options.body),info=payload.kind==='moment'?data.moments.find(x=>x.subject===payload.subject):payload.kind==='scene'?data.scene:(payload.kind==='portrait'?data.characters:data.items).find(x=>x.id===payload.subject);const row={id:'image-'+requests.length,kind:payload.kind,subject:payload.subject,fingerprint:info.fingerprint,status:'generating',name:info.name,url:null};data.images.unshift(row);return row;}return structuredClone(data);},blob:async()=>({})};}});
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));};
const click=b=>{assert.equal(b.disabled,false);return b.onclick({stopPropagation(){}});};
const countGenerate=()=>requests.filter(r=>r.url.endsWith('/generate')).length;
const finish=async()=>{await settle();const row=data.images[0];row.status='done';row.url='/api/illustrations/image/'+row.id;timers[0]();await settle();};
(async()=>{
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../illustrations.js'),'utf8'),context);await settle();
 assert.equal(body.querySelector('.illustration-panel'),null,'no standalone image panel');
 for(const host of [banner,avatar.parentNode,heading,bag,itemDialog,moment])assert.ok(host.querySelector('.media-generate'));
 for(const button of body.querySelectorAll('.media-generate'))assert.ok(button.title,'every image generation control has a hover title');
 assert.equal(banner.querySelector('.media-view').disabled,true);
 assert.equal(requests[0].options.headers['X-RPG-Token'],'token');
 await click(banner.querySelector('.media-generate'));await settle();
 assert.equal(countGenerate(),1);assert.equal(bag.querySelector('.media-generate').disabled,true);
 assert.equal(banner.querySelector('.media-generate').attributes['aria-busy'],'true');
 await finish();assert.ok(banner.querySelector('img.illustration-cover'));
 await click(banner.querySelector('.media-view'));await settle();
 const viewer=body.querySelector('.media-viewer');assert.equal(viewer.open,true);assert.equal(viewer.querySelector('h2').textContent,'Gate');assert.equal(viewer.querySelector('img').hidden,false);
 viewer.close();assert.equal(viewer.open,false);
 await click(bag.querySelector('.media-generate'));await finish();
 assert.equal(JSON.parse(requests.filter(r=>r.url.endsWith('/generate')).at(-1).options.body).kind,'item');assert.ok(bag.querySelector('img'));assert.ok(itemImage.querySelector('img'));
 await click(bag.querySelector('.media-view'));await settle();assert.equal(viewer.querySelector('h2').textContent,'Knife');viewer.close();
 await click(heading.querySelector('.media-generate'));await finish();assert.ok(portrait.querySelector('img'));
 const before=countGenerate();await click(portrait);await settle();assert.equal(countGenerate(),before,'view never regenerates');assert.equal(viewer.querySelector('h2').textContent,'Hark');
 fail=true;await click(viewer.querySelector('.secondary'));await settle();assert.ok(portrait.querySelector('img'),'failed regeneration retains prior image');fail=false;
 // Rebuilt character cards get controls and cached art without new generation.
 heading.remove();heading=add(body,'div','person-heading');portrait=add(heading,'div','person-portrait');portrait.dataset.mediaKey='hark';listeners['taleoria:media']();await settle();assert.ok(heading.querySelector('.media-view'));assert.ok(portrait.querySelector('img'));assert.equal(countGenerate(),before+1);
 await click(moment.querySelector('.media-generate'));await finish();assert.equal(JSON.parse(requests.filter(r=>r.url.endsWith('/generate')).at(-1).options.body).subject,'1');assert.equal(momentArt.hidden,false);assert.ok(momentArt.querySelector('img'));await click(moment.querySelector('.media-view'));await settle();assert.equal(viewer.querySelector('h2').textContent,'第一段故事');assert.ok(viewer.querySelector('.secondary').title);viewer.close();
 // A changed appearance invalidates old decoration and closes an ineligible viewer.
 data={...data,revision:1,characters:data.characters.map(p=>p.id==='hark'?{...p,fingerprint:'hark-two'}:p),items:[]};context.state={...context.state,revision:1};timers[0]();await settle();assert.equal(portrait.querySelector('img'),null);assert.equal(bag.querySelector('img'),null);assert.equal(heading.querySelector('.media-view').disabled,true);
 context.state={session_id:'new',campaign_id:'other',revision:0,pc:{id:'ben',location:'gate'}};data={...data,session_id:'new',campaign_id:'other',revision:0,images:[]};timers[0]();await settle();assert.equal(viewer.open,false);assert.equal(banner.querySelector('img'),null);assert.ok(revoked.length>=3);
 assert.equal(body.querySelector('.illustration-panel'),null);
 console.log('Integrated images: in-place controls, scene/portrait/item delivery, modal viewing without generation, async status, duplicate prevention, regeneration failure, rebuilt cards, stale appearance and campaign cleanup passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
