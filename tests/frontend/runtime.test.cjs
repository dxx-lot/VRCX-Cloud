const test = require('node:test');
const assert = require('node:assert/strict');
const {Context, Client, Tasks, Pages, Scheduler, PageHistory, RealtimeChannel, StaleRequest, realtimeState} = require('../../src/webui/static/core/runtime.js');
const Feed = require('../../src/webui/static/core/feed.js');
const deferred = () => { let resolve; const promise = new Promise(r=>resolve=r); return {resolve,promise}; };
const ev = (id, ts=100, extra={}) => ({id,ts,friend_id:'usr_test',event:'location',location:'wrld_one:1',...extra});
const peerPath = url => url.startsWith('/api/peer-relay?') ? new URL(url,'https://fixture').searchParams.get('path') : null;

test('account names reset when login is absent or fails and unknown account keys are rejected',()=>{
  const {AccountDirectory,loginLabel}=require('../../src/webui/static/core/runtime.js');
  const accounts=new AccountDirectory();
  assert.equal(accounts.observe('a',{logged_in:true,name:'Alice'}),'Alice');
  assert.equal(accounts.observe('a',{logged_in:false,name:'stale identity'}),'账号A');
  assert.equal(accounts.observe('b',null),'账号B');
  for(const snapshot of [null,{}, {logged_in:false}, {logged_in:true,_auth_state:'error'}]) assert.equal(loginLabel(snapshot),'登录异常');
  assert.throws(()=>accounts.setName('__proto__','bad'),/无效/);
});
test('an empty primary account skips remote self lookup while local history stays readable',async()=>{
  const calls=[],client=new Client(new Context('a'),path=>{
    calls.push(path);
    if(path==='/api/status')return {logged_in:false};
    if(path==='/api/feed')return {events:[ev(1)]};
    assert.fail('No remote profile lookup is needed for an empty account');
  });
  assert.equal((await client.read('/api/self')).logged_in,false);
  assert.equal((await client.read('/api/feed')).events.length,1);
  assert.deepEqual(calls,['/api/status','/api/feed']);
});

test('a late status request cannot turn a newly logged-in peer into an error',async()=>{
  const slow=deferred();let probes=0;
  const client=new Client(new Context('b'),(url,options)=>{
    if(options)return {ok:true};
    if(peerPath(url)==='/api/status')return ++probes===1?slow.promise:{logged_in:true};
    return {friends:[]};
  });
  const old=client.read('/api/friends');
  await new Promise(resolve=>setImmediate(resolve));
  await client.write('/api/peer-login',{});
  await client.read('/api/friends');
  const rejected=assert.rejects(old,StaleRequest);
  slow.resolve({logged_in:false});await rejected;
  assert.equal(client.accountState('b').state,'logged_in');
});

test('an account-targeted login invalidates the requested account only',async()=>{
  const client=new Client(new Context('b'),()=>({ok:true}));
  client.accountStates.set('a',{state:'logged_in'});client.accountStates.set('b',{state:'not_logged_in'});
  await client.write('/api/login',{});
  assert.equal(client.accountState('a').state,'logged_in');assert.equal(client.accountState('b'),null);
});

