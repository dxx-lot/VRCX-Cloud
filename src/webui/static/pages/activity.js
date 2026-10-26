/* ---------- 仪表盘 / 状态 ---------- */

async function loadStatus(){

  try{

    const s = await gGet('/api/status');
    const statuses=GA==='m'
      ? ['a','b'].map(account=>({account,value:s._accounts?.[account]}))
      : [{account:GA==='b'?'b':'a',value:s}];
    const label=({account,value})=>VRCXRuntime.loginLabel(value,s._errors?.[account]);
    statuses.forEach(({account,value})=>{if(label({account,value})!=='已登录') syncAccountIdentity(account,null);});
    document.getElementById('sideDot').classList.toggle('on', statuses.some(({value})=>value?.logged_in===true));
    document.getElementById('sideState').textContent = statuses.map(item=>
      GA==='m'?`${GA_NAMES[item.account]} ${label(item)}`:label(item)).join(' · ');

    if (CURPAGE !== 'dash') return;

    const ws = s.watch_source;

  }catch(e){
    if(VRCXRuntime.ignored(e)) return;
    const dot=document.getElementById('sideDot');if(dot)dot.classList.remove('on');
    const state=document.getElementById('sideState');if(state)state.textContent='登录异常';
    if(!VRCXRuntime.ignored(e)){
      (GA==='m'?['a','b']:[GA]).forEach(account=>syncAccountIdentity(account,null));console.error(e);
    }
  }

}

async function loadSelf(){

  const myE = GA_EPOCH;

  try{

    const s = await gGet('/api/self');

    if (myE !== GA_EPOCH) return;   // 旧视角响应丢弃

    const card = document.getElementById('selfCard');

    const scS = document.getElementById('scSingle'), scM = document.getElementById('scMerge');

    // 合并视角：左上角同时显示两个号（各带来源标）；写状态控件仍用账号A值

    if (GA==='m'){
      ['a','b'].forEach(account=>syncAccountIdentity(account,s._accounts?.[account]));

      const ps = {peer:s._accounts?.b};

      card.style.display = 'flex';
      card.style.cursor = 'default';card.onclick=null;card.removeAttribute('tabindex');

      scS.style.display = 'none'; scM.classList.remove('hidden');

      const line = (tag, d) =>d && d._auth_state!=='error' && !d.error && d.logged_in !== false && d.name

        ? `<div style="display:flex;gap:8px;align-items:center;min-width:0">${ovSrcTag(tag)}`+

          `${d.thumb?`<img ${mediaAttrs(d.thumb,tag,'high')} style="width:34px;height:34px;border-radius:6px;object-fit:cover">`:'<img>'}`+

          `<div style="min-width:0"><div class="n">${esc(d.name||'')}</div>`+

          `<div class="l">${d.state==='online'?esc(d.world||'在线'):d.state==='active'?'活跃中（仅登录网页端）':'离线'}</div></div></div>`

        : `<div style="display:flex;gap:8px;align-items:center">${ovSrcTag(tag)}<span class="l">${esc(GA_NAMES[tag])} ${VRCXRuntime.LOGIN_ERROR}</span></div>`;

      scM.innerHTML = line('a', s._accounts?.a) + `<div style="height:6px"></div>` + line('b', ps.peer||ps);

      return;

    }

    scS.style.display = 'flex'; scM.classList.add('hidden');
    card.style.cursor = 'pointer';card.onclick=goDashSelf;card.setAttribute?.('tabindex','0');
    syncAccountIdentity(GA,s);
    if(VRCXRuntime.loginLabel(s)!=='已登录'){
      card.style.display='flex'; card.onclick=showLogin;
      document.getElementById('selfName').textContent=GA_NAMES[GA];
      document.getElementById('selfLoc').textContent=VRCXRuntime.LOGIN_ERROR;
      IMAGES.clear(document.getElementById('selfThumb'));
      document.getElementById('selfPanel').style.display='none';
      return;
    }

    card.style.display = 'flex';

    IMAGES.setURL(document.getElementById('selfThumb'),s.thumb||'',GA,'high');

    document.getElementById('selfName').textContent = s.name || '';

    document.getElementById('selfLoc').textContent =

      (s.state==='online' ? (s.world || '在线') : s.state==='active' ? '活跃中（仅登录网页端）' : '离线')

      + (s.instance_label ? ` · ${s.instance_label}` : '');

    // 我的状态控件预选当前值（空白下拉=看不出当前状态；正输入的字段不覆盖）

    const ms = document.getElementById('myStatus');

    if (ms && document.activeElement !== ms){

      const v = s.status||'';

      if ([...ms.options].some(o=>o.value===v)) ms.value = v;

    }

    const md = document.getElementById('myDesc');

    if (md && document.activeElement !== md) md.value = s.desc || '';

    const panel = document.getElementById('selfPanel');

    panel.style.display = 'block';



  }catch(e){
    if(!VRCXRuntime.ignored(e) && myE===GA_EPOCH){
      (GA==='m'?['a','b']:[GA]).forEach(account=>syncAccountIdentity(account,null));
      document.getElementById('selfPanel').style.display='none';
      reportError(e);
    }
  }

}

async function saveMyStatus(){

  const r = await gPost('/api/set-status', {status: document.getElementById('myStatus').value,

    desc: document.getElementById('myDesc').value});

  document.getElementById('myStatusMsg').textContent = r.ok ? ' 已生效' : ' '+(r.error||'失败');

  setTimeout(()=>document.getElementById('myStatusMsg').textContent='', 2500);

}

