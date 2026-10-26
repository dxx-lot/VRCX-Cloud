/* ---------- 登录 / 推送 ---------- */

async function doLogin(){

  const btn = document.getElementById('loginBtn'), msg = document.getElementById('loginMsg');

  btn.disabled = true;

  try{

    const r = await post('/api/login', {username: v('username'), password: document.getElementById('password').value,

      code: v('code'), store: false});

    if (r.ok){

      msg.textContent = ' ' + r.message;

      document.getElementById('code').classList.add('hidden');
      document.getElementById('password').value='';document.getElementById('code').value='';

      APP.client.invalidate('a'); refreshChrome(); loadAccount();

    } else if (r.need_2fa){

      const codeEl = document.getElementById('code');

      codeEl.classList.remove('hidden');

      if (r.hint) codeEl.placeholder = r.hint;

      codeEl.focus();

      msg.textContent = (r.hint || '需要两步验证') + (r.error ? `（上次错误：${r.error}）` : '');

    } else {

      msg.textContent = '登录异常，请检查账号、密码及验证码后重试。';

    }

  }catch(e){ console.error(e);msg.textContent = '登录异常，请稍后重试。'; }

  finally{ btn.disabled = false; }

}

function showLogin(){
  switchPage('login');
  switchAcct(GA==='m'?'ov':GA==='b'?'peer':'self');
}

async function testPush(){

  const r = await gPost('/api/push-test', {});

  alert(r.ok ? ' 测试推送已发出，看看手机/手表' : ' 推送未成功：检查 config.json 里的 Bark key');

}

/* ---------- 启动 ---------- */

function fmtBytes(b){
  if (b==null || isNaN(b)) return '—';
  const u=['B','KB','MB','GB','TB']; let i=0;
  while (b>=1024 && i<u.length-1){ b/=1024; i++; }
  return (i? b.toFixed(b>=100?0:1) : Math.round(b)) + u[i];
}

async function loadNetStats(){
  try{
    const r = await gGet('/api/net-stats');
    const tiles = [['实时速率', fmtBytes(r.rate)+'/s'], ['今天', fmtBytes(r.today)],
      ['最近 1 小时', fmtBytes(r.hour1)], ['最近 24 小时', fmtBytes(r.hour24)], ['总计', fmtBytes(r.total)]];
    document.querySelectorAll('.piStatsLine').forEach(el=>{
      el.innerHTML =
        ` 内存 ${r.mem_pct!=null?r.mem_pct+'%':'—'}${r.mem_used_mb!=null?' ('+r.mem_used_mb+'MB)':''} ·  CPU ${r.cpu_pct!=null?r.cpu_pct+'%':'—'}<br>`+
        `↓ ${fmtBytes(r.down_bps)+'/s'} · ↑ ${fmtBytes(r.up_bps)+'/s'} · 轮询 ${r.poll||'—'}s`;
    });
    const g = document.getElementById('netgrid');
    if (!g) return;
    g.innerHTML = tiles.map(([k,v])=>
      `<div style="border:1px solid var(--line);border-radius:10px;padding:14px 10px;text-align:center">`+
      `<div class="dim" style="font-size:12px">${k}</div>`+
      `<div style="font-size:20px;font-weight:700;margin-top:6px">${v}</div></div>`).join('');
  }catch(e){reportError(e);}
}

function acctRow(k, v){
  return `<div style="border:1px solid var(--line);border-radius:8px;padding:8px 10px">`+
    `<div class="dim" style="font-size:11px">${k}</div>`+
    `<div style="font-weight:600;margin-top:2px">${v}</div></div>`;
}