test('A response cannot overwrite B after an account switch', async()=>{
  const pending=deferred(), context=new Context('a');
  const client=new Client(context,url=>url==='/api/status'?{logged_in:true}:url.startsWith('/api/peer-relay')?(peerPath(url)==='/api/status'?{logged_in:true}:{name:'B'}):pending.promise);
  const old=client.read('/api/self'); context.select('b');
  assert.equal((await client.read('/api/self')).name,'B');
  pending.resolve({name:'A'}); await assert.rejects(old,StaleRequest);
});
test('an in-flight page response is discarded on navigation',async()=>{
  const d=deferred(),ctx=new Context(),client=new Client(ctx,()=>d.promise);
  const request=client.read('/api/notifications');ctx.pageEpoch++;
  d.resolve({items:[]});await assert.rejects(request,StaleRequest);
});
test('simultaneous sidebar/feed/widget reads share one request and return isolated copies',async()=>{
  let calls=0;const client=new Client(new Context(),async()=>{calls++;return {friends:[{id:'usr_1'}]};});
  const values=await Promise.all(Array.from({length:8},()=>client.read('/api/friends')));
  assert.equal(calls,1); values[0].friends.length=0;assert.equal(values[1].friends.length,1);
});
test('cache is segregated by account even for equal endpoint paths',async()=>{
  const client=new Client(new Context(),url=>url==='/api/status'?{logged_in:true}:url.startsWith('/api/peer-relay')?(peerPath(url)==='/api/status'?{logged_in:true}:{name:'B'}):{name:'A'});
  assert.equal((await client.read('/api/self',{account:'a'})).name,'A');
  assert.equal((await client.read('/api/self',{account:'b'})).name,'B');
});
test('fixed-account labels do not follow the active viewport',async()=>{
  const ctx=new Context('b'),client=new Client(ctx,url=>url==='/api/status'?{logged_in:true}:url.startsWith('/api/peer-relay')?(peerPath(url)==='/api/status'?{logged_in:true}:{name:'B'}):{name:'A'});
  assert.equal((await client.read('/api/self',{account:'a',fenced:false})).name,'A');
});
test('mutations capture the account and invalidate older cache fills',async()=>{
  const d=deferred(),urls=[],ctx=new Context('b');
  const client=new Client(ctx,(url,opts)=>{urls.push(url);return opts?{ok:true}:d.promise;});
  const read=client.read('/api/self'); await Promise.resolve();
  await client.write('/api/set-status',{status:'busy'});ctx.select('a');
  assert.ok(urls[1].startsWith('/api/peer-relay-post'));
  d.resolve({name:'obsolete'});await assert.rejects(read,StaleRequest);
});
test('merged view refuses writes without issuing a network request',async()=>{
  let calls=0;const client=new Client(new Context('m'),()=>{calls++;});
  assert.equal((await client.write('/api/logout',{})).ok,false);assert.equal(calls,0);
});
test('merged reads keep a healthy peer when the local source fails, with a visible error',async()=>{
  const client=new Client(new Context('m'),url=>url.startsWith('/api/peer-relay')?(peerPath(url)==='/api/status'?{logged_in:true}:{friends:[{id:'b'}]}):{error:'A failed'});
  const data=await client.read('/api/friends');assert.equal(data.friends[0]._src,'b');assert.equal(data._errors.a,'A failed');
});
test('merged reads probe peer login once and skip peer data endpoints after signed out',async()=>{
  const calls=[],client=new Client(new Context('m'),url=>{
    const path=peerPath(url);if(path)calls.push(path);
    if(path==='/api/status')return {logged_in:false};
    return path?{friends:[],events:[]}:{friends:[],events:[]};
  });
  const feed=await client.read('/api/feed');
  assert.match(feed._errors.b,/登录异常/);
  const friends=await client.read('/api/friends');
  assert.match(friends._errors.b,/登录异常/);
  assert.deepEqual(calls,['/api/status']);
  assert.equal(client.accountState('b').state,'not_logged_in');
});
test('peer authentication failure is reported as abnormal and not retried automatically',async()=>{
  const calls=[],client=new Client(new Context('b'),url=>{
    calls.push(peerPath(url));throw new Error('HTTP 401');
  });
  await assert.rejects(client.read('/api/friends'),/登录异常/);
  await assert.rejects(client.read('/api/feed'),/登录异常/);
  assert.deepEqual(calls,['/api/status']);
  assert.equal(client.accountState('b').state,'error');
});
test('latest filter/modal task wins and closing a modal cancels pending completions',()=>{
  const tasks=new Tasks(new Context()); const old=tasks.begin('modal'),next=tasks.begin('modal');
  assert.equal(old.current(),false);assert.equal(next.current(),true);tasks.cancel('modal');assert.equal(next.current(),false);
});
test('navigation loads only the active page and disallows nonmerged pages in merged view',async()=>{
  const ctx=new Context(),pages=new Pages(ctx);let feed=0,favorites=0;
  pages.register('feed',{merged:true,interval:0,load:()=>feed++});pages.register('favorites',{load:()=>favorites++});
  pages.enter('feed');await pages.running;await pages.refresh();assert.equal(feed,2);assert.equal(favorites,0);
  ctx.select('m');assert.equal(pages.enter('favorites'),'feed');await pages.running;assert.equal(favorites,0);
});
test('scheduler neither overlaps a slow job nor polls a hidden browser',async()=>{
  const scheduler=new Scheduler(),d=deferred();let count=0;
  scheduler.add('slow',5000,()=>{count++;return d.promise;});
  const first=scheduler.tick(0);await Promise.resolve();await scheduler.tick(6000);await scheduler.tick(12000,false);
  assert.equal(count,1);d.resolve();await first;
});
test('unknown resources fail explicitly instead of silently reading the wrong account',async()=>{
  const client=new Client(new Context(),()=>assert.fail('must not call transport'));
  await assert.rejects(client.read('/api/typo'),/未注册/);
});
test('merged events preserve rapid movements to different rooms',()=>{
  const rows=Feed.mergeEvents([ev(1,100),ev(2,102,{location:'wrld_two:2'})],[ev(9,101)]);
  assert.equal(rows.length,2);assert.equal(rows.find(r=>r.location==='wrld_one:1')._src,'ab');
});
test('same-account repeated events are never merged and two minutes apart are separate',()=>{
  assert.equal(Feed.mergeEvents([ev(1),ev(2)],[]).length,2);
  assert.equal(Feed.mergeEvents([ev(1,100)],[ev(9,220)]).length,2);
});
test('status/description changes and web-offline versus game-offline do not collapse',()=>{
  assert.equal(Feed.mergeEvents([ev(1,100,{event:'status',status:'busy'})],[ev(9,101,{event:'status',status:'active'})]).length,2);
  assert.equal(Feed.mergeEvents([ev(1,100,{event:'offline',prev_state:'active'})],[ev(9,101,{event:'offline',prev_state:'online'})]).length,2);
  assert.equal(Feed.eventType({event:'offline',prev_state:'active'}),'web_offline');
});
test('HTTP and SSE duplicates use source and event id, not display name',()=>{
  assert.equal(Feed.normalize([ev(1),ev(1),ev(2,100,{friend_id:'usr_other'})]).length,2);
  assert.equal(Feed.normalize([{...ev(1),_src:'a'},{...ev(1),_src:'b'}]).length,2);
});
test('merged friends prefer game, then web, then offline and retain each source for details',()=>{
  const friend={id:'usr_shared',name:'Shared',online:false,state:'offline'};
  const result=Feed.mergeFriends([friend],[{...friend,online:true,web_online:true,state:'active'}]);
  assert.equal(result[0]._src,'ab');assert.equal(result[0]._detailSource,'b');assert.equal(result[0].state,'active');
  assert.equal(result[0]._accounts.a.state,'offline');
});
test('a superseded route cannot start its loader in the next microtask', async()=>{
  const ctx=new Context(),pages=new Pages(ctx); const loaded=[];
  pages.register('feed',{merged:true,load:()=>loaded.push('feed')});
  pages.register('favorites',{load:()=>loaded.push('favorites')});
  pages.enter('feed');pages.enter('favorites');await pages.running;
  assert.deepEqual(loaded,['favorites']);
});
test('reentering a running page joins work, and an account switch releases the old load',async()=>{
  const ctx=new Context(),pages=new Pages(ctx),d=deferred();let loads=0;
  pages.register('feed',{merged:true,load:()=>{loads++;return d.promise;}});
  pages.enter('feed');const first=pages.running;await Promise.resolve();
  pages.enter('feed');assert.equal(pages.running,first);assert.equal(loads,1);
  ctx.select('b');pages.enter('feed');await Promise.resolve();assert.equal(loads,2);
  d.resolve();await pages.running;
});
test('a source typo cannot silently route account data or writes to A',async()=>{
  const client=new Client(new Context(),()=>assert.fail('no request allowed'));
  await assert.rejects(client.read('/api/self',{account:'ab'}),/无效/);
  await assert.rejects(client.write('/api/set-status',{}, {account:'system'}),/无效/);
});
test('a sent write stays on B but its late reply cannot mutate the new A page',async()=>{
  const d=deferred(),ctx=new Context('b'),calls=[];
  const client=new Client(ctx,(url)=>{calls.push(url);return d.promise;});
  const pending=client.write('/api/config-set',{poll_seconds:30});ctx.select('a');
  d.resolve({ok:true});await assert.rejects(pending,StaleRequest);
  assert.ok(calls[0].startsWith('/api/peer-relay-post'));
  assert.equal(client.revisions.get('b'),1);
});
test('errors from a departed page are stale instead of appearing on its successor',async()=>{
  let reject;const p=new Promise((_,r)=>reject=r),ctx=new Context(),client=new Client(ctx,()=>p);
  const pending=client.read('/api/friends');await Promise.resolve();ctx.pageEpoch++;
  reject(new Error('old network failure'));await assert.rejects(pending,StaleRequest);
});