/* ---------- 动态 ---------- */

const EV_LABEL = {online:'上线', offline:'下线', location:'位置变动',

  active:'网页在线', status:'状态变动', desc:'简介变更', avatar:'模型变动'};

const EV_BADGE = {online:'badge-online', offline:'badge-offline', location:'badge-location',

  active:'badge-active', status:'badge-status', desc:'badge-desc', avatar:'badge-avatar'};

const STATUS_LABEL = {active:'在线', 'join me':'Join Me', 'ask me':'Ask Me', busy:'勿扰'};

function WEB_OFFLINE_LABEL(e){

  return e.event==='offline' && e.prev_state==='active' ? ' 网页下线' : (EV_LABEL[e.event]||e.event);

}

/* 状态点配色 = 上游 status-icon.css 变量原值（--status-online 等） */

function statusDotC(s){

  s = (s||'').toLowerCase().replace(/_/g,' ');

  return {active:'#2ed319','join me':'#00b8ff','ask me':'#e97c03',busy:'#c80928'}[s]||'#737f8d';

}

function worldChipOf(e){
  const loc=e.location||'',wid=loc.split(':')[0];
  if(!wid.startsWith('wrld_')) return `<span class="dim">${esc(VRCXFeed.locationText(e))}</span>`;
  const action=loc.includes(':')?`openInstance(${JSON.stringify(loc)},${JSON.stringify(e._src||'')})`:`openWorld(${JSON.stringify(wid)},${JSON.stringify(e._src||'')})`;
  return `<button class="chip click" title="${esc(e.world_name||'世界信息未缓存')}" onclick="event.stopPropagation();${esc(action)}">${esc(e.world_name||'世界信息未缓存')}</button>`+(e.instance_label?`<span class="chip">${esc(e.instance_label)}</span>`:'');
}

function sessionDurationText(e){
  const value=Object.hasOwn(e,'session_duration')?e.session_duration:e.duration;
  return `${e.prev_state==='active'?'网页 · ':''}本次在线时长 ${value!=null?fmtDur(value):'未确认'}`;
}

const EV_COLOR = {online:'#16a34a',offline:'#ef4444',location:'#0369a1',

  active:'#2563eb',status:'#b45309',desc:'#6d28d9',avatar:'#be185d'};

function feedItemSimple(e){  /* 仪表板速览用 */

  const label = e.event==='offline'&&e.prev_state==='active' ? ' 网页下线' : (WEB_OFFLINE_LABEL(e));

  const color = EV_COLOR[e.event]||'#64748b';

  const detail = e.event==='offline'

    ? `${sessionDurationText(e)}${e.world_name?' · 最后位置 '+esc(e.world_name):''}`

    : e.event==='active' ? '网页在线（未进世界）'

    : e.event==='status' ? esc(e.status_description||'')

    : e.event==='desc' ? esc((e.status_description||'').slice(0,20))

    : e.event==='avatar' ? '模型变动'

    : esc(e.world_name||'');

  return `<div class="fitem"><span class="ftime">${e._src?ovSrcTag(e._src):''}${fmtTs(e.ts)}</span>`+

    `<span class="chip" style="color:${color};border-color:${color}">${label}</span>`+

    `<span>${detail}</span></div>`;

}

let FEED_SORT_DESC = true, STAR_ONLY = false, FEED_PAGE = 0;

let FEED_FRIEND = '';   // 动态页单人筛选：选中的 friend_id（空=全部）

let FEED_SEARCH_TIMER = null, FEED_LOADED_QUERY = null;
let FEED_SCOPE_FILTERED = false, FEED_SCOPE_CAPPED = false;

function feedRequest(){
  const name = v('feedSearch'), params = ['days=365'];
  if (FEED_FRIEND) params.push('friend_id='+encodeURIComponent(FEED_FRIEND));
  if (name) params.push('name='+encodeURIComponent(name));
  if (FEEDFILTER) params.push('type='+encodeURIComponent(FEEDFILTER));
  const filtered = params.length > 1;
  return {path:filtered ? '/api/history?'+params.join('&') : '/api/feed', filtered};
}

function feedQueryKey(request=feedRequest()){
  return `${GA}|${GA_EPOCH}|${request.path}`;
}

function feedCountText(total){
  if (!FEED_SCOPE_FILTERED) return `近期记录中 ${total} 条`;
  if (STAR_ONLY) return `近一年记录中 ${total} 条`;
  return `${FEED_SCOPE_CAPPED ? '近一年已显示' : '近一年共'} ${total} 条`;
}

function renderFeedMessage(message){
  document.getElementById('feedTable').innerHTML = `<tr><td colspan="5" class="dim">${esc(message)}</td></tr>`;
  document.getElementById('feedPager').textContent = '';
  const mobile = document.getElementById('mobileFeed');
  if (mobile) mobile.innerHTML = `<div class="mobile-empty">${esc(message)}</div>`;
}

function reloadFeedFilter(delay=0){
  if (FEED_SEARCH_TIMER) { clearTimeout(FEED_SEARCH_TIMER); FEED_SEARCH_TIMER = null; }
  APP.tasks.cancel('feed:feed');
  const pending = APP.tasks.begin('feed:filter');
  FEED_PAGE = 0;
  renderFeed();
  if (!delay) return loadFeed();
  FEED_SEARCH_TIMER = setTimeout(()=>{
    FEED_SEARCH_TIMER = null;
    if (pending.current()) return loadFeed();
  },delay);
}

