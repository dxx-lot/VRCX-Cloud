/* Execute shipped page handlers against minimal DOM elements and native HTTP
 * Responses. This verifies handler contracts; browser layout has a separate fixture. */
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ROOT=path.resolve(__dirname,'../../src/webui/static');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
function element(id){
  const classes=new Set(['hidden']);
  return {id,value:'',textContent:'',innerHTML:'',style:{},dataset:{},options:[],isConnected:true,
    classList:{add(...xs){xs.forEach(x=>classes.add(x));},remove(...xs){xs.forEach(x=>classes.delete(x));},
      contains(x){return classes.has(x);},toggle(x,on){on=on??!classes.has(x);on?classes.add(x):classes.delete(x);return on;}},
    focus(){},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},scrollIntoView(){},appendChild(){},querySelectorAll(){return []},getBoundingClientRect(){return {left:0,width:100}}};
}
function ui(transport,{dashboard}={}){
  const elements=new Map(),timers=new Map();let tid=0;
  const el=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
  const pages=['feed','favorites','login','dash','settings','netstats','extensions','push'].map(id=>el('page-'+id));
  const storage=new Map();if(dashboard!==undefined) storage.set('vrcxDashs',dashboard);
  const context={console,Response,AbortController,URL,Date,Promise,
    setTimeout(fn,ms){timers.set(++tid,{fn,ms});return tid;},clearTimeout(id){timers.delete(id);},
    setInterval(){return 0;},clearInterval(){},confirm:()=>true,alert:()=>{},matchMedia:()=>({matches:false}),
    addEventListener(){},navigator:{},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    fetch:async(url,options)=>{
      let data=await transport(url,options);
      const status=url==='/api/status'||url.startsWith('/api/peer-relay?')&&new URL(url,'https://fixture').searchParams.get('path')==='/api/status';
      if(status&&typeof data?.logged_in!=='boolean'&&!data?.error)data={logged_in:true};
      return new Response(JSON.stringify(data),{status:200});
    },
    document:{body:element('body'),getElementById:el,querySelectorAll:s=>s==='[id^="page-"]'?pages:[],querySelector:s=>el(s),addEventListener(){},createElement:()=>element('new')}
  };
  context.window=context;vm.createContext(context);
  for(const file of ['core/feed.js','core/runtime.js','core/legacy.js','core/images.js','pages/activity.js','pages/catalog.js','pages/details.js','pages/accounts.js','pages/mobile.js'])
    vm.runInContext(fs.readFileSync(path.join(ROOT,file),'utf8'),context,{filename:file});
  vm.runInContext('alignGSlide=()=>{};showPartial=()=>{};',context);
  return {context,el,run:code=>vm.runInContext(code,context),timers,
    async flush(ms){const selected=[...timers].filter(([,t])=>t.ms===ms);for(const [id,t] of selected){timers.delete(id);await t.fn();}}};
}
test('shipped account handlers keep A identity fixed while the self card follows B',async()=>{
  const calls=[],u=ui(async url=>{calls.push(url);return {name:url.startsWith('/api/peer')?'账号B':'账号A',logged_in:true,id:'usr_test'};});
  u.run("GA='b';APP.context.select('b')");
  await u.context.loadAccount();await u.context.loadPeerAccount();await u.context.loadSelf();
  assert.equal(u.el('selfName').textContent,'账号B');
  assert.match(u.el('acctSelf').innerHTML,/账号A/);assert.match(u.el('acctPeer').innerHTML,/账号B/);
  assert.equal(u.run('GA_NAMES.a'),'账号A');assert.equal(u.run('GA_NAMES.b'),'账号B');
  assert.equal(calls.length,4); // Both identities have a shared login-status probe before their profile request.
});
test('shipped self handler drops a slow A result after selection moves to B',async()=>{
  const slow=deferred(),u=ui(url=>url.startsWith('/api/peer')?{name:'B',logged_in:true}:slow.promise);
  const old=u.context.loadSelf();await Promise.resolve();
  u.run("GA='b';GA_EPOCH++;APP.context.select('b')");await u.context.loadSelf();
  slow.resolve({name:'A',logged_in:true});await old;assert.equal(u.el('selfName').textContent,'B');
});
test('peer account checks status first and does not request profile when signed out',async()=>{
  const calls=[],u=ui(async url=>{
    calls.push(url);
    const path=url.startsWith('/api/peer-relay?')?new URL(url,'https://fixture').searchParams.get('path'):url;
    return path==='/api/status'?{logged_in:false}:{name:'should-not-load'};
  });
  u.run("CURPAGE='login';ACCT_VIEW='peer';");
  await u.context.loadPeerAccount();
  assert.equal(calls.length,1);
  assert.equal(new URL(calls[0],'https://fixture').searchParams.get('path'),'/api/status');
  assert.match(u.el('acctPeer').innerHTML,/登录异常/);
  assert.doesNotMatch(u.el('acctPeer').innerHTML,/should-not-load/);
});
test('failed account loads remove previous names and hide raw endpoint diagnostics',async()=>{
  const u=ui(()=>{throw new Error('ConnectionPool 127.0.0.1:8001 synthetic detail');});
  u.run("updateAccountName('a','old A');updateAccountName('b','old B');CURPAGE='login';ACCT_VIEW='peer';");
  await u.context.loadAccount();await u.context.loadPeerAccount();
  assert.equal(u.run('GA_NAMES.a'),'账号A');assert.equal(u.run('GA_NAMES.b'),'账号B');
  for(const id of ['acctSelf','acctPeer']){
    assert.match(u.el(id).innerHTML,/登录异常/);assert.doesNotMatch(u.el(id).innerHTML,/8001|ConnectionPool|old [AB]/);
  }
});
test('merged phone menu removes pages that cannot work in a read-only view',()=>{
  const u=ui(()=>({}));
  u.run("for(const id of ['feed','locations','home','login','netstats'])APP.pages.register(id,{merged:true});for(const id of ['notifs','search','friendlog','modlist','avatars','push','settings','dash','tools','direct'])APP.pages.register(id,{});GA='m';APP.context.select('m');");
  u.context.mobileMenu();
  assert.match(u.el('moreGrid').innerHTML,/账号/);
  assert.doesNotMatch(u.el('moreGrid').innerHTML,/通知|搜索|好友日志|玩家管理|我的模型|推送|设置|仪表板|直达/);
  assert.match(u.el('moreGrid').innerHTML,/流量/);
});
test('phone social aliases enter their registered page without opening an account picker',()=>{
  const u=ui(()=>({}));
  u.run("APP.pages.register('feed',{merged:true});APP.pages.register('moderation',{});");
  u.context.mobileGo('friendlog');
  assert.equal(u.run('CURPAGE'),'moderation');
  assert.equal(u.run('MobileUI.pending'),null);
  u.context.mobileMenu();
  assert.match(u.el('moreGrid').innerHTML,/好友日志|玩家管理/);
});
test('merge-only chrome controls are hidden and restored with the selected view',()=>{
  const u=ui(()=>({})),control=u.el('merge-only-control');
  u.context.document.querySelectorAll=selector=>selector==='[data-hide-in-merge]'?[control]:[];
  u.run("GA='m';APP.context.select('m');MobileUI.refresh();");
  assert.ok(control.classList.contains('hidden'));
  u.run("GA='a';APP.context.select('a');MobileUI.refresh();");
  assert.ok(!control.classList.contains('hidden'));
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  assert.match(html,/<button id="sideSettings"[^>]*data-hide-in-merge/);
  assert.match(html,/<button data-mb="favorites" onclick="mobileGo\('favorites'\)"/);
});
test('settings debounce sends one captured-account transaction and cancels on switching',async()=>{
  const calls=[],u=ui(async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true};});
  u.run('CFG={}');u.el('set-poll_seconds').value='45';u.el('set-group').value='test';
  u.context.saveSettings();u.context.saveSettings();await u.flush(600);
  assert.equal(calls.length,1);assert.equal(calls[0].body.poll_seconds,45);
  u.context.saveSettings();u.run("GA='b';APP.context.select('b')");await u.flush(600);
  assert.equal(calls.length,1);
});
test('all settings destinations have a usable return path on desktop',()=>{
  const u=ui(()=>({}));
  u.run("for(const id of ['feed','settings','login','extensions','netstats'])APP.pages.register(id,{merged:true});");
  for(const target of ['login','extensions','netstats']){
    u.context.switchPage('settings');u.context.switchPage(target);
    assert.equal(u.el('pageBack').textContent,'‹ 返回设置');
    assert.ok(!u.el('pageBack').classList.contains('hidden'));
    u.context.pageBack();assert.equal(u.run('CURPAGE'),'settings');
    assert.equal(u.el('pageBack').textContent,'‹ 返回好友动态');
  }
  u.context.pageBack();assert.equal(u.run('CURPAGE'),'feed');assert.ok(u.el('pageBack').classList.contains('hidden'));
});
test('mobile header identifies secondary pages when duplicate content headings are hidden',()=>{
  const u=ui(()=>({}));
  for(const [page,label] of [['stats','统计'],['friends','好友列表'],['mutual','共同好友'],['activity','活动记录'],['hotworlds','热门世界']]){
    u.run('CURPAGE='+JSON.stringify(page));u.context.MobileUI.refresh();
    assert.equal(u.el('mobileTitle').textContent,label);
  }
});
test('switching to a merged view removes unavailable pages from the return trail',()=>{
  const u=ui(()=>({}));
  u.run("APP.pages.register('feed',{merged:true});APP.pages.register('settings',{});APP.pages.register('login',{merged:true});");
  u.context.switchPage('settings');u.context.switchPage('login');
  u.run("GA='m';APP.context.select('m')");u.context.switchPage('login');
  assert.equal(u.el('pageBack').textContent,'‹ 返回好友动态');
  u.context.pageBack();assert.equal(u.run('CURPAGE'),'feed');
});
test('settings load failure offers a retry and a valid partial config restores editing',async()=>{
  let failed=true;
  const u=ui(()=>{if(failed)throw new Error('synthetic unavailable');return {poll_seconds:30};});
  const input=u.el('set-poll_seconds');
  const oldQuery=u.context.document.querySelectorAll;
  u.context.document.querySelectorAll=selector=>selector.includes('#page-settings input')?[input]:oldQuery(selector);
  await u.context.loadSettings();assert.equal(u.run('CFG'),null);assert.ok(input.disabled);
  assert.match(u.el('settingsLoadStatus').textContent,/设置加载失败/);assert.ok(!u.el('settingsLoadRetry').classList.contains('hidden'));
  failed=false;await u.context.loadSettings(true);
  assert.ok(!input.disabled);assert.equal(input.value,30);assert.ok(u.el('settingsLoadRetry').classList.contains('hidden'));
  assert.doesNotMatch(u.el('set-pwstate').textContent,/局域网内无需口令/);
});
test('a delayed failed settings request cannot lock or replace a different account config',async()=>{
  const slow=deferred();const u=ui(url=>url==='/api/config'?slow.promise:{poll_seconds:45});
  const first=u.context.loadSettings();await Promise.resolve();
  u.run("GA='b';APP.context.select('b')");await u.context.loadSettings();
  slow.resolve({error:'old source failed'});await first;
  assert.equal(u.el('set-poll_seconds').value,45);assert.match(u.el('settingsLoadStatus').textContent,/账号B/);
});
test('a notification write invalidating a new settings read triggers a bounded fresh retry',async()=>{
  const slow=deferred();let reads=0;
  const u=ui((url,options)=>options?.method==='POST'?{ok:true}:++reads===1?slow.promise:{poll_seconds:60});
  const load=u.context.loadSettings();await new Promise(resolve=>setImmediate(resolve));
  await u.run("gPost('/api/notification-act',{id:'synthetic',op:'read'})");
  slow.resolve({poll_seconds:30});await load;
  assert.equal(reads,2);assert.equal(u.el('set-poll_seconds').value,60);assert.match(u.el('settingsLoadStatus').textContent,/当前账号/);
});
test('compatibility password settings are read-only and cannot desynchronize peer authentication',()=>{
  const u=ui(()=>({}));
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  assert.doesNotMatch(html,/onclick="savePassword\(/);
  assert.doesNotMatch(html,/id="set-(?:old|new)pw"/);
  assert.match(html,/网页不支持分别修改或清除服务口令/);
  assert.equal(typeof u.context.savePassword,'undefined');
});
test('failed push scope loading exposes an independent retry and ignores old page responses',async()=>{
  let failed=true;const u=ui(()=>{if(failed)throw new Error('scope unavailable');return {mode:'favorites',friends:[],watch:[]};});
  await u.context.loadPushCfg();assert.ok(!u.el('pushScopeRetry').classList.contains('hidden'));
  assert.equal(u.context.pushReady(),false);
  failed=false;await u.context.loadPushCfg(true);assert.ok(u.el('pushScopeRetry').classList.contains('hidden'));
  assert.equal(u.context.pushReady(),true);
});
test('backup list failure has a retry and does not leave a permanent loading option',async()=>{
  let failed=true;const u=ui(()=>{if(failed)throw new Error('offline');return {backups:['synthetic.db']};});
  await u.context.loadBackups();assert.match(u.el('bkList').innerHTML,/加载失败/);
  assert.ok(!u.el('backupRetry').classList.contains('hidden'));
  failed=false;await u.context.loadBackups(true);
  assert.match(u.el('bkList').innerHTML,/synthetic.db/);assert.ok(u.el('backupRetry').classList.contains('hidden'));
});
test('quick search closing prevents its delayed results from replacing the overlay',async()=>{
  const slow=deferred(),u=ui(()=>slow.promise);u.el('qsInput').value='someone';
  const job=u.context.doQuickSearch();u.context.closeQS();u.el('qsBody').innerHTML='closed';
  slow.resolve({users:[],worlds:[],groups:[]});await job;
  assert.equal(u.el('qsBody').innerHTML,'closed');assert.ok(u.el('qsOverlay').classList.contains('hidden'));
});
test('group details render the registered info tab and old members cannot overwrite it',async()=>{
  const slow=deferred(),u=ui(url=>url.startsWith('/api/group-members')?slow.promise:{group:{id:'grp_test',name:'Group',description:'Info'}});
  await u.context.openGroup('grp_test');assert.match(u.el('gdBody').innerHTML,/Info/);
  u.context.setGDTab('members');u.context.setGDTab('info');slow.resolve([{id:'usr_1',name:'old'}]);
  await new Promise(resolve=>setImmediate(resolve));assert.match(u.el('gdBody').innerHTML,/Info/);
});
test('a dashboard widget never renders into a replaced element',async()=>{
  const slow=deferred(),u=ui(()=>slow.promise),widget=u.el('widget');
  const job=u.context.renderWidget('feed','widget');widget.isConnected=false;widget.innerHTML='detached';
  slow.resolve({events:[]});await job;assert.equal(widget.innerHTML,'detached');
});
test('login navigation keeps exactly one page visible through the lifecycle registry',()=>{
  const u=ui(()=>({}));u.run("APP.pages.register('feed',{merged:true});APP.pages.register('login',{merged:true});");
  u.context.switchPage('feed');u.context.showLogin();
  assert.ok(u.el('page-feed').classList.contains('hidden'));
  assert.ok(!u.el('page-login').classList.contains('hidden'));
  assert.equal(u.run('APP.pages.active'),'login');
});

test('feed freshness identifies stale collection and keeps merged account timestamps separate',()=>{
  const u=ui(()=>({}));
  u.context.renderFeedFreshness({last_sync:1000,server_now:1600});
  assert.match(u.el('feedFreshness').textContent,/A 号数据已超过10分钟未更新/);
  assert.match(u.el('feedFreshness').textContent,/上次采集/);
  assert.equal(u.el('feedFreshness').style.borderLeftColor,'var(--yellow)');
  u.run("GA='m';APP.context.select('m')");
  u.context.renderFeedFreshness({_accounts:{
    a:{last_sync:1000,server_now:1060},b:{last_sync:null,server_now:1060}
  }});
  assert.match(u.el('feedFreshness').textContent,/A 号最近采集/);
  assert.match(u.el('feedFreshness').textContent,/B 号暂无采集记录/);
});

test('feed page exposes freshness and uses one label for web presence',()=>{
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  assert.match(html,/id="feedFreshness"/);
  assert.equal((html.match(/data-f="active"[^>]*>网页在线/g)||[]).length,2);
  assert.doesNotMatch(html,/data-f="active"[^>]*>网页登录/);
});

const feedEvent=(id,friend='usr_target')=>({id,friend_id:friend,
  display_name:friend==='usr_target'?'FixtureFriend':friend,event:'online',ts:1700000000+id,location:'private'});
function feedTransport(reply,calls=[]){
  return async url=>{
    calls.push(url);
    const path=url.startsWith('/api/peer-relay?')?new URL(url,'https://fixture').searchParams.get('path'):url;
    if(path==='/api/friends')return {friends:[{id:'usr_target',name:'FixtureFriend'}]};
    return reply(path,url);
  };
}

test('friend filtering queries history before the global 500-row cap and paginates its own results',async()=>{
  const calls=[],all=Array.from({length:37},(_,i)=>feedEvent(i+1));
  const recent=[...all.slice(30),...Array.from({length:493},(_,i)=>feedEvent(i+100,'usr_other'))];
  const u=ui(feedTransport(path=>({events:path==='/api/feed'?recent:all}),calls));
  u.el('feedPageSize').value='20';
  await u.context.loadFeed();assert.equal(u.run('FEEDDATA.length'),500);
  await u.context.setFeedFriend('usr_target');
  assert.ok(calls.includes('/api/history?days=365&friend_id=usr_target'));
  assert.equal(u.run('FEEDDATA.length'),37);
  assert.match(u.el('feedPager').innerHTML,/近一年共 37 条/);
  assert.match(u.el('mobileFeed').innerHTML,/近一年共 37 条/);
  assert.equal((u.el('feedTable').innerHTML.match(/class="name"/g)||[]).length,20);
  u.run('FEED_PAGE=1;renderFeed()');
  assert.equal((u.el('feedTable').innerHTML.match(/class="name"/g)||[]).length,17);
  await u.context.setFeedFriend('');
  assert.equal(u.run('FEEDDATA.length'),500);
  assert.match(u.el('feedPager').innerHTML,/近期记录中 500 条/);
});

test('desktop and phone text search debounce one encoded history query and clearing restores feed',async()=>{
  const calls=[],u=ui(feedTransport(()=>({events:[]}),calls));
  await u.context.loadFeed();calls.length=0;
  u.context.setFeedSearch('old');u.context.mobileFeedSearch('FixtureFriend &好友');
  assert.match(u.el('mobileFeed').innerHTML,/正在查询/);
  await u.flush(250);
  assert.deepEqual(calls,['/api/history?days=365&name=FixtureFriend%20%26%E5%A5%BD%E5%8F%8B']);
  assert.equal(u.el('feedSearch').value,'FixtureFriend &好友');
  u.context.mobileFeedSearch('');await u.flush(250);
  assert.equal(u.run('feedRequest().path'),'/api/feed');
  assert.match(u.el('feedPager').innerHTML,/近期记录中 0 条/);
});

test('event filters are applied at the server and B rows keep their B source',async()=>{
  const calls=[],u=ui(feedTransport(()=>({events:[{...feedEvent(1),event:'offline',prev_state:'active'}]}),calls));
  u.run("GA='b';GA_EPOCH++;APP.context.select('b')");
  await u.context.setFeedFriend('usr_target');
  await u.context.setFeedFilter({dataset:{f:'web_offline'}});
  const relay=calls.map(url=>new URL(url,'https://fixture').searchParams.get('path'));
  assert.ok(relay.includes('/api/history?days=365&friend_id=usr_target&type=web_offline'));
  assert.equal(u.run('FEEDDATA[0]._src'),'b');
  assert.match(u.el('feedPager').innerHTML,/近一年共 1 条/);
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  assert.match(html,/id="feedFriendSel" onchange="setFeedFriend\(this.value\)"/);
  assert.match(html,/id="feedSearch"[^>]*oninput="setFeedSearch\(this.value\)"/);
});

test('a late old friend result cannot replace the newly selected friend',async()=>{
  const slow=deferred(),u=ui(feedTransport(path=>path.includes('friend_id=usr_old')?slow.promise:{events:[feedEvent(2)]}));
  const old=u.context.setFeedFriend('usr_old');
  await u.context.setFeedFriend('usr_target');
  slow.resolve({events:[feedEvent(1,'usr_old')]});await old;
  assert.equal(u.run('FEEDDATA[0].friend_id'),'usr_target');
  assert.match(u.el('feedPager').innerHTML,/近一年共 1 条/);
  assert.doesNotMatch(u.el('mobileFeed').innerHTML,/usr_old/);
});

test('a widget refresh preserves the main feed query and data',async()=>{
  const u=ui(feedTransport(path=>({events:[feedEvent(path==='/api/feed'?9:1)]})));
  await u.context.setFeedFriend('usr_target');
  const before=u.el('feedTable').innerHTML;
  await u.context.loadFeed('widget',1);
  assert.equal(u.run('FEEDDATA[0].id'),1);
  assert.equal(u.el('feedTable').innerHTML,before);
  assert.match(u.el('widget').innerHTML,/class="fitem"/);
});

test('a pending search does not execute after leaving its account context',async()=>{
  const calls=[],u=ui(feedTransport(()=>({events:[]}),calls));
  u.context.mobileFeedSearch('FixtureFriend');
  u.run("GA='b';GA_EPOCH++;APP.context.select('b')");
  await u.flush(250);assert.equal(calls.length,0);
});

test('a capped merged query reports displayed rows without claiming a complete total',async()=>{
  const events=Array.from({length:500},(_,i)=>feedEvent(i+1));
  const u=ui(feedTransport((path,url)=>({events:url.startsWith('/api/peer')?[]:events})));
  u.run("GA='m';GA_EPOCH++;APP.context.select('m')");
  await u.context.setFeedFriend('usr_target');
  assert.equal(u.run('FEEDDATA.length'),500);
  assert.match(u.el('feedPager').innerHTML,/近一年已显示 500 条/);
  assert.doesNotMatch(u.el('feedPager').innerHTML,/共 500 条/);
});

function pickerUI(transport){
  const u=ui(transport);
  u.run("APP.pages.register('feed',{merged:true});CURPAGE='feed';APP.pages.enter('feed');");
  return u;
}
test('phone bottom navigation selects a friend by ID, clears old filters, and returns to all activity',async()=>{
  const calls=[],all=Array.from({length:37},(_,i)=>feedEvent(i+1));
  const u=pickerUI(feedTransport(path=>({events:path==='/api/feed'?[feedEvent(99,'usr_other')]:all}),calls));
  u.run("FEEDFILTER='offline';STAR_ONLY=true;FEED_PAGE=3");u.el('feedSearch').value='old';u.el('mobileFeedSearch').value='old';
  await u.context.mobileGo('friendfeed');
  assert.match(u.el('mobileFeedFriendList').innerHTML,/FixtureFriend/);
  await u.context.chooseMobileFeedFriend('usr_target');
  assert.equal(u.run('FEED_FRIEND'),'usr_target');assert.equal(u.run('FEEDDATA.length'),37);
  assert.equal(u.run('FEEDFILTER'),'');assert.equal(u.run('STAR_ONLY'),false);assert.equal(u.run('FEED_PAGE'),0);
  assert.equal(u.el('feedSearch').value,'');assert.equal(u.el('mobileFeedSearch').value,'');
  assert.equal(u.el('mobileTitle').textContent,'单人动态');
  assert.match(u.el('mobileFeedSelection').innerHTML,/FixtureFriend/);
  assert.ok(u.el('moreSheet').classList.contains('hidden'));
  assert.ok(calls.includes('/api/history?days=365&friend_id=usr_target'));
  await u.context.mobileGo('feed');
  assert.equal(u.run('FEED_FRIEND'),'');assert.equal(u.run('FEEDDATA.length'),1);
  assert.ok(u.el('mobileFeedSelection').classList.contains('hidden'));
  assert.equal(u.el('mobileTitle').textContent,'好友动态');
});
test('the phone friend picker searches its roster and escapes names',async()=>{
  const u=pickerUI(async()=>({friends:[{id:'usr_one',name:'One <test>'},{id:'usr_two',name:'Two'}]}));
  await u.context.mobileFriendFeed();
  u.context.renderMobileFeedFriends('one');
  assert.match(u.el('mobileFeedFriendList').innerHTML,/One &lt;test&gt;/);
  assert.doesNotMatch(u.el('mobileFeedFriendList').innerHTML,/usr_two/);
  u.context.renderMobileFeedFriends('missing');assert.match(u.el('mobileFeedFriendList').innerHTML,/没有匹配的好友/);
  assert.equal(u.context.chooseMobileFeedFriend('usr_unknown'),undefined);
  assert.equal(u.run('FEED_FRIEND'),'');
});
test('the phone B picker and history both stay on B',async()=>{
  const calls=[],u=pickerUI(feedTransport(()=>({events:[feedEvent(1)]}),calls));
  u.run("GA='b';GA_EPOCH++;APP.context.select('b')");
  await u.context.mobileFriendFeed();await u.context.chooseMobileFeedFriend('usr_target');
  assert.ok(calls.every(url=>url.startsWith('/api/peer-relay?')));
  assert.ok(calls.some(url=>new URL(url,'https://fixture').searchParams.get('path')==='/api/history?days=365&friend_id=usr_target'));
  assert.equal(u.run('FEEDDATA[0]._src'),'b');
});
test('the merged phone picker queries the selected friend on both sources',async()=>{
  const calls=[],u=pickerUI(feedTransport(()=>({events:[feedEvent(1)]}),calls));
  u.run("GA='m';GA_EPOCH++;APP.context.select('m')");
  await u.context.mobileFriendFeed();await u.context.chooseMobileFeedFriend('usr_target');
  assert.ok(calls.includes('/api/history?days=365&friend_id=usr_target'));
  assert.ok(calls.some(url=>url.startsWith('/api/peer-relay?')&&new URL(url,'https://fixture').searchParams.get('path').includes('friend_id=usr_target')));
  assert.equal(u.run('FEEDDATA[0]._src'),'ab');
});
test('closing a phone picker drops late roster data instead of overwriting a different sheet',async()=>{
  const slow=deferred(),u=pickerUI(()=>slow.promise);
  const job=u.context.mobileFriendFeed();u.context.mbSheetsClose();u.el('moreGrid').innerHTML='another sheet';
  slow.resolve({friends:[{id:'usr_old',name:'Old'}]});await job;
  assert.equal(u.el('moreGrid').innerHTML,'another sheet');
  assert.equal(u.context.chooseMobileFeedFriend('usr_old'),undefined);
  assert.equal(u.run('FEED_FRIEND'),'');
});
test('switching accounts prevents old phone picker selection and removes the old selected name',async()=>{
  const slow=deferred(),u=pickerUI(()=>slow.promise);
  const job=u.context.mobileFriendFeed();u.el('mobileFeedSelection').innerHTML='old account friend';
  u.run("GA='b';GA_EPOCH++;APP.context.select('b');FEED_FRIEND='';MobileUI.refresh()");
  slow.resolve({friends:[{id:'usr_old',name:'Old'}]});await job;
  assert.equal(u.context.chooseMobileFeedFriend('usr_old'),undefined);
  assert.equal(u.el('mobileFeedSelection').innerHTML,'');
  assert.ok(u.el('mobileFeedSelection').classList.contains('hidden'));
});

test('login forms support phone autofill without saving service-side passwords',async()=>{
  const calls=[],u=ui(async(url,options)=>{
    calls.push({url,body:options?.body?JSON.parse(options.body):null});
    return {ok:true,message:'登录成功'};
  });
  u.run('refreshChrome=()=>{};loadAccount=()=>{};loadPeerAccount=()=>{};');
  u.el('username').value='account-a';u.el('password').value='test-password';
  await u.context.doLogin();
  u.el('p_username').value='account-b';u.el('p_password').value='test-password';
  await u.context.doPeerLogin();
  assert.equal(calls[0].url,'/api/login');assert.equal(calls[0].body.store,false);
  assert.equal(calls[1].url,'/api/peer-login');assert.equal(calls[1].body.store,false);
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  assert.match(html,/id="acctSelfLoginForm" class="row" autocomplete="on"/);
  assert.match(html,/id="password" name="password" type="password" autocomplete="current-password"/);
  assert.match(html,/id="code" name="code" autocomplete="one-time-code"/);
  assert.doesNotMatch(html,/保存密码用于自动重登/);
});

test('switching accounts cannot save an unloaded settings or push form',async()=>{
  let calls=0;const u=ui(async()=>{calls++;return {ok:true};});
  u.el('set-poll_seconds').value='99';u.context.saveSettings();await u.flush(600);await u.context.savePushCfg();
  assert.equal(calls,0);assert.match(u.el('pushSaveMsg').textContent,/尚未加载/);
});

test('shipped modal handlers discard a closed or superseded friend detail',async()=>{
  const slow=deferred(),u=ui(url=>url.includes('usr_old')?slow.promise:{user:{displayName:'new'},events:[]});
  u.run("renderUserShell=()=>{document.getElementById('mcard').textContent=UD.user.displayName;};");
  const old=u.context.openFriend('usr_old');u.context.closeModal();
  await u.context.openFriend('usr_new');slow.resolve({user:{displayName:'old'},events:[]});await old;
  assert.equal(u.el('mcard').textContent,'new');
  u.context.closeModal();assert.ok(u.el('modal').classList.contains('hidden'));
});
test('a malformed saved dashboard does not prevent page modules from loading',()=>{
  const u=ui(()=>({}),{dashboard:'{broken'});
  assert.equal(u.run('DASHS.length'),1);assert.equal(u.run('DASHS[0].widgets[0]'),'feed');
});
test('template event handlers refer to available shipped functions',()=>{
  const u=ui(()=>({}));
  const html=fs.readFileSync(path.join(ROOT,'../templates/index.html'),'utf8');
  const builtins=new Set(['if','for','switch','confirm','alert','setTimeout','Number','String','parseInt','Math']);
  const handlers=[...html.matchAll(/on(?:click|change|input|keydown|keyup|error)="([^"]*)"/g)];
  assert.ok(handlers.length>50);
  for(const [,handler] of handlers){
    for(const [,name] of handler.matchAll(/(?<![\w.])([A-Za-z_$][\w$]*)\s*\(/g)){
      if(builtins.has(name)) continue;
      assert.equal(u.run('typeof '+name),'function',`missing ${name}: ${handler}`);
    }
  }
});

test('friend opens its scoped list snapshot before a slow profile response',async()=>{
  const slow=deferred(),u=ui(()=>slow.promise);
  u.run("GA='m';APP.context.select('m');window._FRIENDS=[{id:'usr_shared',name:'Shared',_detailSource:'b',_accounts:{a:{name:'A'},b:{name:'B',state:'online'}}}];renderUserShell=()=>{document.getElementById('mcard').textContent=UD.user.displayName;};");
  const pending=u.context.openFriend('usr_shared');
  assert.equal(u.el('mcard').textContent,'B');assert.equal(u.run('DETAIL_CURRENT.account'),'b');
  u.context.closeModal();slow.resolve({user:{displayName:'late B'},events:[]});await pending;
  assert.equal(u.el('mcard').textContent,'B');
});
test('world note save uses the captured B source and accepts a completed response',async()=>{
  const calls=[],u=ui(async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true};});
  u.run("GA='b';APP.context.select('b');window._CURSRC='b';WD_DATA={world:{id:'wrld_one'}};");
  u.el('wnoteText').value='Room note';const button=element('save');
  await u.context.saveWorldNote(button);
  assert.equal(calls.length,1);assert.ok(calls[0].url.startsWith('/api/peer-relay-post'));
  assert.equal(u.run('WD_DATA.note'),'Room note');assert.equal(button.textContent,'已保存');
  assert.equal(button.disabled,false);
});

