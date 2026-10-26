/* Mobile navigation shares scoped accounts, friend filters,
 * detail back navigation and one sheet at a time. Desktop shares the data model. */
const MobileUI = window.MobileUI = {
  restoring:false, depth:0, pending:null,
  isMobile:()=>window.matchMedia?.('(max-width:820px), (max-width:1024px) and (pointer:coarse)').matches,
  init(){
    if(!this.isMobile()) return;
    history.replaceState({vrcx:true,page:'feed',depth:0,nav:APP.navigation.current.key},'');
    window.addEventListener('popstate',event=>{
      let target=event.state?.vrcx?event.state:{page:'feed',depth:0};
      const unavailable=!APP.pages.allows(target.page,GA);
      if(unavailable)target={page:'feed',depth:0};
      if(target.depth>0 && !DETAIL_CURRENT){history.back();return;}
      this.restoring=true;
      if(this.depth>target.depth){
        if(target.depth>0) detailBack(true); else closeModal(true);
      }
      this.depth=target.depth||0;
      mbSheetsClose();closeQS();
      APP.navigation.restore(target.nav,target.page);
      if(target.page!==CURPAGE) switchPage(target.page,{restoring:true});
      refreshPageBack();
      this.restoring=false;this.refresh();
      if(unavailable)history.replaceState({vrcx:true,page:CURPAGE,depth:0,nav:APP.navigation.current.key},'');
    });
    document.addEventListener('keydown',event=>{
      if(event.key!=='Escape') return;
      if(!document.getElementById('modal').classList.contains('hidden')) closeModal();
      else {mbSheetsClose();closeQS();}
    });
    this.refresh();
  },
  pageEntered(page){
    if(this.isMobile()&&!this.restoring&&history.state?.vrcx&&history.state.page!==page){
      this.depth=0;history.pushState({vrcx:true,page,depth:0,nav:APP.navigation.current.key},'');
      window.scrollTo?.({top:0});
    }
    this.refresh();
  },
  detailOpened(){
    if(!this.isMobile()||this.restoring) return;
    this.depth++;history.pushState({vrcx:true,page:CURPAGE,depth:this.depth,nav:APP.navigation.current.key},'');
  },
  detailBack(){if(this.isMobile()&&this.depth&&!this.restoring) history.back();},
  detailClosed(){
    if(!this.isMobile()||this.restoring||!this.depth) return;
    this.depth=0;history.replaceState({vrcx:true,page:CURPAGE,depth:0,nav:APP.navigation.current.key},'');
  },
  refresh(){
    const title=document.getElementById('mobileTitle');
    if(title) title.textContent=CURPAGE==='feed'&&FEED_FRIEND?'单人动态':pageTitle(CURPAGE);
    const label=document.getElementById('mobileAccountName');
    if(label) label.textContent=GA==='m'?'双号合并':GA_NAMES[GA];
    document.querySelectorAll('[data-hide-in-merge]').forEach(button=>button.classList.toggle('hidden',GA==='m'));
    if(!FEED_FRIEND){const selection=document.getElementById('mobileFeedSelection');if(selection){selection.classList.add('hidden');selection.innerHTML='';}}
    document.querySelectorAll('#mobileNav [data-mb]').forEach(button=>{
      const single=CURPAGE==='feed'&&!!FEED_FRIEND;
      const page=button.dataset.mb==='friendfeed'?'feed':button.dataset.mb;
      const available=page==='home'||APP.pages.allows(page,GA);
      const accountPickerFlow=page==='favorites';
      const hidden=GA==='m'&&!available&&!accountPickerFlow;
      button.classList.toggle('hidden',hidden);
      button.setAttribute?.('aria-hidden',hidden?'true':'false');
      const selected=button.dataset.mb==='friendfeed'?single:button.dataset.mb==='feed'?CURPAGE==='feed'&&!single:
        button.dataset.mb===CURPAGE || button.dataset.mb==='home'&&!['feed','locations','favorites'].includes(CURPAGE);
      button.classList.toggle('active',!hidden&&selected);button.setAttribute?.('aria-current',!hidden&&selected?'page':'false');
    });
  },
  go(page,keepFriend=false){
    if(page==='friendfeed')return mobileFriendFeed();
    if(!pageAllowed(page)) {this.pending=page;mobileAccounts();return;}
    mbSheetsClose();switchPage(page);
    if(page==='feed'&&!keepFriend&&FEED_FRIEND){resetMobileFeedFilters();return setFeedFriend('');}
  }
};
function mobileGo(page){return MobileUI.go(page);}
function mobileAccounts(){
  const sheet=document.getElementById('moreSheet'),grid=document.getElementById('moreGrid');
  mbCloseDrawer();closeQS();
  document.getElementById('sheetTitle').textContent=MobileUI.pending?'选择操作账号':'选择账号';
  grid.innerHTML=`<div class="account-options">${['a','b','m'].map(account=>`<button class="account-option ${GA===account?'selected':''}" onclick="mobileSelectAccount('${account}')"><span class="account-mark ${account}">${account==='m'?'合':account.toUpperCase()}</span><span><strong>${esc(account==='m'?'双号合并':GA_NAMES[account])}</strong><small>${account==='m'?'同时查看两个账号的动态与好友':'独立的登录会话与好友数据'}</small></span><span>${GA===account?'✓':'›'}</span></button>`).join('')}</div>`;
  sheet.classList.remove('hidden');document.body.classList.add('sheet-open');
}
function mobileSelectAccount(account){
  const pending=MobileUI.pending;MobileUI.pending=null;
  switchGA(account);mbSheetsClose();MobileUI.refresh();
  if(pending&&pageAllowed(pending,account)) switchPage(pending);
}
function mobileMenu(){
  const groups=[['社交',[['notifs','通知'],['search','搜索'],['friendlog','好友日志'],['modlist','玩家管理']]],
    ['个人',[['login','账号'],['avatars','我的模型'],['push','推送'],['settings','设置']]],
    ['工具',[['dash','仪表板'],['tools','工具'],['direct','直达'],['netstats','流量']]]];
  document.getElementById('sheetTitle').textContent='全部功能';
  const visible=groups.map(([name,items])=>[name,items.filter(([page])=>pageAllowed(page))]).filter(([,items])=>items.length);
  document.getElementById('moreGrid').innerHTML=visible.map(([name,items])=>`<section class="menu-group"><h3>${name}</h3>${items.map(([page,label])=>`<button onclick="mobileGo('${page}')"><span>${label}</span><span>›</span></button>`).join('')}</section>`).join('')||'<p class="dim">当前视角没有可用的其他功能。</p>';
  document.getElementById('moreSheet').classList.remove('hidden');document.body.classList.add('sheet-open');
}
async function loadMobileHome(){
  const task=APP.tasks.begin('mobile-home');
  const result=await gGet('/api/self');if(!task.current()) return;
  const accounts=GA==='m'?Object.entries(result._accounts||{}):[[GA,result]];
  document.getElementById('mobileProfile').innerHTML=accounts.map(([account,me])=>{
    const state=VRCXRuntime.loginLabel(me,result._errors?.[account]);
    if(state!=='已登录') me=null;
    syncAccountIdentity(account,me);
    return `<div class="profile-summary">${me?.thumb?`<img ${mediaAttrs(me.thumb,account)} alt="">`:`<span class="profile-initial">${esc((me?.name||GA_NAMES[account]).slice(0,1))}</span>`}<div><strong>${esc(me?.name||GA_NAMES[account])}</strong><p>${state} · ${esc(ST[me?.status]||'—')}</p></div><button class="ghost" onclick="mobileGo('login')">账号</button></div>`;
  }).join('');
}
function mobileFeedSearch(value){return setFeedSearch(value);}