function renderAcct(el, s, isLocal){
  if (VRCXRuntime.loginLabel(s) !== '已登录'){
    el.innerHTML = `<span class="badge bad">${VRCXRuntime.LOGIN_ERROR}</span> <span class="dim">请登录账号，或重新检查现有会话。</span>`+
      `<button class="ghost mini" onclick="${isLocal?'loadAccount':'loadPeerAccount'}({force:true})">重新检查</button>`;
    return;
  }
  const right = isLocal
    ? `<button class="ghost" style="margin-left:auto;align-self:flex-start" onclick="doLogout()">登出</button>`
    : `<button class="ghost" style="margin-left:auto;align-self:flex-start" onclick="doPeerLogout()">登出</button>`;
  el.innerHTML =
    `<div style="display:flex;gap:14px;align-items:center">`+
    `${s.thumb?`<img ${mediaAttrs(s.thumb,isLocal?'a':'b')} referrerpolicy="no-referrer" style="width:72px;height:72px;border-radius:12px;object-fit:cover">`:'<div style="width:72px;height:72px;border-radius:12px;background:var(--hov)"></div>'}`+
    `<div style="min-width:0">`+
    `<div style="font-size:17px;font-weight:700;color:${s.trust&&s.trust.color?s.trust.color:'inherit'}">${esc(s.name||'')}</div>`+
    `<div class="dim" style="font-size:12px">${s.username?('@'+esc(s.username)+' · '):''}${esc(s.id||'')}</div>`+
    `<div style="margin-top:4px">`+
    `<span class="badge ${s.state==='online'?'badge-online':s.state==='active'?'badge-active':'badge-offline'}">${s.state==='online'?'游戏内':s.state==='active'?'网页在线（仅登录）':'离线'}</span>`+
    (s.status?`<span style="color:${statusDotC(s.status)};font-weight:600">${esc(STATUS_LABEL[s.status]||s.status)}</span>`:'')+
    (s.desc?`<span class="dim">${esc(s.desc)}</span>`:'')+
    `</div></div>${right}</div>`+
    `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-top:12px">`+
    acctRow('所在世界', s.world? esc(s.world)+(s.instance_label?' · '+esc(s.instance_label):'') : (s.state==='offline'?'离线':'—'))+
    acctRow('好友数', s.friends_count!=null? s.friends_count : '—')+
    acctRow('注册时间', s.date_joined? esc(String(s.date_joined).slice(0,10)) : '—')+
    acctRow('上次登录', s.last_login? esc(String(s.last_login).slice(0,16).replace('T',' ')) : '—')+
    acctRow('两步验证', s.twoFA===true?'已开启':s.twoFA===false?'未开启':'—')+
    `</div>`;
}

let ACCT_VIEW = 'self';

function switchAcct(v){
  ACCT_VIEW = v;
  document.getElementById('acctOv').classList.toggle('hidden', v!=='ov');
  document.getElementById('acctSelf').classList.toggle('hidden', v!=='self');
  document.getElementById('acctPeer').classList.toggle('hidden', v!=='peer');
  document.getElementById('acctSelfForm').classList.toggle('hidden', v!=='self');
  document.getElementById('acctPeerForm').classList.toggle('hidden', v!=='peer');
  // 滑动胶囊：滑块宽度=段数均分，translateX 按段滑（未来加号=加按钮即成左中右多段）
  const btns = [...document.querySelectorAll('#acctSwitch button')];
  const idx = Math.max(0, btns.findIndex(b=>b.dataset.v===v));
  const slide = document.getElementById('acctSlide');
  if (slide && btns.length){
    slide.style.width = `calc((100% - 6px)/${btns.length})`;
    slide.style.transform = `translateX(${idx*100}%)`;
  }
  btns.forEach(b=>{
    const on = b.dataset.v===v;
    b.style.color = on? '#fff' : 'var(--dim)';
  });
  if (v==='ov') loadOverview();
  if (v==='peer') loadPeerAccount();
}

const OV_EV = {online:' 上线', offline:' 下线', location:' 前往',
               active:' 网页在线', status:' 状态', desc:' 简介', avatar:' 模型'};
let OV = {feedA: [], feedB: [], frA: [], frB: [], peerOk: true, peerState:null};
let OV_FEED_MODE = 'merge', OV_LIST_MODE = 'merge';

function setOvFeedMode(btn){ OV_FEED_MODE = btn.dataset.m;
  document.querySelectorAll('#ovFeedTabs .tabbtn').forEach(b=>b.classList.toggle('active', b===btn));
  renderOvFeed(); }

function setOvListMode(btn){ OV_LIST_MODE = btn.dataset.m;
  document.querySelectorAll('#ovListTabs .tabbtn').forEach(b=>b.classList.toggle('active', b===btn));
  renderOvFriends(); }