test('favorite group selection filters by stable API id rather than its label',async()=>{
  const u=ui(async()=>({groups:[{name:'group_1',displayName:'First'},{name:'group_2',displayName:'Second'}],items:[{group:'group_1',fid:'usr_1',name:'One'},{group:'group_2',fid:'usr_2',name:'Two'}]}));
  await u.context.loadFavorites();u.context.selectFavGroup('group_2');
  assert.equal(u.run('FAVGROUP'),'group_2');assert.equal(u.el('favSelName').textContent,'Second');
  assert.match(u.el('favItems').innerHTML,/Two/);assert.doesNotMatch(u.el('favItems').innerHTML,/One/);
  assert.equal(typeof u.context.renameGroup,'function');assert.equal(typeof u.context.clearGroup,'function');assert.equal(typeof u.context.removeFavorite,'function');
});

test('a B-only world in merged feed opens B even after an A detail was closed',async()=>{
  const calls=[],u=ui(async url=>{calls.push(url);return {world:{id:'wrld_one',name:'World'},stale:false};});
  u.run("GA='m';APP.context.select('m');window._CURSRC='a';renderWorldShell=()=>{};");
  await u.context.openWorld('wrld_one','b');assert.equal(u.run('DETAIL_CURRENT.account'),'b');
  assert.ok(calls[0].startsWith('/api/peer-relay?'));
  u.context.closeModal();assert.equal(u.context._CURSRC,null);
  assert.match(u.context.worldChipOf({location:'wrld_one:1',world_name:'World',_src:'b'}),/openInstance\(&quot;wrld_one:1&quot;,&quot;b&quot;\)/);
});

