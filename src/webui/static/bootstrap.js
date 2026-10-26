/* Add a feature by registering its page and resource; this is the sole startup. */
APP.accessManaged=!!document.querySelector('meta[name="app-access-managed"]');
if(APP.accessManaged){
  TOKEN='';localStorage.removeItem('vrcwebtoken');
  document.getElementById('engineAccessSettings')?.classList.add('hidden');
  document.getElementById('appAccessSettings')?.classList.remove('hidden');
}

function clearAccountUI(){
  FEEDDATA=[]; FEED_FRIEND=''; FEED_PAGE=0; NT_DATA=[]; NT_PAGE=0; FAVD=null; FAVGROUP=null;
  CFG=null; settingsBusy(true); _PUSH_READY=null; UD=null; window._FRIENDS=[]; window._LOCF=[]; window._AVD=null;
  window._FLT=[]; window._FLT_DATA=[]; window._WATCH_IDS=undefined; PUSH_FRIENDS=[]; PUSH_SELECTED=[];
  if (SAVE_T) { clearTimeout(SAVE_T); SAVE_T=null; }
  const loading='<div class="dim">加载中…</div>';
  const bodies=['rpBody','friends','locations','favGroups','favItems','avatarsOwn','avatarsFav',
    'curAvatar','history','friendlog','moderations','searchUsers','searchWorlds','statFriends',
    'statWorlds','statDaily','statHeat','ovFeed','ovFriends','mobileFeed','mobileProfile','mobileNotifs'];
  for (const id of bodies) { const el=document.getElementById(id); if (el) el.innerHTML=loading; }
  for (const id of ['feedTable','ntBody','fltBody']) {
    const el=document.getElementById(id); if(el) el.innerHTML='<tr><td colspan="13" class="dim">加载中…</td></tr>';
  }
  for (const id of ['set-oldpw','set-newpw','set-tgtoken','myDesc']) { const el=document.getElementById(id);if(el) el.value=''; }
  const backup=document.getElementById('bkList');if(backup) backup.innerHTML='<option value="">加载中…</option>';
  for (const id of ['feedPager','ntPager','pushChips','pushPick']) { const el=document.getElementById(id); if(el) el.innerHTML=''; }
  document.getElementById('selfName').textContent='';
  IMAGES.clear(document.getElementById('selfThumb'));
  document.getElementById('selfLoc').textContent='';
  document.getElementById('scMerge').innerHTML='';
  document.getElementById('selfPanel').style.display='none';
  document.getElementById('appError').classList.add('hidden');
}

function showPartial(payload){
  const unavailable=Object.entries(payload?._errors||{}).filter(([,error])=>error);
  const el=document.getElementById('appPartial');
  if (!el) return;
  el.textContent=unavailable.map(([account])=>`${GA_NAMES[account]} ${VRCXRuntime.LOGIN_ERROR}`).join(' · ');
  el.classList.toggle('hidden',unavailable.length===0);
}

function refreshChrome(){
  return Promise.allSettled([loadSelf(),loadStatus(),loadRPanel()]);
}