async function loadOverview(){
  const task=APP.tasks.begin('overview');
  try{
    const [fa, fb, frA, frB] = await Promise.allSettled([
      gGet('/api/feed',{account:'a'}), gGet('/api/feed',{account:'b'}),
      gGet('/api/friends',{account:'a'}), gGet('/api/friends',{account:'b'})]);
    if (!task.current()) return;
    OV.feedA=fa.status==='fulfilled'?fa.value.events:[];
    OV.feedB=fb.status==='fulfilled'?fb.value.events:[];
    OV.frA=frA.status==='fulfilled'?frA.value.friends:[];
    OV.frB=frB.status==='fulfilled'?frB.value.friends:[];
    OV.peerOk=fb.status==='fulfilled';
    OV.peerState=APP.client.accountState('b');
  }catch(e){reportError(e);}
  renderOvFeed(); renderOvFriends();
}

function ovTag(which){
  return `<span class="ovtag ${which}" title="${which==='a'?'账号A':'账号B'}">${which==='a'?'A':'B'}</span>`;
}

function ovFeedRow(e, which){
  const what = WEB_OFFLINE_LABEL(e);
  const detail = e.event==='offline' ? `在线 ${Math.round((e.duration||0)/60)} 分钟`
    : (e.world_name || (e.location==='private' ? '私人房间' : e.status_description || e.location || ''));
  return `<div class="rrow" style="padding:4px 8px">${ovTag(which)}`+
    `<div style="min-width:0"><div class="rn">${esc(e.display_name||'?')} <span class="dim" style="font-weight:400">${what}</span></div>`+
    `<div class="rl">${esc(detail||'—')}</div></div>`+
    `<span class="dim" style="margin-left:auto;font-size:11px">${fmtTs(e.ts)}</span></div>`;
}

function renderOvFeed(){
  const el = document.getElementById('ovFeed');
  if (!el) return;
  const unavailable=`${GA_NAMES.b}登录异常`;
  const notice=!OV.peerOk?`<div class="dim" style="padding:8px">${unavailable}，仅显示账号A动态</div>`:'';
  if (!OV.peerOk && OV_FEED_MODE==='b') { el.innerHTML=notice; return; }
  let rows;
  if (OV_FEED_MODE==='a') rows = OV.feedA.map(e=>ovFeedRow(e,'a'));
  else if (OV_FEED_MODE==='b') rows = OV.feedB.length ? OV.feedB.map(e=>ovFeedRow(e,'b'))
      : [`<div class="dim" style="padding:8px">账号B暂无动态（B 号登录并同步后这里会出现）</div>`];
  else {
    rows = [...OV.feedA.map(e=>({...e, _w:'a'})), ...OV.feedB.map(e=>({...e, _w:'b'}))]
      .sort((x,y)=>(y.ts||0)-(x.ts||0)).slice(0,100).map(e=>ovFeedRow(e, e._w));
  }
  if (!rows.length) rows = [`<div class="dim" style="padding:8px">暂无动态</div>`];
  el.innerHTML = (OV_FEED_MODE==='merge' ? notice : '') + rows.join('');
}

function renderOvFriends(){
  const el = document.getElementById('ovFriends');
  if (!el) return;
  if(!OV.peerOk&&OV_LIST_MODE==='b'){
    el.innerHTML=`<div class="dim" style="padding:8px">${`${GA_NAMES.b}登录异常`}，暂不读取账号B好友</div>`;
    return;
  }
  let rows;
  const frow = (f, which)=>{
    const on = f.state==='online';
    return `<div class="rrow" style="padding:4px 8px">${ovTag(which)}`+
      `${f.thumb?`<img ${mediaAttrs(f.thumb,which)} referrerpolicy="no-referrer">`:'<img>'}`+
      `<div style="min-width:0"><div class="rn" style="color:${f.trust&&f.trust.color?f.trust.color:'inherit'}">${esc(f.name||'')}</div>`+
      `<div class="rl">${esc(f.world||'—')}${f.instance_label?' · '+esc(f.instance_label):''}</div></div>`+
      `<span class="dot" style="margin-left:auto;background:${f.online?'#2ed319':f.web_online?'#00b8ff':'#737f8d'}"></span></div>`;
  };
  if (OV_LIST_MODE==='a') rows = OV.frA.map(f=>frow(f,'a'));
  else if (OV_LIST_MODE==='b') rows = OV.frB.length ? OV.frB.map(f=>frow(f,'b'))
      : [`<div class="dim" style="padding:8px">账号B暂无好友数据（B 号登录并同步后出现）</div>`];
  else {
    rows = [...OV.frA.map(f=>({...f, _w:'a'})), ...OV.frB.map(f=>({...f, _w:'b'}))]
      .sort((x,y)=>(x.name||'').localeCompare(y.name||'')).map(f=>frow(f, f._w));
  }
  if (!rows.length) rows = [`<div class="dim" style="padding:8px">暂无好友数据</div>`];
  el.innerHTML = rows.join('');
}

