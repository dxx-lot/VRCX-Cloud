const ST = {active:'在线', joinme:'Join Me·欢迎加入', askme:'Ask Me·先询问', busy:'勿扰'};

const PF = {standalonewindows:'PCVR', android:'Quest', ios:'iOS', web:'网页'};

const WD = ['日','一','二','三','四','五','六'];

 









const PAGES = [['feed','','好友动态'],['locations','','好友位置'],

  ['gamelog','','游戏日志'],['playerlist','','房内玩家'],

  ['search','','搜索'],['favorites','','收藏&分组'],

  ['notifs','','通知'],['push','','推送'],['avatars','','我的模型'],

  ['social','','社交'],['charts','','图表'],['tools','','工具'],

  ['direct','','直达'],['dash','','仪表板'],

  ];  // 账号/管理/流量 从导航移除（入口在设置页）

/* 社交文件夹子项（上游 nav: friend-log/friend-list/moderation） */

const SOCIAL = [['friendlog','','好友日志'],['friendtable','','好友列表'],['modlist','','玩家管理']];

/* 图表文件夹子项（上游 nav: charts-instance/charts-mutual/charts-hot-worlds） */

const CHARTS = [['activity','','活动记录'],['mutual','','共同好友'],['hotworlds','','热门世界']];

let TOKEN = localStorage.getItem('vrcwebtoken') || '';

let CURPAGE = 'dash';

let CURUSER = null;

let FEEDFILTER = '';

let FEEDDATA = [];

let FAVTAB = 'friends';

let CFG = null;

let SAVE_T = null;

const v = id =>document.getElementById(id).value.trim();

