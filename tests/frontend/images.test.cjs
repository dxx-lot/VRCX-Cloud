const test=require('node:test'),assert=require('node:assert/strict');
const {Manager}=require('../../src/webui/static/core/images.js');
const ticket=n=>'/media/'+'a'.repeat(64)+'/'+String(n).repeat(64);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {resolve,reject,promise};};
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function image(url,account='a'){
 return {dataset:{mediaUrl:url,mediaAccount:account},style:{},isConnected:true,complete:false,naturalWidth:0,
  getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}};
}
test('unresolved photos have no remote src and cached tickets preserve account',()=>{
 const m=new Manager({read:()=>{},peek:(p,a)=>a==='b'?{src:ticket(1)}:null});
 assert.doesNotMatch(m.attrs('https://assets.vrchat.com/a.png','a'),/ src=/);
 assert.match(m.attrs('https://assets.vrchat.com/a.png','b'),/data-media-account="b" src="\/media\//);
});
test('old node and account completions cannot overwrite the current photo',async()=>{
 const jobs=[];const m=new Manager({read:(p,o)=>{const job=deferred();jobs.push({o,...job});return job.promise;}});
 const img=image('https://assets.vrchat.com/a.png');m.hydrate(img);await flush();
 m.setURL(img,'https://assets.vrchat.com/b.png','b');await flush();
 jobs[0].resolve({src:ticket(1)});await flush();assert.equal(img.src,undefined);
 jobs[1].resolve({src:ticket(2)});await flush();assert.equal(img.src,ticket(2));assert.equal(jobs[1].o.account,'b');
 const old=image('https://assets.vrchat.com/old.png');m.hydrate(old);await flush();old.isConnected=false;
 jobs[2].resolve({src:ticket(3)});await flush();assert.equal(old.src,undefined);
});
test('image jobs are coalesced and bounded, with captured accounts',async()=>{
 const jobs=[];const m=new Manager({limit:2,read:()=>{const job=deferred();jobs.push(job);return job.promise;}});
 const imgs=['a','a','b','c'].map(x=>image('https://assets.vrchat.com/'+x+'.png'));
 imgs.forEach(i=>m.hydrate(i));await flush();assert.equal(jobs.length,2);
 jobs[0].resolve({src:ticket(1)});await flush();assert.equal(jobs.length,3);assert.equal(imgs[0].src,imgs[1].src);
 jobs[1].resolve({src:ticket(2)});jobs[2].resolve({src:ticket(3)});await flush();
 assert.equal(m.busy,0);
});
test('invalid tickets refresh once, then use the node fallback without infinite retries',async()=>{
 let count=0,fallback=0;const m=new Manager({read:async()=>({src:ticket(++count)}),fallback:()=>fallback++});
 const img=image('https://assets.vrchat.com/a.png');img.dataset.photos='["a"]';m.hydrate(img);await flush();
 m.failed(img);await flush();m.failed(img);await flush();
 assert.equal(count,2);assert.equal(fallback,1);
});
test('a lookup failure leaves an already decoded photo visible',async()=>{
 const m=new Manager({read:async()=>{throw new Error('temporary');}});
 const img=image('https://assets.vrchat.com/a.png');img.src=ticket(1);img.complete=true;img.naturalWidth=100;
 m.hydrate(img);await flush();assert.equal(img.src,ticket(1));assert.equal(img.style.display,undefined);
});
test('detail redraw reuses decoded nodes only for the same account, URL and role',()=>{
 const m=new Manager({read:()=>{}}),old=image('https://assets.vrchat.com/a.png');
 old.complete=true;old.naturalWidth=256;old.className='uavatar';
 const fresh=image(old.dataset.mediaUrl),wrong=image(old.dataset.mediaUrl,'b');
 fresh.className=wrong.className='uavatar';let kept=null;fresh.replaceWith=node=>kept=node;wrong.replaceWith=()=>assert.fail('cross-account reuse');
 const photos=m.capture({querySelectorAll:()=>[old]});m.restore({querySelectorAll:()=>[wrong,fresh]},photos);
 assert.equal(kept,old);assert.equal(kept.naturalWidth,256);
});

test('detail images bypass visibility waiting and keep eager browser priority',()=>{
 const m=new Manager({read:()=>{}}),img=image('https://assets.vrchat.com/world.png');
 img.dataset.mediaPriority='high';let hydrated=0,observed=0;
 m.hydrate=()=>hydrated++;m.visibility={observe:()=>observed++};
 m.scan({querySelectorAll:()=>[img,image('https://assets.vrchat.com/avatar.png')]});
 assert.equal(hydrated,1);assert.equal(observed,1);
 assert.match(m.attrs(img.dataset.mediaUrl,'b','high'),/loading="eager" fetchpriority="high"/);
});

test('an opened world image goes ahead of queued thumbnails without exceeding concurrency',async()=>{
 const calls=[],jobs=[];
 const m=new Manager({limit:1,read:(path)=>{calls.push(path);const job=deferred();jobs.push(job);return job.promise;}});
 const active=m.ticket('https://assets.vrchat.com/active.png','a');
 const thumbnail=m.ticket('https://assets.vrchat.com/thumbnail.png','a');
 const world=m.ticket('https://assets.vrchat.com/world.png','b',false,true);
 await flush();assert.equal(calls.length,1);
 jobs[0].resolve({src:ticket(1)});await flush();
 assert.match(calls[1],/world.png/);assert.equal(m.busy,1);
 jobs[1].resolve({src:ticket(2)});await flush();assert.match(calls[2],/thumbnail.png/);
 jobs[2].resolve({src:ticket(3)});await Promise.all([active,thumbnail,world]);await flush();
 assert.equal(m.busy,0);
});

test('a high-priority consumer promotes an already queued shared image request',async()=>{
 const calls=[],jobs=[],m=new Manager({limit:1,read:path=>{
  calls.push(path);const job=deferred();jobs.push(job);return job.promise;
 }});
 const first=m.ticket('https://assets.vrchat.com/active.png','a');
 const other=m.ticket('https://assets.vrchat.com/other.png','a');
 const world=m.ticket('https://assets.vrchat.com/world.png','a');
 assert.equal(m.ticket('https://assets.vrchat.com/world.png','a',false,true),world);
 await flush();jobs[0].resolve({src:ticket(1)});await flush();assert.match(calls[1],/world.png/);
 jobs[1].resolve({src:ticket(2)});await flush();jobs[2].resolve({src:ticket(3)});
 await Promise.all([first,other,world]);await flush();assert.equal(calls.length,3);
});

test('world redraw can retain an in-flight image without restarting its node',()=>{
 const m=new Manager({read:()=>{}}),old=image('https://assets.vrchat.com/world.png');old.className='wthumb';
 const container={querySelectorAll:()=>[old]};
 assert.equal(m.capture(container).length,0);
 const replacement=image(old.dataset.mediaUrl);replacement.className='wthumb';let retained=null;
 replacement.replaceWith=node=>retained=node;
 m.restore({querySelectorAll:()=>[replacement]},m.capture(container,true));
 assert.equal(retained,old);assert.equal(retained.complete,false);
});

test('a persistent account card recovers after a temporary lookup failure with backoff',async()=>{
 let clock=0,calls=0;const m=new Manager({now:()=>clock,read:async()=>{
  calls++;if(calls===1)throw new Error('temporary');return {src:ticket(2)};
 }}),img=image('https://assets.vrchat.com/self.png');
 m.setURL(img,img.dataset.mediaUrl,'a','high');await flush();
 assert.equal(img.style.visibility,'hidden');assert.equal(calls,1);
 m.setURL(img,img.dataset.mediaUrl,'a','high');await flush();assert.equal(calls,1);
 clock=6000;m.setURL(img,img.dataset.mediaUrl,'a','high');await flush();
 assert.equal(calls,2);assert.equal(img.src,ticket(2));assert.equal(img.style.visibility,'');
});

test('clearing or switching an account card removes the old picture and fences pending work',async()=>{
 const jobs=[],m=new Manager({read:()=>{const job=deferred();jobs.push(job);return job.promise;}});
 const img=image('https://assets.vrchat.com/self-a.png');img.src=ticket(1);
 m.setURL(img,'https://assets.vrchat.com/self-b.png','b','high');await flush();
 assert.equal(img.src,undefined);assert.equal(img.dataset.mediaPriority,'high');
 m.clear(img);jobs[0].resolve({src:ticket(2)});await flush();
 assert.equal(img.src,undefined);assert.equal(img.dataset.mediaUrl,undefined);
});