test('history links preserve complete room tags and safely pass quoted strings as data',()=>{
  const u=ui(()=>({})),loc='wrld_one:7~hidden(usr_owner)~region(jp)~nonce(a\'b"c)';
  const html=u.context.worldChipOf({location:loc,_src:'b',world_name:'History'});
  const handler=/onclick="([^"]*)"/.exec(html)[1].replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
  let got;u.context.openInstance=(...args)=>{got=args;};u.context.event={stopPropagation(){}};
  u.run(handler);assert.deepEqual(got,[loc,'b']);
});

test('room ownership follows location tags and the live instance owner, never the world author',()=>{
  const u=ui(()=>({}));
  u.context._FRIENDS=[{id:'usr_owner',_accounts:{a:{name:'A name'},b:{name:'B name'}}}];
  assert.equal(u.context.roomFacts('wrld_one:7~hidden(usr_owner)',{},'b').name,'B name');
  assert.equal(u.context.roomFacts('wrld_one:7~private(usr_one)~canRequestInvite').label,'邀请+');
  assert.equal(u.context.roomFacts('wrld_one:7~private(usr_one)').label,'仅限邀请');
  assert.equal(u.context.roomFacts('wrld_one:7~friends(usr_one)').label,'仅限好友');
  const group=u.context.roomFacts('wrld_one:7~group(grp_one)~region(eu)');
  assert.equal(group.kind,'group');assert.equal(group.id,'grp_one');assert.equal(group.region,'eu');
  assert.equal(u.context.roomFacts('wrld_one:7~hidden(usr_one)',{creator_id:'usr_other'}).id,'usr_other');
  assert.equal(u.context.roomFacts('wrld_one:7',{author:'world author'}).id,'');
  assert.equal(u.context.roomFacts('wrld_one:7',{creator_id:"usr_bad');alert(1)"}).id,'');
});