function setFeedFriend(id){
  FEED_FRIEND = id;
  if(typeof renderMobileFeedSelection==='function')renderMobileFeedSelection();
  return reloadFeedFilter();
}

function setFeedSearch(value){
  document.getElementById('feedSearch').value = value;
  return reloadFeedFilter(250);
}

function toggleStar(){

  STAR_ONLY = !STAR_ONLY;
  if (STAR_ONLY && !window._WATCH_IDS) loadFeed();

  document.getElementById('starBtn').classList.toggle('active', STAR_ONLY);

  FEED_PAGE = 0; renderFeed();

}

function toggleFeedSort(){

  FEED_SORT_DESC = !FEED_SORT_DESC;

  document.getElementById('feedSortIcon').textContent = FEED_SORT_DESC ? '▼' : '▲';

  renderFeed();

}

function feedDetailCell(e){

  if (e.event==='online') return '<span style="color:#16a34a;font-weight:600">游戏内</span>· ' + (worldChipOf(e)||'<span class="dim">—</span>');

  if (e.event==='location') return '<span style="color:#0369a1;font-weight:600">前往</span>' + (worldChipOf(e)||'<span class="dim">—</span>');

  if (e.event==='offline'){

    const web = e.prev_state==='active';

    return `<span style="color:${web?'#f59e0b':'#ef4444'};font-weight:600">${web?' 网页下线':' 下线'}</span> · ` + sessionDurationText(e) + ' · ' + ((e.world_name||e.location==='private') ? (worldChipOf(e)||'<span class="dim">位于私人房间</span>') : '<span class="dim">—</span>');

  }

  if (e.event==='active') return '<span style="color:#2563eb;font-weight:600">网页在线</span>'+((e.prev_state==='online'||e.previous)?' · 已离开游戏':' · 未进世界');

  if (e.event==='status'){

    if ((e.previous_desc||'') === (e.status_description||'')){

      return `<span style="color:${statusDotC(e.previous)}">●</span> <span style="color:${statusDotC(e.previous)};font-weight:600">${esc(STATUS_LABEL[e.previous]||e.previous||'?')}</span><span class="dim" style="margin:0 5px">→</span><span style="color:${statusDotC(e.status)}">●</span> <span style="color:${statusDotC(e.status)};font-weight:600">${esc(STATUS_LABEL[e.status]||e.status||'?')}</span>`;

    }

    return `<span style="color:${statusDotC(e.status)}">●</span> <span style="color:${statusDotC(e.status)};font-weight:600">${esc(STATUS_LABEL[e.status]||e.status||'?')}</span> <span class="dim">${esc((e.status_description||'').slice(0,42))}</span>`;

  }

  if (e.event==='desc') return `<span class="dim">${esc((e.status_description||'').slice(0,42))}</span>`;

  if (e.event==='avatar'){

    return `<img ${mediaAttrs(e.previous||'',e._src||GA)} style="width:26px;height:26px;border-radius:6px;object-fit:cover;vertical-align:middle">`+

      `<span class="dim" style="margin:0 4px">→</span>`+

      `<img ${mediaAttrs(e.location||'',e._src||GA)} style="width:26px;height:26px;border-radius:6px;object-fit:cover;vertical-align:middle">`;

  }

  return '';

}

function feedExpandRow(e){

  const wid = (e.location||'').split(':')[0];

  let inner = '';

  if (e.event==='location' || e.event==='online'){

    inner = (e.previous?`<div><span class="dim">之前:</span> <span class="chip">${esc(e.previous)}</span></div><div class="dim" style="margin:2px 0">↓</div>`:'')+

      (worldChipOf(e)||'<span class="dim">—</span>');

  } else if (e.event==='offline'){

    inner = worldChipOf(e)+

      ` <span class="chip">${sessionDurationText(e)}</span>`;

  } else if (e.event==='status'){

    inner = `<div><span style="color:${statusDotC(e.previous)}">●</span> <span style="color:${statusDotC(e.previous)};font-weight:600">${esc(STATUS_LABEL[e.previous]||e.previous||'?')}</span>${e.previous_desc?' <span class="dim">· '+esc(e.previous_desc)+'</span>':''}</div>`+

      `<div class="dim" style="margin:3px 0">↓</div>`+

      `<div><span style="color:${statusDotC(e.status)}">●</span> <span style="color:${statusDotC(e.status)};font-weight:600">${esc(STATUS_LABEL[e.status]||e.status||'?')}</span>${e.status_description?' <span class="dim">· '+esc(e.status_description)+'</span>':''}</div>`;

  } else if (e.event==='desc'){

    inner = `<div><span class="dim">旧:</span>${esc((e.previous||'—')).slice(0,90)}</div>`+

      `<div class="dim" style="margin:3px 0">↓</div>`+

      `<div><span class="dim">新:</span>${esc((e.status_description||'—')).slice(0,90)}</div>`;

  } else if (e.event==='active'){

    inner = '<span class="dim">网页在线（未进世界）</span>'+

      (e.previous?`<div class="dim" style="margin-top:4px">离开世界: ${esc(e.previous)}</div>`:'')+

      (e.status_description?`<div class="dim" style="margin-top:4px">签名: ${esc(e.status_description)}</div>`:'');

  } else if (e.event==='avatar'){

    inner = `<div class="row" style="align-items:flex-start">`+

      `<div style="text-align:center"><img ${mediaAttrs(e.previous||'',e._src||GA)} style="width:96px;height:96px;border-radius:10px;object-fit:cover"><div class="dim" style="font-size:11px">之前</div></div>`+

      `<span style="margin:40px 10px 0">→</span>`+

      `<div style="text-align:center"><img ${mediaAttrs(e.location||'',e._src||GA)} style="width:96px;height:96px;border-radius:10px;object-fit:cover"><div class="dim" style="font-size:11px">现在</div></div></div>`;

  }

  return `<div style="background:var(--hov);border-radius:8px;padding:8px 12px;margin:2px 0 6px 8px;font-size:12.5px" onclick="event.stopPropagation()">${inner}`+

    `<div class="row" style="margin-top:6px"><span class="dim">${new Date(e.ts*1000).toLocaleString('zh-CN')}</span>`+

    (wid&&wid.startsWith('wrld_')?`<button class="ghost mini" onclick="openWorld('${esc(wid)}','${e._src||''}')">世界详情</button>`:'')+
    (wid&&wid.startsWith('wrld_')&&(e.location||'').includes(':')?`<button class="ghost mini" onclick="${esc(`openInstance(${JSON.stringify(e.location)},${JSON.stringify(e._src||'')})`)}">房间详情</button>`:'')+

    (e.location?`<button class="ghost mini" onclick="${esc(`copyText(${JSON.stringify(e.location)})`)}">复制 location</button>`:'')+

    (e.friend_id?`<button class="ghost mini" onclick="openFriend('${esc(e.friend_id)}','${e._src||''}')">用户详情</button>`:'')+

    `</div></div>`;

}

