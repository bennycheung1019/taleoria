const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('connection.js','utf8');
function setup(local=false){
 const saved=new Map(),calls=[];
 const context=vm.createContext({URL,Headers,AbortSignal,location:{origin:local?'http://127.0.0.1:8787':'https://taleoria.example'},
  localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},
  window:{RPG_TOKEN:local?'local-only-token':'HOSTED_COMPANION',fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({companion_url:'https://mac.example',model_url:'http://127.0.0.1:5001'})};}}});
 vm.runInContext(source,context);return {transport:context.window.TaleoriaConnection,calls,saved};
}
(async()=>{
 const remote=setup();await remote.transport.ready;
 assert.equal(remote.transport.get().companion_url,'https://mac.example');
 assert.equal(remote.transport.needsPairing(),true);
 await assert.rejects(remote.transport.fetch('/api/session'),/配對碼/);
 const secret='private-browser-pairing';
 remote.transport.save({companion_url:'https://home.example',key:secret,model_url:'http://127.0.0.1:5002'});
 await remote.transport.fetch('/api/session',{headers:{'X-RPG-Session':'session-one'}});
 const sent=remote.calls.at(-1);
 assert.equal(sent.url,'https://home.example/api/session');
 assert.equal(sent.options.headers.get('X-Taleoria-Key'),secret);
 assert.equal(sent.options.headers.get('X-RPG-Session'),'session-one');
 assert.ok(!sent.url.includes(secret));assert.equal(sent.options.credentials,'omit');
 assert.ok(remote.saved.size===1,'pairing stays in this browser');
 for(const bad of ['https://user:password@remote.example','http://public.example','https://host.example/path','https://host.example?key=private'])assert.throws(()=>remote.transport.endpoint(bad));
 await assert.rejects(remote.transport.fetch('https://other.example/api/session'));
 const local=setup(true);await local.transport.ready;
 await local.transport.fetch('/api/session',{headers:{'X-RPG-Token':'local-only-token'}});
 assert.equal(local.calls[0].options.headers.has('X-Taleoria-Key'),false);
 assert.equal(local.calls[0].options.headers.get('X-RPG-Token'),'local-only-token');
 assert.equal(local.saved.size,0);
 console.log('Connection checks passed: explicit pairing, correct computer, no secrets in URLs, local behavior preserved.');
})();