test('an offline friend keeps a room-detail entry and stale occupancy is not shown as current',()=>{
  const u=ui(()=>({}));u.run("window._CURSRC='b';UD={user:{state:'offline'},last_room:{world:'Old Room',location:'wrld_one:7~hidden(usr_owner)',ts:1700000000}};");
  const html=u.context.userRoomHTML({world:{name:'Old Room',thumb:'https://assets.vrchat.com/world.png'}},{stale:true,live:{user_count:9}});
  assert.match(html,/openInstance\(&quot;wrld_one:7~hidden\(usr_owner\)&quot;,&quot;b&quot;\)/);
  assert.match(html,/最后记录位置/);assert.match(html,/房间建立者/);
  assert.match(html,/loading="eager"/);assert.doesNotMatch(html,/>9 人/);
});

test('a friend world image renders before a slow room request completes',async()=>{
  const slow=deferred(),calls=[],u=ui(async url=>{
    calls.push(url);return url.startsWith('/api/instance')?slow.promise:{world:{name:'Fast World',thumb:'https://assets.vrchat.com/world.png'},stale:false};
  });
  u.run("CURUSER='usr_one';window._CURSRC='a';UD={user:{state:'offline'},last_room:{location:'wrld_one:7~hidden(usr_owner)'}};");
  const job=u.run("loadUserRoom(APP.tasks.begin('modal'))");
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(u.el('userRoom').innerHTML,/world.png/);assert.match(u.el('userRoom').innerHTML,/Fast World/);
  assert.ok(calls.some(url=>url.startsWith('/api/instance')));
  slow.resolve({live:null,stale:false});await job;
});