async function loadAccount(options={}){
  try{
    const account = await gGet('/api/self', {account:'a', fenced:false, force:options.force===true});
    syncAccountIdentity('a', account);
    const el = document.getElementById('acctSelf');
    if(el) renderAcct(el, account, true);
  }catch(error){
    if(VRCXRuntime.ignored(error)) return;
    console.error(error); syncAccountIdentity('a', null);
    const el = document.getElementById('acctSelf');
    if(el) renderAcct(el, {logged_in:false}, true);
  }
}

async function loadPeerAccount(options={}){
  const force=options.force===true;
  if(!force && GA==='a' && !(CURPAGE==='login' && ACCT_VIEW==='peer')) return;
  try{
    const status = await gGet('/api/status', {account:'b', fenced:false, force});
    const account = status.logged_in===true
      ? await gGet('/api/self', {account:'b', fenced:false, force}) : {logged_in:false};
    syncAccountIdentity('b', account);
    const el = document.getElementById('acctPeer');
    if(el) renderAcct(el, account, false);
  }catch(error){
    if(VRCXRuntime.ignored(error)) return;
    console.error(error); syncAccountIdentity('b', null);
    const el = document.getElementById('acctPeer');
    if(el) renderAcct(el, {logged_in:false}, false);
  }
}

function mbFill(){
  const g = document.getElementById('moreGrid');
  if (!g || g.dataset.filled) return;
  // 管理/流量 已从 PAGES 移除（入口在设置页）——手机端补回更多面板，否则无入口
  const extra = [['extensions','','管理'],['netstats','','流量']];
  g.innerHTML = PAGES.filter(([id])=>pageAllowed(id)&&!['feed','locations','push','login'].includes(id))
    .concat(extra.filter(([id])=>pageAllowed(id)))
    .map(([id,ic,label])=>`<button onclick="mbGo('${id}')"><span class="ic">${ic}</span>${label}</button>`).join('');
  g.dataset.filled = '1';
}

/* ---------- 顶部全局账号视角（GA）：整站数据源跟随切换 ----------
   （GA/GA_LABEL 声明在脚本最前——buildNav 立即执行就要读 GA，放后面会 TDZ 崩掉整站） */
function ovSrcTag(w){
  return (w||'').split('').filter(c=>c==='a'||c==='b')
    .map(c=>`<span class="ovtag ${c}">${c.toUpperCase()}</span>`).join('');
}
function srcChip(w){
  return w ? ` <span class="chip">${w==='ab'?'A+B 号':(w==='a'?'A 号':'B 号')}</span>` : '';
}

function switchGA(v){
  if (!APP.context.select(v)) return;
  GA = APP.context.view; GA_EPOCH = APP.context.epoch;
  localStorage.setItem('ga', GA);
  closeModal(); closeQS(); clearAccountUI();
  alignGSlide(); buildNav();
  const view = document.getElementById('gaView');
  if (view) view.textContent = GA==='m' ? '视角：双号合并' : '视角：'+GA_NAMES[GA];
  const fsel = document.getElementById('feedFriendSel');
  if (fsel) { fsel.style.display = GA==='m' ? 'none' : ''; fsel.dataset.ga = ''; fsel.innerHTML='<option value="">全部好友</option>'; }
  FEED_FRIEND=''; FEED_PAGE=0;
  switchAcct(GA==='m' ? 'ov' : GA==='b' ? 'peer' : 'self');
  switchPage(CURPAGE);
  refreshChrome(); realtimeLabel();
}