APP.pages.register('home',{merged:true,load:loadMobileHome});
APP.pages.register('feed',{merged:true,interval:5000,load:()=>loadFeed()});
APP.pages.register('locations',{merged:true,interval:5000,load:loadLocations});
APP.pages.register('friends',{interval:5000,load:loadFriends});
APP.pages.register('favorites',{load:loadFavorites});
APP.pages.register('stats',{load:loadStats});
APP.pages.register('activity',{available:false,refresh:false});
APP.pages.register('hotworlds',{available:false,refresh:false});
APP.pages.register('mutual',{refresh:false});
APP.pages.register('history',{load:loadHistory});
APP.pages.register('notifs',{load:loadNotifs});
APP.pages.register('avatars',{load:loadAvatars});
APP.pages.register('moderation',{load:()=>{
  const want=_SOC_TARGET.t||document.querySelector('#socTabs .tabbtn.active')?.dataset.t||'log';
  const btn=[...document.querySelectorAll('#socTabs .tabbtn')].find(b=>b.dataset.t===want);
  _SOC_TARGET.t=null; return setSocTab(btn||document.querySelector('#socTabs .tabbtn'));
}});
APP.pages.register('settings',{refresh:false,load:loadSettings});
APP.pages.register('push',{refresh:false,load:()=>Promise.all([loadSettings(),loadPushCfg()])});
APP.pages.register('login',{merged:true,load:()=>Promise.all([loadAccount(),loadPeerAccount(),ACCT_VIEW==='ov'?loadOverview():null])});
APP.pages.register('netstats',{merged:true,load:loadNetStats});
APP.pages.register('dash',{interval:5000,load:entering=>Promise.all([
  GA==='m'?null:loadPresets(),
  entering?renderDashWidgets():Promise.all(DASHS[DASH_IDX]?.widgets.map((type,i)=>renderWidget(type,`wd-${type}-${i}`))||[])
])});
for (const id of ['search','tools','direct','extensions']) APP.pages.register(id,{});
for (const id of ['gamelog','playerlist']) APP.pages.register(id,{available:false});

APP.scheduler.add('chrome',5000,refreshChrome);
APP.scheduler.add('page',5000,()=>APP.pages.refresh());
APP.scheduler.add('identity',15000,()=>Promise.allSettled([loadAccount(),loadPeerAccount()]));
APP.scheduler.add('host',10000,loadNetStats);
APP.scheduler.add('service',120000,loadVrcStatus);
const UI_VER=document.querySelector('meta[name="app-build"]')?.content;
APP.scheduler.add('version',60000,async()=>{
  const r=await gGet('/api/ui-version');
  if(r.v && UI_VER && r.v!==UI_VER) location.reload();
});

let ES_STATE='idle';
function realtimeLabel(){
  const el=document.getElementById('esState');
  if(!el) return;
  const state=VRCXRuntime.realtimeState(GA,!!TOKEN,ES_STATE);
  el.textContent=state.text;
  el.title=state.detail;
  el.style.color=state.connected?'var(--green)':'var(--dim)';
}
// SSE belongs to the local instance. It invalidates that source only; rendering
// always comes through the selected view's gateway, including merged snapshots.
let streamRefresh=null;
const realtimeChannel=new VRCXRuntime.RealtimeChannel({
  create:()=>new EventSource('/api/events/stream'),
  onState:state=>{ES_STATE=state;realtimeLabel();},
  onFeed:()=>{
    APP.client.invalidate('a',['/api/feed','/api/friends']);
    if(GA!=='a'||streamRefresh)return;
    streamRefresh=setTimeout(()=>{streamRefresh=null;if(GA==='a'){refreshChrome();APP.pages.refresh();}},250);
  }
});
function connectStream(){
  if(TOKEN||GA!=='a')realtimeChannel.stop();else realtimeChannel.start();
  realtimeLabel();
}
APP.syncRealtime=connectStream;
connectStream();
window.addEventListener('pagehide',()=>{realtimeChannel.stop();clearTimeout(streamRefresh);streamRefresh=null;});

window.addEventListener('unhandledrejection',e=>{
  e.preventDefault();reportError(e.reason);
});
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden){refreshChrome();APP.pages.refresh();}
});
window.addEventListener('pagehide',()=>APP.scheduler.stop());
window.addEventListener('pageshow',()=>{APP.scheduler.start();connectStream();});
MobileUI.init();
IMAGES.start(document);
buildNav();
switchAcct(GA==='m'?'ov':GA==='b'?'peer':'self');
switchPage('feed');alignGSlide();realtimeLabel();
const initialView=document.getElementById('gaView');
if(initialView) initialView.textContent='视角：'+GA_LABEL[GA];
APP.scheduler.start();APP.scheduler.tick();