function resetMobileFeedFilters(){
  for(const id of ['feedSearch','mobileFeedSearch']){
    const input=document.getElementById(id);if(input)input.value='';
  }
  FEEDFILTER='';STAR_ONLY=false;
  document.getElementById('starBtn')?.classList.remove('active');
  document.querySelectorAll('#feedFilter [data-f],#mobileFeedFilter [data-f]').forEach(button=>button.classList.toggle('active',button.dataset.f===''));
}
function mobileFeedPickerCurrent(picker){
  return !!picker&&MobileUI.friendPicker===picker&&picker.task.current()&&
    picker.account===GA&&picker.epoch===GA_EPOCH&&
    !document.getElementById('moreSheet').classList.contains('hidden')&&
    !!document.getElementById('mobileFeedFriendSearch')?.isConnected;
}
async function mobileFriendFeed(){
  MobileUI.go('feed',true);closeQS();
  const picker=MobileUI.friendPicker={task:APP.tasks.begin('mobile-feed-friends'),account:GA,epoch:GA_EPOCH,friends:[],loaded:false};
  document.getElementById('sheetTitle').textContent='选择好友';
  document.getElementById('moreGrid').innerHTML='<div class="friend-feed-picker"><label class="mobile-search"><input id="mobileFeedFriendSearch" aria-label="搜索好友列表" placeholder="搜索好友" oninput="renderMobileFeedFriends(this.value)"></label><div id="mobileFeedFriendList" class="friend-feed-list" aria-live="polite"></div></div>';
  document.getElementById('moreSheet').classList.remove('hidden');document.body.classList.add('sheet-open');
  renderMobileFeedFriends();
  try{
    const result=await gGet('/api/friends');
    if(!mobileFeedPickerCurrent(picker))return;
    picker.friends=result.friends||[];picker.loaded=true;
    window._FRIENDS=picker.friends;
    renderMobileFeedFriends(v('mobileFeedFriendSearch'));
  }catch(error){
    if(!mobileFeedPickerCurrent(picker)||VRCXRuntime.ignored(error))return;
    document.getElementById('mobileFeedFriendList').innerHTML='<p class="dim">好友列表加载失败，请稍后重试。</p><button class="ghost" onclick="mobileFriendFeed()">重试</button>';
  }
}
function renderMobileFeedFriends(query=''){
  const picker=MobileUI.friendPicker;
  if(!mobileFeedPickerCurrent(picker))return;
  const target=document.getElementById('mobileFeedFriendList');
  if(!picker.loaded){target.innerHTML='<p class="dim">正在加载好友…</p>';return;}
  const q=query.trim().toLowerCase(),name=f=>f.name||f.display_name||f.id;
  const friends=picker.friends.filter(f=>!q||name(f).toLowerCase().includes(q)||f.id.toLowerCase().includes(q))
    .sort((a,b)=>name(a).localeCompare(name(b),'zh-CN'));
  target.innerHTML=friends.map(friend=>`<button class="feed-friend-option ${friend.id===FEED_FRIEND?'selected':''}" data-friend-id="${esc(friend.id)}" onclick="${esc(`chooseMobileFeedFriend(${JSON.stringify(friend.id)})`)}"><span>${esc(name(friend))}</span><small>${picker.account==='m'?esc(friend._src==='ab'?'A+B 号':friend._src==='b'?'B 号':'A 号'):''}</small><span>${friend.id===FEED_FRIEND?'✓':'›'}</span></button>`).join('')||'<p class="dim">没有匹配的好友。</p>';
}
function chooseMobileFeedFriend(id){
  const picker=MobileUI.friendPicker;
  if(!mobileFeedPickerCurrent(picker)||!picker.friends.some(friend=>friend.id===id))return;
  APP.tasks.cancel('mobile-feed-friends');MobileUI.friendPicker=null;
  mbSheetsClose();resetMobileFeedFilters();
  const result=setFeedFriend(id);
  window.scrollTo?.({top:0});return result;
}
function renderMobileFeedSelection(){
  const box=document.getElementById('mobileFeedSelection');if(!box)return;
  box.classList.toggle('hidden',!FEED_FRIEND);
  if(FEED_FRIEND){
    const friend=(window._FRIENDS||[]).find(f=>f.id===FEED_FRIEND);
    const name=friend?.name||FEEDDATA.find(e=>e.friend_id===FEED_FRIEND)?.display_name||FEED_FRIEND;
    box.innerHTML=`<div><small>正在查看</small><strong>${esc(name)}</strong></div><button class="ghost" onclick="mobileFriendFeed()">换一位</button><button class="ghost" onclick="mobileGo('feed')">全部动态</button>`;
  }else box.innerHTML='';
  MobileUI.refresh();
}
function mobileFriendSearch(value){window._MOBILE_FRIEND_QUERY=value;renderLoc();}
function renderMobileFeed(rows,total,size){
  renderMobileFeedSelection();
  const target=document.getElementById('mobileFeed');if(!target) return;
  const expanded=new Set([...target.querySelectorAll('details[open]')].map(el=>el.dataset.key));
  let day='',html='';
  for(const {e} of rows){
    const date=new Date(e.ts*1000),group=date.toLocaleDateString('zh-CN',{month:'long',day:'numeric'});
    if(day!==group){day=group;html+=`<div class="timeline-day">${esc(group)}</div>`;}
    const friend=(window._FRIENDS||window._LOCF||[]).find(f=>f.id===e.friend_id);
    const key=VRCXFeed.identity(e);
    html+=`<article class="timeline-card"><div class="timeline-avatar">${friend?.thumb?`<img ${mediaAttrs(friend.thumb,friend._detailSource||e._src||GA)} alt="">`:`<span>${esc((e.display_name||'?').slice(0,1))}</span>`}</div><div class="timeline-content"><div class="timeline-person"><button class="text-button" onclick="openFriend('${esc(e.friend_id)}','${e._src||''}')">${esc(e.display_name)}</button><time>${date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</time></div><div class="timeline-event"><span class="event-marker ${esc(e.event)}"></span><strong>${esc(WEB_OFFLINE_LABEL(e))}</strong>${srcChip(e._src)}</div><div class="timeline-detail">${feedDetailCell(e)}</div><details data-key="${esc(key)}" ${expanded.has(key)?'open':''}><summary>详细信息</summary>${feedExpandRow(e)}</details></div></article>`;
  }
  if(!rows.length) html='<div class="mobile-empty"><strong>暂无动态</strong><p>可以调整筛选，或稍后再查看。</p></div>';
  html+=`<div class="timeline-pagination"><span>${feedCountText(total)}</span>${FEED_PAGE>0?'<button class="ghost" onclick="FEED_PAGE--;renderFeed()">上一页</button>':''}${(FEED_PAGE+1)*size<total?'<button class="ghost" onclick="FEED_PAGE++;renderFeed();window.scrollTo({top:0})">下一页</button>':''}</div>`;
  if(target.innerHTML!==html) target.innerHTML=html;
}

function renderMobileNotifs(notifications){
  const target=document.getElementById('mobileNotifs');if(!target) return;
  target.innerHTML=notifications.map(n=>`<article class="notification-card"><div class="notification-meta"><span>${esc(NT_LABEL[n.type]||n.type)}</span><time>${fmtLast(n.created)}</time></div>
    ${n.sender_id?`<button class="text-button" onclick="openFriend('${esc(n.sender_id)}')">${esc(n.sender||'')}</button>`:`<strong>${esc(n.sender||'')}</strong>`}
    ${n.imageUrl?`<img ${mediaAttrs(n.imageUrl)} alt="">`:''}${n.group?`<p class="dim">${esc(n.group)}</p>`:''}<p>${esc(n.message||'')}</p>
    <div class="row">${n.type==='friendRequest'?`<button onclick="notifAct('accept','${esc(n.id)}')">接受</button>`:''}${!n.seen?`<button class="ghost" onclick="notifAct('see','${esc(n.id)}')">已读</button>`:''}<button class="ghost" onclick="notifAct('hide','${esc(n.id)}')">隐藏</button></div></article>`).join('')||'<div class="mobile-empty">没有通知</div>';
}