// 滑块对齐到激活按钮的实际几何位置（按钮文字不等长，均分必穿模）
function alignGSlide(){
  const btns = [...document.querySelectorAll('#gswitch button')];
  const cur = btns.find(b=>b.dataset.g===GA);
  const slide = document.getElementById('gslide');
  if (!slide || !cur) return;
  slide.style.left = cur.offsetLeft + 'px';
  slide.style.width = cur.offsetWidth + 'px';
  btns.forEach(b=>b.classList.toggle('on', b===cur));
}
window.addEventListener('resize', alignGSlide);
window.addEventListener('load', ()=>setTimeout(alignGSlide, 60));

function goOverview(){
  switchPage('login');
  switchAcct('ov');
  window.scrollTo({top:0, behavior:'smooth'});
}

function mbSheetsClose(){
  const s = document.getElementById('moreSheet');
  if (s) s.classList.add('hidden');
  document.body?.classList.remove('sheet-open');
  mbCloseDrawer();
}

function toggleMore(){
  if(window.MobileUI?.isMobile()){ mobileMenu(); return; }
  const s = document.getElementById('moreSheet');
  s.classList.toggle('hidden');
  if (!s.classList.contains('hidden')){ mbFill(); mbCloseDrawer(); }
}function mbGo(p, btn){
  const sheetWasOpen = !document.getElementById('moreSheet').classList.contains('hidden');
  switchPage(p);
  // switchPage 只管高亮；面板显隐在这里一次性收对（避免双重翻转）
  document.getElementById('moreSheet').classList.add('hidden');
  mbCloseDrawer();
  document.querySelectorAll('#mobileNav button').forEach(b=>{
    b.classList.remove('active');
    if (b.dataset.mb===p) b.classList.add('active');
  });
}

function mbDrawer(){
  document.getElementById('rpanel').classList.add('mb-open');
  const s = document.getElementById('moreSheet');
  if (s) s.classList.add('hidden');
}

function mbCloseDrawer(){ document.getElementById('rpanel').classList.remove('mb-open'); }

async function doLogout(){
  if (!confirm(`确定登出 ${GA_NAMES.a}？该账号的会话将被清除，推送停止，直到重新登录。`)) return;
  try{
    const r=await gPost('/api/logout', {}, {account:'a'});
    if (!r.ok) throw new Error(r.error||'登出失败');
    APP.client.invalidate('a');
    if(GA!=='b') clearAccountUI();
    updateAccountName('a','账号A'); await Promise.all([loadAccount(),refreshChrome()]);
  }catch(e){reportError(e);}
}

async function doPeerLogin(){
  const btn = document.getElementById('p_loginBtn'), msg = document.getElementById('p_loginMsg');
  btn.disabled = true;
  try{
    const r = await post('/api/peer-login', {username: v('p_username'), password: document.getElementById('p_password').value,
      code: v('p_code'), store: false});
    if (r.ok){
      msg.textContent = ' ' + (r.message || '账号B登录成功');
      document.getElementById('p_code').classList.add('hidden');
      document.getElementById('p_password').value='';document.getElementById('p_code').value='';
      APP.client.invalidate('b'); loadPeerAccount({force:true}); refreshChrome();
    } else if (r.need_2fa){
      const codeEl = document.getElementById('p_code');
      codeEl.classList.remove('hidden');
      if (r.hint) codeEl.placeholder = r.hint;
      codeEl.focus();
      msg.textContent = (r.hint || '需要两步验证') + (r.error ? `（上次错误：${r.error}）` : '');
    } else {
      msg.textContent = '登录异常，请检查账号、密码及验证码后重试。';
    }
  }catch(e){ console.error(e);msg.textContent = '登录异常，请稍后重试。'; }
  finally{ btn.disabled = false; }
}

async function doPeerLogout(){
  if (!confirm(`确定登出 ${GA_NAMES.b}？该账号的会话将被清除，推送停止，直到重新登录。`)) return;
  try{
    const r=await post('/api/peer-logout', {});
    if (!r.ok) throw new Error(r.error||'账号B登出失败');
    APP.client.invalidate('b');
    if(GA!=='a') clearAccountUI();
    updateAccountName('b','账号B'); await Promise.all([loadPeerAccount(),refreshChrome()]);
  }catch(e){reportError(e);}
}

let PUSH_FRIENDS = [], PUSH_MODE = 'favorites', PUSH_SELECTED = [], _PUSH_READY=null;
function pushReady(){return _PUSH_READY===GA+'|'+GA_EPOCH;}

