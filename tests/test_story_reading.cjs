const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
const interrupted=source.match(/^function connectionInterrupted.*$/m)[0];
const tracked=source.match(/async function trackedApi\([\s\S]*?(?=\nasync function sendText)/)[0];
(async()=>{
 const calls=[],saved=[],view={name:{},percent:{},bar:{},detail:{}};
 let submit=0,polls=0;
 const context=vm.createContext({TypeError,Error,Date,encodeURIComponent,state:{session_id:'session'},activeTaskMetadata:null,
  uid:()=> 'same-request',progressView:()=>view,storeJob:v=>saved.push(v),renderTaskLink(){},el:()=>({}),
  setTimeout:fn=>{fn();},api:async(path,body)=>{calls.push({path,body});if(path==='/api/play'){if(++submit===1)throw Object.assign(new Error('signal timed out'),{name:'TimeoutError'});return{};}
   if(++polls===1)throw Object.assign(new Error('body aborted'),{name:'AbortError'});
   if(polls===2)throw Object.assign(new Error('gateway timeout'),{retryable:true});
   return{status:'done',progress:{stage:'故事',phase:'完成',percent:100,status:'done',elapsed_seconds:2},result:{turn:{revision:4}}};}});
 vm.runInContext(interrupted+'\n'+tracked,context);
 const result=await context.trackedApi('/api/play',{text:'查看橋樑',request_id:'one-request'},{prepend(){}});
 assert.equal(result.turn.revision,4);
 assert.equal(submit,2);assert.equal(polls,3);
 assert.ok(calls.filter(c=>c.body).every(c=>c.body.request_id==='one-request'),'timeout reattaches to the same action');
 assert.equal(saved.length,2);assert.equal(saved.at(-1),null,'clear pending identifier only after result delivered');
 context.api=async()=>{throw new Error('無效的行動');};
 await assert.rejects(context.trackedApi('/api/play',{text:'x'},{prepend(){}}),/無效的行動/,'validation errors do not loop');
 const scroll=source.match(/^function scrollLatest.*$/m)[0];
 const panel={scrollTop:300,clientTop:1,getBoundingClientRect:()=>({top:200})};
 const action={getBoundingClientRect:()=>({top:470}),scrollIntoView(){assert.fail('must not scroll the outer page');}};
 const turn={querySelector:()=>action},thinking={hidden:true,getBoundingClientRect:()=>({top:800}),scrollIntoView(){assert.fail('must not scroll the outer page');}};
 let outerScroll=137;
 const reading=vm.createContext({location:{hash:'#adventure'},requestAnimationFrame:fn=>fn(),document:{querySelector:()=>panel},window:{scrollTo(){assert.fail('outer scroll must stay unchanged');}},$:id=>id==='thinking'?thinking:{lastElementChild:turn}});
 vm.runInContext(scroll+';scrollLatest();',reading);
 assert.equal(panel.scrollTop,553,'align previous action inside the story frame only');assert.equal(outerScroll,137);
 thinking.hidden=false;vm.runInContext('scrollLatest();',reading);assert.equal(panel.scrollTop,1136,'show loading progress within the frame');
 reading.location.hash='#character';vm.runInContext('scrollLatest();',reading);assert.equal(panel.scrollTop,1136,'background completion does not pull another page away');
 assert.ok(source.includes('await load(true).catch'),'error reload also preserves the page position');
 const hint=source.match(/^function powerHint.*$/m)[0],powerNode={setAttribute(k,v){this[k]=v;}};
 const powerContext=vm.createContext({powerNode});vm.runInContext(hint+';powerHint(powerNode,{name:"灰塵感知",effect:"感受附近灰塵的流動。",limits:"只能感知近處"});',powerContext);
 assert.ok(powerNode.title.includes('感受附近灰塵'));assert.ok(powerNode.title.includes('只能感知近處'));assert.equal(powerNode.tabIndex,0);
 console.log('Timeout recovery, same-action retry, validation failure, reading position and ability hover checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