test('an instance world image does not wait for its owner and old owner results cannot reopen a detail',async()=>{
  const owner=deferred(),room=deferred(),u=ui(async url=>{
    if(url.startsWith('/api/friend?'))return owner.promise;
    if(url.startsWith('/api/instance?'))return room.promise;
    return {world:{name:'Fast World',thumb:'https://assets.vrchat.com/world.png'},stale:false};
  });
  const job=u.context.openInstance('wrld_one:7~hidden(usr_owner)');
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(u.el('mcard').innerHTML,/world.png/);assert.match(u.el('mcard').innerHTML,/房间建立者/);
  room.resolve({world:{name:'World',thumb:'https://assets.vrchat.com/old-world.png'},live:{creator_id:'usr_owner',user_count:0},stale:false});await job;
  assert.match(u.el('mcard').innerHTML,/>0<\/span>/);
  assert.doesNotMatch(u.el('mcard').innerHTML,/old-world.png/);
  u.context.closeModal();u.el('mcard').innerHTML='new detail';
  owner.resolve({user:{id:'usr_owner',displayName:'Late owner'}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(u.el('mcard').innerHTML,'new detail');
});

test('an unavailable historical B room still resolves its creator through B and finishes the pending count',async()=>{
  const calls=[],loc='wrld_one:7~private(usr_owner)~region(jp)~nonce(saved)',u=ui(async url=>{
    const p=new URL(url,'https://fixture').searchParams.get('path');calls.push(p);
    if(p.startsWith('/api/friend?'))return {user:{id:'usr_owner',displayName:'Room Owner'},stale:false};
    if(p.startsWith('/api/world?'))return {world:{name:'Recorded World'},stale:false};
    return {world:{name:'Recorded World'},live:null,stale:true};
  });
  u.run("GA='m';APP.context.select('m')");
  await u.context.openInstance(loc,'b');await new Promise(resolve=>setImmediate(resolve));
  assert.match(u.el('mcard').innerHTML,/Room Owner/);assert.match(u.el('mcard').innerHTML,/仅限邀请/);
  assert.ok(calls.includes('/api/instance?location='+encodeURIComponent(loc)));
  assert.ok(calls.includes('/api/friend?id=usr_owner'));
  for(let i=0;i<10;i++){await u.flush(2000);await new Promise(resolve=>setImmediate(resolve));}
  assert.doesNotMatch(u.el('mcard').innerHTML,/查询中…/);
  assert.match(u.el('mcard').innerHTML,/未能获取/);
  assert.match(u.el('mcard').innerHTML,/当前房间状态未确认/);
});

test('a profile with no photo still renders the same-account roster fallback',()=>{
  const u=ui(()=>({}));
  u.run("UD={user:{id:'usr_one',displayName:'One',_avatar_fallback:'https://example.test/roster.png'},events:[],heat:[]};renderUserShell();");
  assert.match(u.el('mcard').innerHTML,/class="uavatar" loading="lazy" onerror="IMAGES.failed\(this\)" data-media-url="https:\/\/example.test\/roster.png" data-media-account="a"/);
  assert.match(u.el('mcard').innerHTML,/正在使用的模型/);
});

test('photo fallback is owned by each image and detached errors do not change the new image',()=>{
  const u=ui(()=>({})),old=element('old'),current=element('current');
  const applied=[];u.context.IMAGES.setURL=(image,url)=>applied.push([image,url]);
  old.dataset={photos:JSON.stringify(['old.png','old-fallback.png']),photoIndex:'0'};
  current.dataset={photos:JSON.stringify(['current.png','current-fallback.png']),photoIndex:'0'};
  old.isConnected=false;u.context.detailPhotoError(old);
  assert.equal(old.dataset.photoIndex,'0');assert.equal(current.dataset.photoIndex,'0');
  u.context.detailPhotoError(current);assert.deepEqual(applied,[[current,'current-fallback.png']]);
  assert.equal(old.dataset.photoIndex,'0');
});

test('session labels use verified duration, preserve zero and identify web sessions',()=>{
  const u=ui(()=>({}));
  assert.match(u.context.sessionDurationText({duration:62340,session_duration:40754}),/本次在线时长 11小时19分/);
  assert.match(u.context.sessionDurationText({duration:900,session_duration:null}),/未确认/);
  assert.match(u.context.sessionDurationText({duration:0,session_duration:0,prev_state:'active'}),/网页 · 本次在线时长/);
  assert.doesNotMatch(u.context.sessionDurationText({duration:0,session_duration:0}),/未确认/);
});

const decodeAttribute=value=>value.replace(/&(amp|lt|gt|quot|#39);/g,(_,key)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[key]));
test('friend deletion keeps hostile display names as data rather than executable script',()=>{
 const name="');globalThis.injected=1;//",u=ui(()=>({})),calls=[];
 u.context._FLTB=[{id:'usr_fixture',name,trust:{},online:false}];
 u.context.renderFriendTable();
 const button=u.el('fltBody').innerHTML.match(/<button[^>]*data-friend-id[^>]*>/)[0];
 const attribute=key=>decodeAttribute(button.match(new RegExp(key+'="([^"]*)"'))[1]);
 u.context.clicked={dataset:{friendId:attribute('data-friend-id'),friendName:attribute('data-friend-name')}};
 u.context.deleteFriend=(...args)=>calls.push(args);
 u.run('(function(){'+attribute('onclick')+'}).call(clicked)');
 assert.deepEqual(calls,[['usr_fixture',name]]);assert.equal(u.context.injected,undefined);
});
test('leaving a group keeps its hostile name in the confirmation text and respects cancel',async()=>{
 const name="x'));globalThis.injected=1;//",u=ui(url=>({group:{id:'grp_fixture',name}})),prompts=[],writes=[];
 await u.context.openGroup('grp_fixture');
 const button=u.el('mcard').innerHTML.match(/<button[^>]*data-group-id[^>]*>/)[0];
 const attribute=key=>decodeAttribute(button.match(new RegExp(key+'="([^"]*)"'))[1]);
 u.context.clicked={dataset:{groupId:attribute('data-group-id'),groupName:attribute('data-group-name')}};
 u.context.confirm=text=>{prompts.push(text);return false;};u.context.leaveGroup=id=>writes.push(id);
 u.run('(function(){'+attribute('onclick')+'}).call(clicked)');
 assert.deepEqual(prompts,[`确认退出群组「${name}」？此操作同步到 VRChat。`]);
 assert.equal(writes.length,0);assert.equal(u.context.injected,undefined);
});