function toggleFeedDetail(i){ document.getElementById('fdr'+i).classList.toggle('hidden'); }

function copyText(t){ if (navigator.clipboard) navigator.clipboard.writeText(t); }

function setFeedFilter(btn){

  FEEDFILTER = btn.dataset.f;

  document.querySelectorAll('#feedFilter [data-f],#mobileFeedFilter [data-f]').forEach(b=>b.classList.toggle('active', b.dataset.f===FEEDFILTER));

  return reloadFeedFilter();

}

async function loadFeed(target='feed', limit=null){
  const request = target==='feed' ? feedRequest() : {path:'/api/feed',filtered:false};
  const queryKey = feedQueryKey(request);
  const task = APP.tasks.begin('feed:'+target);
  const current = ()=>task.current() && (target!=='feed' || queryKey===feedQueryKey());
  if (target==='feed' && FEED_SEARCH_TIMER){
    clearTimeout(FEED_SEARCH_TIMER); FEED_SEARCH_TIMER = null;
    APP.tasks.cancel('feed:filter');
  }
  let freshnessLoaded = false;
  try {
    const r = await gGet(request.path);
    if (!current()) return;
    const events = VRCXFeed.normalize(r.events, GA==='m' ? undefined : GA);
    if (target!=='feed'){
      const el = document.getElementById(target);
      if (el) el.innerHTML = events.slice(0,limit||8).map(feedItemSimple).join('') || '<div class="dim">暂无动态</div>';
      showPartial(r);
      return;
    }
    FEEDDATA = events;
    FEED_LOADED_QUERY = queryKey;
    FEED_SCOPE_FILTERED = request.filtered;
    const sources = GA==='m' ? Object.values(r._accounts||{}) : [r];
    FEED_SCOPE_CAPPED = sources.some(source=>(source?.events?.length||0)>=500);
    renderFeedFreshness(r); freshnessLoaded = true;
    renderFeed();
    const sel = document.getElementById('feedFriendSel');
    if (sel && sel.dataset.ga !== GA) {
      const fr = await gGet('/api/friends');
      if (!current()) return;
      window._FRIENDS = fr.friends || [];
      sel.innerHTML = '<option value="">全部好友</option>';
      for (const f of [...(fr.friends||[])].sort((a,b)=>(a.name||'').localeCompare(b.name||''))) {
        const o = document.createElement('option'); o.value=f.id; o.textContent=f.name||f.id; sel.appendChild(o);
      }
      sel.dataset.ga=GA;
      if (FEED_FRIEND && !(fr.friends||[]).some(f=>f.id===FEED_FRIEND)){
        const o = document.createElement('option'); o.value=FEED_FRIEND;
        o.textContent=events.find(e=>e.friend_id===FEED_FRIEND)?.display_name||FEED_FRIEND;
        sel.appendChild(o);
      }
      sel.value=FEED_FRIEND; sel.style.display=GA==='m' ? 'none' : '';
    }
    if (STAR_ONLY && !window._WATCH_IDS) {
      const status = await gGet('/api/status');
      if (!current()) return;
      const sources = GA==='m' ? Object.values(status._accounts||{}) : [status];
      window._WATCH_IDS = [...new Set(sources.flatMap(s=>s?.watch_source?.ids||[]))];
    }
    renderFeed();
    showPartial(r);
  } catch(e) {
    if (!current()) return;
    if (target==='feed' && !freshnessLoaded){
      renderFeedFreshness(null);
      renderFeedMessage('动态加载失败，请稍后重试');
    }
    reportError(e);
  }
}

