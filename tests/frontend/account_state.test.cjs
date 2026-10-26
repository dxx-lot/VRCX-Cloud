const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {Manager}=require('../../src/webui/static/core/images.js');
test('clearAccountUI fences a pending old-account header picture before the next profile arrives',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);
 const manager=new Manager({read:()=>pending}),elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{dataset:{},style:{},isConnected:true,
  setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},getAttribute(k){return this[k]||null;},classList:{add(){}}});return elements.get(id);};
 const photo=element('selfThumb');manager.setURL(photo,'https://example.test/a.png','a','high');
 for(let i=0;i<5;i++)await Promise.resolve();
 const source=fs.readFileSync(path.join(__dirname,'../../src/webui/static/bootstrap.js'),'utf8');
 const fn=source.slice(source.indexOf('function clearAccountUI(){'),source.indexOf('\nfunction showPartial'));
 const context={document:{getElementById:element},IMAGES:manager,SAVE_T:null,settingsBusy(){},clearTimeout(){}};
 context.window=context;vm.createContext(context);vm.runInContext(fn+'\nclearAccountUI();',context);
 resolve({src:'/media/'+'a'.repeat(64)+'/'+'1'.repeat(64)});
 for(let i=0;i<20;i++)await Promise.resolve();
 assert.equal(photo.src,undefined);assert.equal(photo.dataset.mediaUrl,undefined);
 assert.equal(photo.dataset.mediaAccount,undefined);
});