async function loadPushCfg(force=false){
  _PUSH_READY=null;
  const task=APP.tasks.begin('push-scope');
  const status=document.getElementById('pushScopeStatus'),retry=document.getElementById('pushScopeRetry');
  if(status)status.textContent='正在加载提醒范围…';retry?.classList.add('hidden');
  try{
    const r = await gGet('/api/push-config',{force});
    if (!task.current()) return;
    PUSH_FRIENDS = r.friends || [];
    PUSH_MODE = r.mode || 'favorites';
    PUSH_SELECTED = (r.watch||[]).map(x=>x.id);
    _PUSH_READY=GA+'|'+GA_EPOCH;
    pushModeUI();
    const cm = document.getElementById('pushCustom');
    if (cm) cm.classList.toggle('hidden', PUSH_MODE!=='custom');
    if(status)status.textContent='提醒范围已加载。';
  }catch(e){
    if(!task.current())return;
    if(status)status.textContent='提醒范围加载失败：'+(e.message||'无法连接服务器');
    retry?.classList.remove('hidden');
  }
}

function pushModeUI(){
  document.querySelectorAll('#pushModeRow button').forEach(b=>{
    const on = b.dataset.m===PUSH_MODE;
    b.style.borderColor = on? 'var(--accent)' : '';
    b.style.color = on? 'var(--accent)' : '';
  });
  document.getElementById('pushCustom').classList.toggle('hidden', PUSH_MODE!=='custom');
  renderPushChips(); renderPushPick();
}

function pickPushMode(btn, m){ if(!pushReady()) return; PUSH_MODE = m; pushModeUI(); }

function pushIsSel(id){ return PUSH_SELECTED.includes(id); }

function pushDel(id){ if(!pushReady()) return; PUSH_SELECTED = PUSH_SELECTED.filter(x=>x!==id); renderPushChips(); renderPushPick(); }

function pushAdd(id){ if(!pushReady()) return; if (!pushIsSel(id)) PUSH_SELECTED.push(id); renderPushChips(); renderPushPick(); }

function renderPushChips(){
  const el = document.getElementById('pushChips');
  if (!el) return;
  el.innerHTML = PUSH_SELECTED.map(id=>{
    const f = PUSH_FRIENDS.find(x=>x.id===id) || {name:id, thumb:''};
    return `<span class="chip" style="margin:2px;padding:3px 8px">`+
      `${f.thumb?`<img ${mediaAttrs(f.thumb)} referrerpolicy="no-referrer" style="width:18px;height:18px;border-radius:50%;vertical-align:-5px;margin-left:0">`:''} `+
      `${esc(f.name)} <b style="cursor:pointer" onclick="pushDel('${esc(id)}')"></b></span>`;
  }).join('') || '<span class="dim">还没有选好友</span>';
}

function renderPushPick(){
  const inp = document.getElementById('pushSearch');
  const el = document.getElementById('pushPick');
  if (!el) return;
  const q = ((inp&&inp.value)||'').toLowerCase();
  const rows = PUSH_FRIENDS.filter(f=>!q || f.name.toLowerCase().includes(q));
  el.innerHTML = rows.map(f=>{
    const on = pushIsSel(f.id);
    return `<div class="rrow" style="padding:4px 8px;cursor:pointer" onclick="${on?`pushDel('${f.id}')`:`pushAdd('${f.id}')`}">`+
      `${f.thumb?`<img ${mediaAttrs(f.thumb)} referrerpolicy="no-referrer">`:'<img>'}`+
      `<div><div class="rn">${esc(f.name)}</div></div>`+
      `<span class="chip ${on?'click':''}" style="margin-left:auto">${on?' 已选':'+ 添加'}</span></div>`;
  }).join('') || '<div class="dim" style="padding:8px">没有匹配的好友</div>';
}

async function savePushCfg(){
  if(!pushReady()){document.getElementById('pushSaveMsg').textContent='账号配置尚未加载';return;}
  const r = await gPost('/api/push-config-set', {mode: PUSH_MODE, watch_list: PUSH_SELECTED});
  const el = document.getElementById('pushSaveMsg');
  el.textContent = r.ok? ' 已保存，下一轮轮询生效' : ' '+(r.error||'失败');
  setTimeout(()=>{ el.textContent=''; }, 4000);
}