test('realtime label reports token polling and failed push fallback honestly',()=>{
  for(const [view,token,state] of [['a',true,'idle'],['m',false,'failed'],['b',false,'connected'],['a',false,'failed']]){
    const result=realtimeState(view,token,state);
    assert.match(result.text,/每 5 秒刷新/);assert.equal(result.connected,false);
    assert.match(result.detail,/上次采集时间/);
  }
  assert.match(realtimeState('a',false,'connecting').text,/连接中/);
  assert.equal(realtimeState('a',false,'connected').connected,true);
});

test('page return trail restores exact browser entries without return loops',()=>{
  const trail=new PageHistory();trail.enter('settings');const first=trail.current;
  trail.enter('login');const login=trail.current;
  trail.restore(first.key,'settings');assert.equal(trail.previous.page,'feed');
  trail.restore(login.key,'login');assert.equal(trail.previous.page,'settings');
  assert.equal(trail.back().page,'settings');
  trail.enter('netstats');assert.equal(trail.back().page,'settings');
  trail.enter('extensions');assert.equal(trail.back().page,'settings');
  assert.equal(trail.back().page,'feed');assert.equal(trail.previous,null);
  for(let i=0;i<100;i++)trail.enter('page-'+i);
  assert.equal(trail.entries.length,64);
  trail.restore(first.key,'settings');assert.equal(trail.current.page,'settings');assert.equal(trail.previous,null);
});