function feedAgeText(seconds){
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes < 1) return '不足1分钟';
  if (minutes < 60) return `${minutes}分钟`;
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  if (hours < 24) return `${hours}小时${rest ? `${rest}分钟` : ''}`;
  const days = Math.floor(hours / 24), restHours = hours % 24;
  return `${days}天${restHours ? `${restHours}小时` : ''}`;
}

function renderFeedFreshness(payload){
  const el = document.getElementById('feedFreshness');
  if (!el) return;
  const sources = GA === 'm'
    ? ['a','b'].map(account => ({account, snapshot: payload?._accounts?.[account]}))
    : [{account: GA === 'b' ? 'b' : 'a', snapshot: payload}];
  let issue = false;
  const lines = sources.map(({account, snapshot})=>{
    const label = account === 'a' ? 'A 号' : 'B 号';
    if (!snapshot) { issue = true; return `${label}同步状态暂不可读`; }
    if (snapshot.logged_in===false) { issue = true; return `${label}登录异常`; }
    const lastSync = Number(snapshot.last_sync);
    if (snapshot.last_sync == null || !Number.isFinite(lastSync) || lastSync <= 0){
      issue = true;
      return `${label}暂无采集记录`;
    }
    const serverNow = Number(snapshot.server_now);
    const now = Number.isFinite(serverNow) && serverNow > 0 ? serverNow : Date.now() / 1000;
    const age = Math.max(0, now - lastSync);
    const stamp = new Date(lastSync * 1000).toLocaleString('zh-CN', {
      year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false
    });
    if (age >= 180){
      issue = true;
      return `${label}数据已超过${feedAgeText(age)}未更新（上次采集：${stamp}）`;
    }
    return `${label}最近采集：${stamp}`;
  });
  el.textContent = lines.join('；');
  el.style.color = issue ? '#b45309' : 'var(--dim)';
  el.style.borderLeftColor = issue ? 'var(--yellow)' : 'transparent';
}

function renderFeed(){
  if (FEED_LOADED_QUERY !== feedQueryKey()){
    renderFeedMessage('正在查询符合筛选的动态…');
    return;
  }
  FEEDDATA = VRCXFeed.normalize(FEEDDATA);
  let list = FEEDDATA.map((e,i)=>({e,i}));

  if (FEEDFILTER==='web_offline') list = list.filter(x=>x.e.event==='offline' && x.e.prev_state==='active');
  else if (FEEDFILTER==='offline') list = list.filter(x=>x.e.event==='offline' && x.e.prev_state!=='active');
  else if (FEEDFILTER) list = list.filter(x=>x.e.event===FEEDFILTER);

  if (FEED_FRIEND) list = list.filter(x=>x.e.friend_id===FEED_FRIEND);

  if (STAR_ONLY){

    const ids = new Set(window._WATCH_IDS||[]);

    list = list.filter(x=>ids.has(x.e.friend_id));

  }

  const q = (v('feedSearch')||'').toLowerCase();

  if (q) list = list.filter(x=>(x.e.display_name||'').toLowerCase().includes(q));

  list.sort((a,b)=>FEED_SORT_DESC ? b.e.ts-a.e.ts : a.e.ts-b.e.ts);

  const size = +(v('feedPageSize')||20);

  const pages = Math.max(1, Math.ceil(list.length/size));

  if (FEED_PAGE >= pages) FEED_PAGE = pages-1;

  const pageRows = list.slice(FEED_PAGE*size, (FEED_PAGE+1)*size);

  document.getElementById('feedTable').innerHTML = pageRows.map(({e,i})=>

    `<tr class="feed-row"><td style="cursor:pointer;color:var(--dim)" onclick="toggleFeedDetail(${i})">▸</td>`+

    `<td class="dim">${fmtTs(e.ts)}</td>`+

    `<td><span class="chip big ${EV_BADGE[e.event]||''}">${WEB_OFFLINE_LABEL(e)}</span></td>`+

    `<td><div class="feed-player">${e._src?ovSrcTag(e._src):''}<span class="name" title="${esc(e.display_name)}" style="cursor:pointer" onclick="event.stopPropagation();openFriend('${esc(e.friend_id||'')}','${e._src||''}')">${esc(e.display_name)}</span>${srcChip(e._src)}</div></td>`+

    `<td>${feedDetailCell(e)}</td></tr>`+

    `<tr id="fdr${i}" class="hidden"><td></td><td colspan="4">${feedExpandRow(e)}</td></tr>`

  ).join('') || '<tr><td colspan="5" class="dim">暂无动态</td></tr>';

  let pg = '';

  for (let p=0; p<pages; p++){

    if (pages>7 && p>2 && p<pages-3 && Math.abs(p-FEED_PAGE)>2){

      if (p===3) pg += '<span class="dim">…</span>';

      continue;

    }

    pg += `<button class="mini ${p===FEED_PAGE?'':'ghost'}" onclick="FEED_PAGE=${p};renderFeed()">${p+1}</button>`;

  }

  document.getElementById('feedPager').innerHTML =

    `<span class="dim" style="font-size:12px;margin-right:6px">${feedCountText(list.length)}</span>`+

    (pages>1?`<button class="ghost mini" onclick="if(FEED_PAGE>0){FEED_PAGE--;renderFeed()}">‹</button>${pg}`+

      `<button class="ghost mini" onclick="if(FEED_PAGE<${pages-1}){FEED_PAGE++;renderFeed()}">›</button>`:'');
  if(typeof renderMobileFeed==='function') renderMobileFeed(pageRows,list.length,size);

}