const esc = s =>String(s==null?'':s).replace(/[&<>"']/g,

  c =>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function fmtDur(s){s=Math.max(0,s|0);if(s<90)return s+'秒';const m=Math.floor(s/60);

  if(m<60)return m+'分钟';const h=Math.floor(m/60),mm=m%60;

  if(h<24)return h+'小时'+String(mm).padStart(2,'0')+'分';

  return Math.floor(h/24)+'天'+(h%24)+'小时';}

function fmtTs(ts){const d=new Date(ts*1000),p=n=>String(n).padStart(2,'0');

  return `${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;}

function fmtLast(v){ if(!v) return '—';

  if(/^\d+$/.test(v)) return fmtTs(+v);

  const d=new Date(v); if(isNaN(d)) return String(v);

  const p=n=>String(n).padStart(2,'0');

  return `${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;}

function fmtHours(h){ return h>=1 ? h+' 小时' : Math.round(h*60)+' 分钟'; }

function trustChip(t){ return (t&&t.name)?` <span class="chip" style="color:${t.color};border-color:${t.color}">${esc(t.name)}</span>`:''; }

function parseLabel(loc){

  if (!loc || !loc.includes(':')) return '';

  const fl = loc.split('~').slice(1).join('~');

  const lab = /groupAccessType\(plus\)/.test(fl)?'群组+':/groupAccessType\(members\)/.test(fl)?'仅限群组成员':/groupAccessType\(public\)/.test(fl)?'公开':/group\(/.test(fl)?'群组':/hidden\(/.test(fl)?'好友+':/friends\(/.test(fl)?'仅限好友':/canRequestInvite/.test(fl)?'邀请+':/invite\(/.test(fl)?'仅限邀请':'公开';

  return ` <span class="chip">${lab}</span>`;

}

function stateDot(state){ return `<span class="dot ${state==='online'?'on':state==='active'?'act':''}"></span>`; }

async function api(path, opts={}){
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(), opts.method === 'POST' ? 60000 : 20000);
  try {
    const r = await fetch(path, {...opts, signal: controller.signal,
      headers: {...opts.headers, ...(TOKEN ? {'X-Web-Token':TOKEN} : {})}});
    if (r.status === 401) throw new Error('网页访问认证失败，请重新打开本站并确认访问口令；这不是 VRChat 账号密码。');
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } finally { clearTimeout(timeout); }
}
const post = (p, d) => APP.client.write(p, d, {account:'a'});
const APP = {};
APP.context = new VRCXRuntime.Context(localStorage.getItem('ga') || 'a');
APP.client = new VRCXRuntime.Client(APP.context, api);
APP.tasks = new VRCXRuntime.Tasks(APP.context);
APP.pages = new VRCXRuntime.Pages(APP.context, reportError);
APP.scheduler = new VRCXRuntime.Scheduler();
APP.navigation = new VRCXRuntime.PageHistory();
let GA = APP.context.view;
let GA_EPOCH = 0;
APP.accounts = new VRCXRuntime.AccountDirectory();
const GA_NAMES = APP.accounts.names;
const GA_LABEL = {...VRCXRuntime.ACCOUNT_NAMES, m:'双号合并'};
function reportError(e){
  if (VRCXRuntime.ignored(e)) return;
  console.error(e);
  let el = document.getElementById('appError');
  if (el) { el.textContent = e.message || String(e); el.classList.remove('hidden'); }
}
function gGet(path, options={}){ return APP.client.read(path, options); }
function gPost(path, body, options={}){ return APP.client.write(path, body, options); }
function updateAccountName(account, name){
  name = APP.accounts.setName(account, name);
  const button = document.querySelector(`#gswitch button[data-g="${account}"]`);
  if (button) button.textContent = name;
  const tab = document.querySelector(`#acctSwitch button[data-v="${account==='a'?'self':'peer'}"]`);
  if (tab) tab.textContent = name;
  const heading = document.getElementById(account==='a'?'acctNameSelf':'acctNamePeer');
  if (heading) heading.textContent = name;
  const view = document.getElementById('gaView');
  if (view && GA === account) view.textContent = '视角：'+name;
  alignGSlide();
  window.MobileUI?.refresh();
}

function syncAccountIdentity(account, snapshot){
  updateAccountName(account, APP.accounts.observe(account, snapshot));
}

const badge = (txt, ok) =>`<span class="badge ${ok?'ok':'bad'}">${txt}</span>`;

const SUB_PAGES = {social: SOCIAL, charts: CHARTS};

let NAV_OPEN = {social:false, charts:false};

function refreshMergeControls(){
  document.querySelectorAll('[data-hide-in-merge]').forEach(el=>el.classList.toggle('hidden',GA==='m'));
}

function buildNav(){

  const pages = PAGES.filter(([id])=>id!=='dash' && (SUB_PAGES[id]
    ? SUB_PAGES[id].some(([child])=>pageAllowed(child)) : pageAllowed(id)));

  refreshMergeControls();

  document.getElementById('nav').innerHTML = pages.map(([id,ic,label])=>{

    if (SUB_PAGES[id]){

      return `<div><button data-fold="${id}" onclick="NAV_OPEN['${id}']=!NAV_OPEN['${id}'];buildNav()">`+

        `<span>${ic}</span><span>${label}</span><span class="dim" style="margin-left:auto">${NAV_OPEN[id]?'▾':'▸'}</span></button>`+

        (NAV_OPEN[id]?`<div style="padding-left:14px">${SUB_PAGES[id].filter(([sid])=>pageAllowed(sid)).map(([sid,sic,slab])=>

          `<button data-p="${sid}" onclick="switchPage('${sid}')"><span>${sic}</span><span>${slab}</span></button>`).join('')}</div>`:'')+`</div>`;

    }

    return `<button data-p="${id}" onclick="switchPage('${id}')"><span>${ic}</span><span>${label}</span></button>`;

  }).join('');
  buildDashNav();highlightNavigation();
}

const PAGE_ALIAS = {friendlog:'moderation', friendtable:'moderation', modlist:'moderation'};

const SOC_TAB_OF = {friendlog:'log', friendtable:'list', modlist:'mod'};

function resolvePage(p){ return PAGE_ALIAS[p] || p; }
function pageAllowed(page,view=GA){return APP.pages.allows(resolvePage(page),view);}

function highlightNavigation(){
  document.querySelectorAll('.nav button[data-p]').forEach(button=>button.classList.remove('active'));
  const id=CURPAGE==='dash'?'dash-'+DASH_IDX:CURPAGE;
  document.querySelector(`#nav button[data-p="${id}"]`)?.classList.add('active');
}

const ALL_PAGE_IDS = [...document.querySelectorAll('[id^="page-"]')].map(e =>e.id.slice(5));

const _SOC_TARGET = {};

function pageTitle(page){
  return {home:'我的',login:'账号',settings:'设置',extensions:'管理',netstats:'流量统计',moderation:'社交',history:'记录',stats:'统计',friends:'好友列表'}[page]||[...PAGES,...SOCIAL,...CHARTS].find(item=>item[0]===page)?.[2]||'好友动态';
}
function refreshPageBack(){
  const button=document.getElementById('pageBack'),previous=APP.navigation.previous;
  if(!button)return;
  button.classList.toggle('hidden',!previous);
  button.textContent=previous?'‹ 返回'+pageTitle(previous.page):'';
  const heading=document.getElementById('page-'+CURPAGE)?.querySelector?.(':scope > .page-heading');
  if(heading){heading.prepend(button);heading.classList.toggle('has-back',!!previous);}
  else document.getElementById('pageToolbar')?.appendChild(button);
}
function pageBack(){
  if(!APP.navigation.previous)return;
  if(window.MobileUI?.isMobile()&&history.state?.nav===APP.navigation.current.key){history.back();return;}
  switchPage(APP.navigation.back().page,{restoring:true});
}

function switchPage(p,options={}){

  if (SOC_TAB_OF[p]) _SOC_TARGET.t = SOC_TAB_OF[p];

  p = PAGE_ALIAS[p] || p;

  // 多仪表板虚拟页（dash-0/dash-1…）：共享 page-dash，仅切换 DASH_IDX
  const dm = /^dash-(\d+)$/.exec(p);

  if (dm){ DASH_IDX = +dm[1]; p = 'dash'; }

  if (!APP.pages.allows(p, GA)) p = 'feed';
  APP.navigation.prune(page=>APP.pages.allows(page,GA));
  if(!options.restoring)APP.navigation.enter(p);
  if (CURPAGE !== p) closeModal();
  CURPAGE = p;
  APP.pages.enter(p);

  // 高亮 = 显式集合运算：先清全部，再精确点亮当前项（含多仪表板虚拟页）。
   
  highlightNavigation();

  [...new Set(ALL_PAGE_IDS)].forEach(id=>{

    const el = document.getElementById('page-'+id);

    if (el) el.classList.toggle('hidden', id!==p);

  });

  // 手机端：底部导航高亮（面板关闭由触发方负责：mbGo / 内联 toggleMore）
  if (window.matchMedia && matchMedia('(max-width:820px)').matches){
    document.querySelectorAll('#mobileNav button').forEach(b=>{
      b.classList.toggle('active', b.dataset.mb===p);
    });
    mbCloseDrawer();
  }
  window.MobileUI?.pageEntered(p);
  refreshPageBack();
  APP.syncRealtime?.();
}

function goDashSelf(){ switchPage('dash'); }