function channelFixture(){
  const streams=[],states=[],feeds=[],timers=new Map();let key=0;
  class Source {
    constructor(){this.listeners={};this.closed=false;streams.push(this);}
    addEventListener(type,callback){this.listeners[type]=callback;}
    close(){this.closed=true;}
    feed(data){this.listeners.feed({data});}
  }
  const channel=new RealtimeChannel({create:()=>new Source(),onState:value=>states.push(value),onFeed:value=>feeds.push(value),
    later:(fn,ms)=>{timers.set(++key,{fn,ms});return key;},cancel:id=>timers.delete(id)});
  return {channel,streams,states,feeds,timers,fire(ms){for(const [id,item] of [...timers])if(item.ms===ms){timers.delete(id);item.fn();}}};
}
test('a buffered stream times out to polling and retries without accepting stale events',()=>{
  const f=channelFixture();f.channel.start();f.channel.start();assert.equal(f.streams.length,1);
  const old=f.streams[0];f.fire(8000);assert.ok(old.closed);assert.equal(f.states.at(-1),'failed');
  old.onopen();old.feed('{"id":1}');assert.equal(f.states.at(-1),'failed');assert.equal(f.feeds.length,0);
  f.fire(30000);assert.equal(f.streams.length,2);
  const current=f.streams[1];current.onopen();assert.equal(f.states.at(-1),'connected');assert.equal(f.timers.size,0);
  current.feed('malformed');current.feed('{"id":2}');assert.deepEqual(f.feeds,[{id:2}]);
  current.onerror();assert.ok(current.closed);assert.equal(f.states.at(-1),'failed');
});
test('stopping a stream for a different account or pagehide cancels reconnect and pageshow starts fresh',()=>{
  const f=channelFixture();f.channel.start();const old=f.streams[0];old.onerror();
  f.channel.stop();f.fire(30000);assert.equal(f.timers.size,0);assert.equal(f.streams.length,1);
  old.onopen();assert.equal(f.states.at(-1),'idle');
  f.channel.start();assert.equal(f.streams.length,2);f.channel.stop();assert.ok(f.streams[1].closed);
});
test('peer local settings and backups remain available when VRChat login is absent',async()=>{
  const calls=[],client=new Client(new Context('b'),url=>{calls.push(peerPath(url));return {bark:{}};});
  await client.read('/api/config');await client.read('/api/push-config');await client.read('/api/backup');
  assert.deepEqual(calls,['/api/config','/api/push-config','/api/backup']);
});

test('instant detail snapshots are isolated copies and never cross accounts or write revisions',async()=>{
  const ctx=new Context('a'),client=new Client(ctx,url=>({user:{name:url.startsWith('/api/peer')?'B':'A'}}));
  await client.read('/api/friend?id=usr_one');
  assert.equal(client.peek('/api/friend?id=usr_one','b'),null);
  const snapshot=client.peek('/api/friend?id=usr_one','a');snapshot.user.name='modified';
  assert.equal(client.peek('/api/friend?id=usr_one','a').user.name,'A');
  await client.write('/api/friend-note',{id:'usr_one',note:'test'});
  assert.equal(client.peek('/api/friend?id=usr_one','a'),null);
});