/* ---------- 好友 ---------- */

let LISTFILTER = '';

function setListFilter(f){

  LISTFILTER = (LISTFILTER === f) ? '' : f;

  renderFriends(window._FRIENDS || []);

}

async function loadFriends(){

  try{

    const myE0 = GA_EPOCH;

    const r = await gGet('/api/friends');

    if (myE0 !== GA_EPOCH) return;

    window._FRIENDS = r.friends || [];

    renderFriends(r.friends);

  }catch(e){ reportError(e); }

}

function summaryRow(k, label, n){

  return `<tr onclick="setListFilter('${k}')" style="cursor:pointer"`+

    (LISTFILTER===k?' style="cursor:pointer;background:var(--hov)"':'')+

    `><td>${label}</td><td style="text-align:right;font-weight:700">${n}</td></tr>`;

}

function renderFriends(all){

  const q = v('fq').toLowerCase();

  let list = all.filter(f=>!q || (f.name||'').toLowerCase().includes(q));

  const inN = all.filter(f=>f.online && !f.web_online).length;

  const webN = all.filter(f=>f.web_online).length;

  const offN = all.filter(f=>!f.online).length;

  if (LISTFILTER==='in')  list = list.filter(f=>f.online && !f.web_online);

  if (LISTFILTER==='web') list = list.filter(f=>f.web_online);

  if (LISTFILTER==='off') list = list.filter(f=>!f.online);

  document.getElementById('friendCount').textContent =

    `游戏内 ${inN} · <span style="color:#2563eb">网页 ${webN}</span>· 离线 ${offN}`;

  document.getElementById('friendSummary').innerHTML =

    summaryRow('in','游戏内', inN) + summaryRow('web','网页在线', webN) +

    summaryRow('off',' 离线', offN);

  document.getElementById('friends').innerHTML = list.map(f=>{

    const color = f.trust && f.trust.color ? f.trust.color : 'inherit';

    let where;

    if (f.online && !f.web_online){

      where = esc(f.world||'') + (f.instance_label?` <span class="chip">${esc(f.instance_label)}</span>`:'');

    } else if (f.web_online){

      where = '<span style="color:#2563eb">网页在线（未进世界）</span>';

    } else {

      where = f.last_seen ? `<span class="dim">上次在线 ${fmtTs(f.last_seen)}</span>` : '<span class="dim">离线</span>';

    }

    const st = f.online ? (`<span style="color:${statusDotC(f.status)}">${ST[f.status]||f.status||'在线'}</span>` + (f.desc? ' · '+esc(f.desc):'')) : '';

    return `<div class="frow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">`+

      `${f.thumb?`<img ${mediaAttrs(f.thumb,f._detailSource||f._src||GA)} style="width:26px;height:26px;border-radius:50%;object-fit:cover;flex-shrink:0">`:''}`+

      `<span class="dot" style="${f.online?'background:'+statusDotC(f.status):'opacity:.4'}"></span>`+

      `${f._src?ovSrcTag(f._src):''}`+

      `<span class="name" style="color:${color};min-width:120px">${esc(f.name)}${trustChip(f.trust)}</span>`+

      `<span class="fworld">${where}</span>`+

      `<span class="fmeta" style="max-width:170px">${st||' '}</span>`+

      `<span class="fmeta">${f.online?fmtDur((Date.now()/1000|0)-f.online_since):esc(PF[f.platform]||f.platform||'')}</span>`+

      `</div>`;

  }).join('') || '<div class="dim">没有符合条件的好友</div>';

}

/* ---------- 好友位置（VRCX Sidebar 风格：标签 + 卡片） ---------- */

let LOC_TAB = 'online';

function setLocTab(btn){

  LOC_TAB = btn.dataset.t;

  document.querySelectorAll('#locTabs .tabbtn').forEach(b=>b.classList.toggle('active', b===btn));

  renderLoc();

}

function locLine(f){

  if (f.online && f.web_online) return '<span style="color:#2563eb">网页在线（未进世界）</span>';

  if (!f.online) return (f.last_world ? '位于 ' + esc(f.last_world) + ' · ' : '') +

    (f.last_seen ? '上次在线 ' + fmtTs(f.last_seen) : '离线');

  if (!f.location || f.location==='offline') return '在大厅';

  if (f.location==='private' || !f.world) return '位于私人房间';

  return esc(f.world||'') + (f.instance_label?` · ${esc(f.instance_label)}`:'');

}

function locCard(f){

  return `<div class="loccard" onclick="openFriend('${esc(f.id)}','${f._src||''}')">`+

    `<div class="hd">${f.thumb?`<img ${mediaAttrs(f.thumb,f._detailSource||f._src||GA)}>`:'<img>'}`+

    `<div class="name" style="color:${f.trust.color||'inherit'};font-size:13.5px;overflow:hidden;text-overflow:ellipsis">${f._src?ovSrcTag(f._src):''}${esc(f.name)}${f._src?` <span class="chip">${f._src==='a'?'A 号':'B 号'}</span>`:''}</div>`+

    `<span class="dot" style="margin-left:auto;${f.online?'background:'+statusDotC(f.status):'opacity:.4'}"></span></div>`+

    (f.desc?`<div class="st">${esc(f.desc)}</div>`:'')+

    `<div class="loc">${locLine(f)}</div></div>`;

}

async function loadLocations(){

  const myE = GA_EPOCH;

  try{

    const fr = await gGet('/api/friends');

    if (myE !== GA_EPOCH) return;   // 旧视角响应丢弃

    window._LOCF = fr.friends || [];
    window._FRIENDS = fr.friends || [];

    renderLoc();

  }catch(e){ reportError(e); }

}

function renderLoc(){

  const query=(window._MOBILE_FRIEND_QUERY||'').toLowerCase().trim();
  const all=(window._LOCF||[]).filter(f=>!query||(f.name||'').toLowerCase().includes(query));

  const online = all.filter(f=>f.online && !f.web_online);

  const web = all.filter(f=>f.web_online);

  const offline = all.filter(f=>!f.online).sort((a,b)=>(b.last_seen||0)-(a.last_seen||0));

  const rooms = {};

  online.forEach(f=>{

    const inst = f.location||'';

    if (f.location && f.location.includes(':')) (rooms[inst]=rooms[inst]||[]).push(f);

  });

  const multi = Object.entries(rooms).filter(([,v])=>v.length>=2)

    .sort((a,b)=>b[1].length-a[1].length);

  document.getElementById('locCount').textContent =

    `游戏内 ${online.length} · 网页在线 ${web.length} / 共 ${all.length}`;

  let html = '';

  if (LOC_TAB==='online'){

     
    // 每个实例一个组头（按人数降序），私密/未知位置单独成组收尾
    const lrooms = {};

    const loose = [];

    online.forEach(f=>{

      const inst = f.location||'';

      if (f.location && f.location.includes(':')) (lrooms[inst]=lrooms[inst]||[]).push(f);

      else loose.push(f);

    });

    const lordered = Object.entries(lrooms).sort((a,b)=>b[1].length-a[1].length);

    html = lordered.map(([inst,fs])=>{

      const f0 = fs[0];

      return `<div class="room-group"><strong>${esc(f0.world||'世界信息未缓存')}</strong>`+

        (f0.world_id?` <span class="chip click" onclick="openWorld('${esc(f0.world_id)}','${f0._detailSource||f0._src||''}')">世界详情</span>`:'')+

        ` <span class="chip">${fs.length} 人</span></div><div class="locgrid">${fs.map(locCard).join('')}</div>`;

    }).join('') +

      (loose.length?`<div style="font-weight:600;margin:12px 0 6px">私密/未知位置 `+

        `<span class="chip">${loose.length} 人</span></div><div class="locgrid">${loose.map(locCard).join('')}</div>`:'')

      || '<div class="dim">没有好友在线</div>';

    if (!online.length) html = '<div class="dim">没有游戏内在线的好友</div>';

  } else if (LOC_TAB==='rooms'){

    html = multi.length ? multi.map(([inst,fs])=>{

      const f0 = fs[0];

      return `<div class="room-group"><strong>${esc(f0.world||'世界信息未缓存')}</strong>`+

        (f0.world_id?` <span class="chip click" onclick="openWorld('${esc(f0.world_id)}','${f0._detailSource||f0._src||''}')">世界详情</span>`:'')+

        ` <span class="chip">${fs.length} 人</span></div><div class="locgrid">${fs.map(locCard).join('')}</div>`;

    }).join('') : '<div class="dim">没有多人同处一个房间</div>';

  } else if (LOC_TAB==='web'){

    html = web.length ? `<div class="locgrid">${web.map(locCard).join('')}</div>`

      : '<div class="dim">没有活跃中（网页端）的好友</div>';

  } else {

    html = offline.length ? `<div class="locgrid">${offline.map(locCard).join('')}</div>`

      : '<div class="dim">没有离线好友</div>';

  }

  document.getElementById('locations').innerHTML = html;

}

/* ---------- 右侧常驻好友面板 ---------- */

let RP_TAB = 'friends';

function setRPTab(t){

  RP_TAB = t;

  document.getElementById('rtab-friends').classList.toggle('active', t==='friends');

  document.getElementById('rtab-rooms').classList.toggle('active', t==='rooms');

  renderRPanel();

}

function toggleRPanel(){

  document.getElementById('rpanel').classList.toggle('hidden-p');

}

async function refreshPanel(btn){
  const task=APP.tasks.begin('panel-refresh');
  if(btn){btn.disabled=true;btn.textContent='⏳';}
  try{
    const r=await gPost('/api/refresh',{});
    if(!r.ok) throw new Error(r.error||'刷新失败');
    await new Promise(resolve=>setTimeout(resolve,1800));
    if(!task.current()) return;
    await Promise.all([refreshChrome(),APP.pages.refresh(true)]);
  }catch(e){if(task.current()) reportError(e);}
  finally{if(btn){btn.disabled=false;btn.textContent='↻';}}
}

async function loadRPanel(){

  if (document.getElementById('rpanel').classList.contains('hidden-p')) return;

  try{

    const myE = GA_EPOCH;

    const [fr, data] = await Promise.all([gGet('/api/friends'), gGet('/api/self')]);
    const s = GA==='m' ? data._accounts?.a : data;
    const sPraw = GA==='m' ? data._accounts?.b : null;

    if (myE !== GA_EPOCH) return;   // 旧视角响应丢弃

    const sP = sPraw && sPraw.peer ? sPraw.peer : sPraw;  // 解外层信封（peer_configured/peer）

    const all = fr.friends || [];

    window._FRIENDS = all;  // 详情弹窗秒开用：先画壳（VRCX 本地缓存同款语义）

    const online = all.filter(f=>f.online && !f.web_online);

    const web = all.filter(f=>f.web_online);

    const offline = all.filter(f=>!f.online).sort((a,b)=>(b.last_seen||0)-(a.last_seen||0));

    const rooms = {};

    online.forEach(f=>{

      const inst = f.location||'';

      if (f.location && f.location.includes(':')) (rooms[inst]=rooms[inst]||[]).push(f);

    });

    const multi = Object.entries(rooms).filter(([,v])=>v.length>=2)

      .sort((a,b)=>b[1].length-a[1].length);

    document.getElementById('rpCount').textContent = `(${online.length+web.length}/${all.length})`;

    document.getElementById('rpRooms').textContent = `(${multi.length})`;

    const av = f =>f.thumb?`<img ${mediaAttrs(f.thumb,f._detailSource||f._src||GA)}>`:'<img>';
    const row = f =>`<div class="rrow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">${av(f)}`+

      `<div><div class="rn" style="color:${f.trust.color||'inherit'}">${f._src?ovSrcTag(f._src):''}${esc(f.name)}</div>`+

      `<div class="rl">${esc(f.world||'—')}${f.instance_label?' · '+esc(f.instance_label):''}</div></div>`+

      `<span class="dot" style="margin-left:auto;background:${statusDotC(f.status)}"></span></div>`;

    let html = '';

    if (RP_TAB==='friends'){

      const ownRow=(source,d)=>{
        if(!d || d.error || d.logged_in===false || !d.name){
          const message=`${GA_NAMES[source]} ${VRCXRuntime.LOGIN_ERROR}`;
          return `<div class="rrow">${ovSrcTag(source)}<span class="dim">${message}</span></div>`;
        }
        return `<div class="rrow"${GA==='m'?'':` onclick="switchPage('dash')"`}>${ovSrcTag(source)}${d.thumb?`<img ${mediaAttrs(d.thumb,source)}>`:'<img>'}`+
          `<div><div class="rn">${esc(d.name)}</div><div class="rl">${d.state==='online'?esc(d.world||'在线'):d.state==='active'?'活跃中（网页端）':'离线'}</div></div>`+
          `<span class="dot ${d.state==='online'?'on':d.state==='active'?'act':''}" style="margin-left:auto"></span></div>`;
      };
      html+=`<div class="rgroup">我${GA==='m'?'（双号）':''}</div>`+
        (GA==='m'?ownRow('a',s)+ownRow('b',sP):ownRow(GA,s));

      const rooms = {};
      online.forEach(f=>{
        const inst = f.location||'';
        if (f.location && f.location.includes(':')) (rooms[inst]=rooms[inst]||[]).push(f);
      });
      const ordered = Object.entries(rooms).sort((a,b)=>b[1].length-a[1].length);
      const grouped = new Set(ordered.flatMap(([,v])=>v.map(f=>f.id)));
      const loose = online.filter(f=>!grouped.has(f.id));
      html += `<div class="rgroup">在线 — ${online.length}</div>`+
        ordered.map(([inst,fs])=>{
          const f0 = fs[0];
          return `<div class="rgroup">${esc(f0.world||'')} <span class="chip">${fs.length} 人</span></div>`+
            fs.map(row).join('');
        }).join('') +
        (loose.length?`<div class="rgroup">私密/未知位置 <span class="chip">${loose.length} 人</span></div>`+
          loose.map(row).join(''):'') ||
        '<div class="dim" style="font-size:12px">无</div>';

      html += `<div class="rgroup"><span style="color:#2563eb">活跃中（仅登录网页端）</span>— ${web.length}</div>`+

        (web.map(f=>`<div class="rrow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">${av(f)}`+

          `<div><div class="rn" style="color:${f.trust.color||'inherit'}">${f._src?ovSrcTag(f._src):''}${esc(f.name)}</div>`+

          `<div class="rl">${esc(f.desc||'网页在线')}</div></div>`+

          `<span class="dot" style="margin-left:auto;background:${statusDotC(f.status)}"></span></div>`).join('')

          || '<div class="dim" style="font-size:12px">无</div>');

      html += `<div class="rgroup">离线 — ${offline.length}</div>`+

        (offline.map(f=>`<div class="rrow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">${av(f)}`+

          `<div><div class="rn" style="color:${f.trust.color||'inherit'}">${f._src?ovSrcTag(f._src):''}${esc(f.name)}</div>`+

          `<div class="rl">${f.last_world?'位于 '+esc(f.last_world)+' · ':''}${f.last_seen?'上次在线 '+fmtTs(f.last_seen):'离线'}</div></div></div>`).join('')

          || '<div class="dim" style="font-size:12px">无</div>');

    } else {

      html = multi.length ? multi.map(([inst,fs])=>{

        const f0 = fs[0];

        return `<div class="rgroup">${esc(f0.world||'')} <span class="chip">${fs.length} 人</span></div>`+

          fs.map(row).join('');

      }).join('') : '<div class="dim" style="font-size:12px">没有多人同处一个房间</div>';

    }

    document.getElementById('rpBody').innerHTML = html;
    showPartial(fr);

  }catch(e){ reportError(e); }

}
