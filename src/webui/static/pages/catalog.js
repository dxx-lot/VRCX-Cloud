/* ---------- 收藏 ---------- */

let FAVTYPE = 'friend', FAVGROUP = null, FAVD = null;

function setFavType(btn){

  FAVTYPE = btn.dataset.t; FAVGROUP = null;

  document.querySelectorAll('#favTabs .tabbtn').forEach(b=>b.classList.toggle('active', b===btn));

  loadFavorites();

}

async function loadFavorites(){
  const task = APP.tasks.begin('loadFavorites');

  try{

    const r = await gGet('/api/favgroups?type='+FAVTYPE);
    if (!task.current()) return;

    FAVD = r;
    if(!FAVGROUP || !(r.groups||[]).some(g=>g.name===FAVGROUP)) FAVGROUP=r.groups?.[0]?.name||null;

    document.getElementById('favGTitle').textContent =

      {friend:'在线收藏夹', world:'在线收藏夹', avatar:'在线收藏夹'}[FAVTYPE];

    renderFavGroups(); renderFavItems();

  }catch(e){ reportError(e); }

}

function renderFavGroups(){

  const gs = FAVD.groups || [];

  const counts = {};

  (FAVD.items||[]).forEach(i=>counts[i.group]=(counts[i.group]||0)+1);

  let html = gs.map(g=>

    `<div class="frow" onclick="selectFavGroup(this.dataset.group)" data-group="${esc(g.name)}" style="${FAVGROUP===g.name?'background:var(--hov);border-radius:6px':''}">`+

    `<div><div class="name">${esc(g.displayName||g.name)}</div>`+

    `<div class="dim" style="font-size:12px">${esc(g.visibility==='private'?'私人':g.visibility==='friends'?'仅好友':'公开')}</div></div>`+

    `<span class="dim" style="margin-left:auto;font-size:12px">${counts[g.name]||0} 个</span>`+

    `<button class="ghost mini" title="重命名" onclick="event.stopPropagation();renameGroup(this.closest('[data-group]').dataset.group)">重命名</button>`+

    `<button class="ghost mini" title="清空此收藏夹" onclick="event.stopPropagation();clearGroup(this.closest('[data-group]').dataset.group)">清空</button></div>`).join('');

  html += `<div class="rgroup">本地收藏夹</div>`+

    `<div class="frow" style="cursor:default"><div><div class="name">Favorites</div></div>`+

    `<span class="dim" style="margin-left:auto;font-size:12px">${counts['Favorites']||0}</span></div>`;

  document.getElementById('favGroups').innerHTML = html || '<div class="dim" style="font-size:13px">没有收藏夹</div>';

  if (!FAVGROUP && gs.length) FAVGROUP = gs[0].name;

}

function renderFavItems(){

  const items = (FAVD.items||[]).filter(i=>!FAVGROUP || i.group===FAVGROUP);

  document.getElementById('favSelName').textContent = (FAVD.groups||[]).find(g=>g.name===FAVGROUP)?.displayName || FAVGROUP || '全部';

  document.getElementById('favSelCount').textContent = `${items.length} 个`;

  let html;

  const rmBtn = i =>`<button class="ghost mini" title="移出收藏" onclick="event.stopPropagation();removeFavorite('${esc(i.fav_id)}')">移出</button>`;

  if (FAVTYPE==='friend'){

    html = items.map(i=>

      `<div class="frow" onclick="openFriend('${esc(i.fid)}')">${i.thumb?`<img ${mediaAttrs(i.thumb)} style="width:30px;height:30px;border-radius:50%;object-fit:cover">`:''}`+

      `<span class="dot ${i.online?'on':''}"></span><span class="name">${esc(i.name)}</span>`+

      `<span class="fmeta" style="margin-left:auto">${i.online?'在线':'离线'}</span>${rmBtn(i)}</div>`).join('')

      || '<div class="dim">无数据</div>';

  } else if (FAVTYPE==='world'){

    html = `<div class="locgrid">` + (items.map(i=>

      `<div class="loccard"><div onclick="openWorld('${esc(i.fid)}')" style="cursor:pointer">`+

      worldRow({id:i.fid, name:i.name, thumb:i.thumb, author:'', visits:null})+`</div>`+

      `<button class="ghost mini" style="width:100%;margin-top:4px" onclick="removeFavorite('${esc(i.fav_id)}')">移出收藏</button></div>`).join('')) + `</div>`;

    if (!items.length) html = '<div class="dim">无数据</div>';

  } else {

    html = `<div class="avgrid">` + (items.map(i=>

      `<div class="avitem" onclick="openAvatarDlg('${esc(i.fid)}')">${i.image?`<img ${mediaAttrs(i.image)}>`:''}`+

      `<div class="n">${esc(i.name||i.fid)}</div>`+

      `<button class="ghost mini" style="width:100%;margin-top:4px" onclick="removeFavorite('${esc(i.fav_id)}')">移出收藏</button></div>`).join('') || '') + `</div>`;

    if (!items.length) html = '<div class="dim">无数据</div>';

  }

  document.getElementById('favItems').innerHTML = html;

}

async function importFavGroups(){
  const raw = prompt('粘贴导出的收藏夹 JSON（格式: {"type":"friend","groups":[{"name":"组名","items":["usr_…"]}]}）:');
  if (!raw) return;
  let payload;
  try{ payload = JSON.parse(raw); }catch(e){ alert('JSON 解析失败'); return; }
  payload.type = payload.type || FAVTYPE;
  const r = await gPost('/api/favgroup-import', payload);
  alert(`导入完成：成功 ${r.ok_count} 条，失败 ${r.fail_count} 条`);
  loadFavorites();
}
function selectFavGroup(name){
  FAVGROUP=name;renderFavGroups();renderFavItems();
}
async function favoriteWrite(body){
  const task=APP.tasks.begin('favorite-write'),account=GA;
  try{
    const result=await gPost('/api/favorite-op',body,{account});
    if(!task.current()) return;
    if(!result.ok) throw new Error(result.error||'操作失败');
    await loadFavorites();
  }catch(e){if(task.current()&&!VRCXRuntime.ignored(e))reportError(e);}
}
async function renameGroup(group){
  const entry=FAVD?.groups?.find(g=>g.name===group);
  const name=prompt('收藏夹名称:',entry?.displayName||group);
  if(!name?.trim()) return;
  return favoriteWrite({op:'rename_group',type:FAVTYPE,group,displayName:name.trim()});
}
async function clearGroup(group){
  if(!confirm('清空这个收藏夹里的全部收藏？')) return;
  return favoriteWrite({op:'clear_group',type:FAVTYPE,group});
}
async function removeFavorite(id){
  return favoriteWrite({op:'remove',objectId:id});
}
async function createFavGroup(){
  const empty=FAVD?.groups?.find(g=>!(FAVD.items||[]).some(i=>i.group===g.name));
  if(!empty){alert('没有空的收藏夹，请先清空一个已有收藏夹。');return;}
  return renameGroup(empty.name);
}

/* ---------- 统计 ---------- */

async function loadStats(){
  const task = APP.tasks.begin('loadStats');

  try{

    const days = v('statDays') || '7';

    const r = await gGet('/api/stats?days='+days);
    if (!task.current()) return;

    const hmax = Math.max(1, ...r.friends.map(f=>f.hours));

    document.getElementById('statFriends').innerHTML =

      r.friends.map(f=>`<div class="bar-row"><span class="bar-name">${esc(f.name)}</span>`+

        `<span class="bar-track"><span class="bar-fill" style="width:${Math.round(f.hours/hmax*100)}%"></span></span>`+

        `<span class="bar-val">${fmtHours(f.hours)} · ${f.sessions}次${f.active_hours>0.05?` · <span style="color:#2563eb">网页 ${fmtHours(f.active_hours)}</span>`:''}</span></div>`).join('')

      || '<div class="dim">暂无数据（记录积累中）</div>';

    const wmax = Math.max(1, ...r.worlds.map(w=>w.visits));

    document.getElementById('statWorlds').innerHTML =

      r.worlds.map((w,i)=>`<div class="bar-row"><span class="bar-name" title="${esc(w.name)}">${i+1}. ${esc(w.name)}</span>`+

        `<span class="bar-track"><span class="bar-fill" style="width:${Math.round(w.visits/wmax*100)}%;background:#4cc2a1"></span></span>`+

        `<span class="bar-val">${w.visits} 次</span></div>`).join('')

      || '<div class="dim">暂无数据</div>';

    // 每日柱状图

    const dmax = Math.max(0.5, ...r.daily.map(d=>d.hours));

    document.getElementById('statDaily').innerHTML =

      r.daily.map(d=>{

        const pct = Math.max(3, Math.round(d.hours/dmax*100));

        return `<div style="flex:1;text-align:center" title="${d.date}: ${d.hours}小时 / ${d.logins}次上线">`+

          `<div style="height:${pct}%;background:var(--accent);border-radius:4px 4px 0 0;margin:auto;width:70%"></div>`+

          `<div class="dim" style="font-size:9px;margin-top:3px">${d.date.slice(5)}</div></div>`;

      }).join('') || '<div class="dim">暂无数据</div>';

    // 热力图

    const map = {}; r.heatmap.forEach(([d,h,c])=>map[d+'-'+h]=c);

    let html = '<div class="lab"></div>';

    for (let h=0; h<24; h++)

      html += `<div class="lab" style="justify-content:center">${h%2? '' : h}</div>`;

    for (const d of [1,2,3,4,5,6,0]){

      html += `<div class="lab">${WD[d]}</div>`;

      for (let h=0; h<24; h++){

        const c = map[d+'-'+h] || 0;

        const a = c ? (0.25 + 0.75*c/(r.heatmap_max||1)) : 0;

        html += `<div class="cell" style="${c?`background:rgba(139,92,246,${a.toFixed(2)})`:''}" title="${WD[d]} ${h}点 · ${c}次"></div>`;

      }

    }

    document.getElementById('statHeat').innerHTML = html;

  }catch(e){ reportError(e); }

}

/* ---------- 搜索 ---------- */

async function doSearch(){
  const task = APP.tasks.begin('doSearch');

  const q = v('sq');

  if (!q) return;

  document.getElementById('searchUsers').innerHTML = '<div class="dim">搜索中…</div>';

  document.getElementById('searchWorlds').innerHTML = '<div class="dim">搜索中…</div>';

  const [u, w] = await Promise.all([

    gGet('/api/search?q='+encodeURIComponent(q)),

    gGet('/api/world-search?q='+encodeURIComponent(q))]);
  if (!task.current()) return;

  document.getElementById('searchUsers').innerHTML = (u.users||[]).map(userRow).join('')

    || `<div class="dim">${u.error? ' '+esc(u.error) : '没有找到用户'}</div>`;

  document.getElementById('searchWorlds').innerHTML = (w.worlds||[]).map(worldRow).join('')

    || `<div class="dim">${w.error? ' '+esc(w.error) : '没有找到世界'}</div>`;

}

function userRow(u){

  const color = u.trust && u.trust.color ? u.trust.color : 'inherit';

  const state = u.state==='online' ? '<span class="dot on"></span>在线'

    : u.state==='active' ? '<span class="dot act"></span>在线（未进世界）' : '<span class="dot"></span>离线';

  return `<div class="srow" onclick="openFriend('${esc(u.id)}')">`+

    (u.thumb?`<img ${mediaAttrs(u.thumb)}>`:'<img>')+

    `<div><div class="name" style="color:${color}">${esc(u.name)}${trustChip(u.trust)}</div>`+

    `<div class="dim" style="font-size:12px">${state}${u.desc?' · '+esc(u.desc):''}</div></div></div>`;

}

function worldRow(w){

  return `<div class="srow" onclick="openWorld('${esc(w.id)}')">`+

    (w.thumb?`<img ${mediaAttrs(w.thumb)}>`:'<img>')+

    `<div><div class="name">${esc(w.name)}</div>`+

    `<div class="dim" style="font-size:12px">${esc(w.author||'')}${w.visits!=null?' · '+w.visits+' 次访问':''}${w.capacity?' · 容量'+w.capacity:''}</div></div></div>`;

}

/* ---------- 记录 ---------- */

async function loadHistory(){
  const task = APP.tasks.begin('loadHistory');

  try{

    const name = encodeURIComponent(v('qname'));

    const type = encodeURIComponent(v('qtype'));

    const days = v('qdays') || '3';

    const r = await gGet(`/api/history?name=${name}&days=${days}&type=${type}`);
    if (!task.current()) return;

    const rows = r.events.map(e =>{

      const C = {online:'#16a34a', offline:'#ef4444', location:'#0369a1',

                 active:'#2563eb', status:'#b45309', desc:'#6d28d9', avatar:'#be185d'};

      const c = C[e.event] || '#64748b';

      const detail = `<span style="color:${c};font-weight:600">${WEB_OFFLINE_LABEL(e)}</span>` +

        (e.event === 'online'

          ? (e.world_name ? `· 世界: ${esc(e.world_name)}` : '') +

            (e.status_description ? ` <span class="dim">· ${esc(e.status_description)}</span>` : '')

        : e.event === 'location'

        ? `→ ${esc(e.world_name||'')}${e.instance_label?`（${esc(e.instance_label)}）`:''}`

        : e.event === 'active'

        ? `（未进世界）${e.previous?` · 离开 ${esc(e.previous)}`:''}`

        : e.event === 'status'

        ? `· ${esc(e.status_description||'')}`

        : e.event === 'desc'

        ? `· ${esc((e.status_description||'').slice(0,40))}`

        : e.event === 'avatar'

        ? ''

        : `· 在线 ${e.duration ? fmtDur(e.duration) : '时长未知'}` +

          (e.world_name ? ` · 最后位置 ${esc(e.world_name)}` : ''));

      return `<tr><td class="dim">${fmtTs(e.ts)}</td>` +

        `<td><span class="name">${esc(e.display_name)}</span></td><td>${detail}</td></tr>`;

    });

    document.getElementById('history').innerHTML =

      rows.length ? rows.join('') : '<tr><td colspan="3" class="dim">暂无记录</td></tr>';

  }catch(e){ reportError(e); }

}

/* ---------- 通知 ---------- */

const NT_LABEL = {invite:'邀请', requestInvite:'申请加入', friendRequest:'好友申请',

  boop:'戳一戳', inviteResponse:'邀请回应', requestInviteResponse:'加入请求回应',

  'group.announcement':'群组公告', 'group.event.created':'群组活动创建',

  'group.joined':'群组变动', 'group.left':'群组变动', badge:'获得徽章',

  newFriend:'新的好友', requestDeny:'拒绝加入申请', friendRequestHidden:'忽略的好友申请'};

let NT_PAGE = 0, NT_DATA = [];

async function loadNotifs(){
  const task = APP.tasks.begin('loadNotifs');

  try{

    const r = await gGet('/api/notifications');
    if (!task.current()) return;

    NT_DATA = r.items || [];

    const sel = document.getElementById('ntType');

    const cur = sel.value;

    const types = [...new Set(NT_DATA.map(n=>n.type||''))];

    sel.innerHTML = '<option value="">全部类型</option>' +

      types.map(t=>`<option value="${esc(t)}">${esc(NT_LABEL[t]||t)}</option>`).join('');

    sel.value = cur;

    renderNotifs();

  }catch(e){ reportError(e); }

}

function renderNotifs(){

  const t = document.getElementById('ntType').value;

  const q = (v('ntSearch')||'').toLowerCase();

  let list = NT_DATA.filter(n=>(!t || n.type===t) &&

    (!q || (n.message||'').toLowerCase().includes(q) || (n.sender||'').toLowerCase().includes(q)));

  const size = +(document.getElementById('ntPageSize').value||20);

  const pages = Math.max(1, Math.ceil(list.length/size));

  if (NT_PAGE>=pages) NT_PAGE=pages-1;

  window.renderMobileNotifs?.(list.slice(NT_PAGE*size,(NT_PAGE+1)*size));
  document.getElementById('ntBody').innerHTML = list.slice(NT_PAGE*size,(NT_PAGE+1)*size).map(n=>{

    const acts = [];

    if (n.type==='friendRequest')

      acts.push(`<button class="ghost mini" onclick="notifAct('accept','${esc(n.id)}')">接受</button>`);

    if (!n.seen) acts.push(`<button class="ghost mini" onclick="notifAct('see','${esc(n.id)}')">已读</button>`);

    acts.push(`<button class="ghost mini" onclick="notifAct('hide','${esc(n.id)}')">隐藏</button>`);

    return `<tr><td class="dim">${fmtLast(n.created)}</td>`+

      `<td><span class="chip">${esc(NT_LABEL[n.type]||n.type||'—')}</span></td>`+

      `<td>${n.sender_id?`<span class="name" style="cursor:pointer" onclick="openFriend('${esc(n.sender_id)}')">${esc(n.sender)}</span>`:esc(n.sender||'—')}</td>`+

      `<td class="dim">${esc(n.group||'')}</td>`+

      `<td>${n.imageUrl?`<img ${mediaAttrs(n.imageUrl)} style="width:52px;height:30px;border-radius:4px;object-fit:cover">`:'—'}</td>`+

      `<td>${esc(n.message||'')}</td>`+

      `<td class="row" style="border:none">${acts.join('')}</td></tr>`;

  }).join('')

    || '<tr><td colspan="5" class="dim">没有通知</td></tr>';

  let pg='';

  for (let p=0;p<pages;p++) pg += `<button class="mini ${p===NT_PAGE?'':'ghost'}" onclick="NT_PAGE=${p};renderNotifs()">${p+1}</button>`;

  document.getElementById('ntPager').innerHTML =

    `<span class="dim" style="font-size:12px;margin-right:6px">共 ${list.length} 条</span>`+

    (pages>1?`<button class="ghost mini" onclick="if(NT_PAGE>0){NT_PAGE--;renderNotifs()}">‹ 上一页</button>${pg}`+

      `<button class="ghost mini" onclick="if(NT_PAGE<${pages-1}){NT_PAGE++;renderNotifs()}">下一页 ›</button>`:'');

}

async function notifAct(op, id, extra){

  const r = await gPost('/api/notification-act', Object.assign({op, id}, extra||{}));

  if (r.ok) loadNotifs();

  else alert('操作失败: ' + (r.error||''));

}

/* ---------- 头像 ---------- */

function avCard(a, cur){

  return `<div class="avitem ${cur?'cur':''}" onclick="openAvatarDlg('${esc(a.id)}')">`+

    (cur?'<div class="curtag">当前</div>':'')+

    `<img ${mediaAttrs(a.thumb||a.image||'')}>`+

    `<div class="n" title="${esc(a.name)}">${esc(a.name)}</div>`+

    (a.author?`<div class="dim" style="font-size:11px">by ${esc(a.author)}</div>`:'')+`</div>`;

}

let AV_VIEW = 'grid';

function setAvView(m){

  AV_VIEW = m;

  document.getElementById('avViewGrid').classList.toggle('active', m==='grid');

  document.getElementById('avViewList').classList.toggle('active', m==='list');

  renderAvatars();

}

function avFiltered(list){

  const q = (v('avSearch')||'').toLowerCase();

  return (list||[]).filter(a=>!q || (a.name||'').toLowerCase().includes(q));

}

function avRow(a, cur){

  return `<tr onclick="openAvatarDlg('${esc(a.id)}')" style="cursor:pointer">`+

    `<td>${(a.thumb||a.image)?`<img ${mediaAttrs(a.thumb||a.image)} style="width:36px;height:36px;border-radius:8px;object-fit:cover">`:''}</td>`+

    `<td><span class="name">${esc(a.name)}</span>${cur?' <span class="chip" style="color:var(--green);border-color:var(--green)">当前</span>':''}</td>`+

    `<td class="dim">${esc(a.author||'')}</td>`+

    `<td class="dim">${esc(a.release||'')}</td></tr>`;

}

async function loadAvatars(){
  const task = APP.tasks.begin('loadAvatars');

  try{

    const r = await gGet('/api/avatars');
    if (!task.current()) return;

    window._AVD = r;

    renderAvatars();

  }catch(e){ reportError(e); }

}

function renderAvatars(){

  const r = window._AVD || {};

  const cur = r.current;

  document.getElementById('curAvatarCard').style.display = cur ? 'block' : 'none';

  if (cur) document.getElementById('curAvatar').innerHTML =

    `<div class="srow" style="cursor:default">${cur.thumb||cur.image?`<img ${mediaAttrs(cur.thumb||cur.image)}>`:'<img>'}`+

    `<div><div class="name">${esc(cur.name)}</div>`+

    `<div class="dim" style="font-size:12px">by ${esc(cur.author||'?')}${cur.own?'（你自己的）':''}</div></div></div>`;

  const own = avFiltered(r.own);

  const fav = avFiltered(r.favorites);

  document.getElementById('avatarsOwn').innerHTML = AV_VIEW==='grid'

    ? `<div class="avgrid">` + (own.map(a=>avCard(a, cur&&cur.id===a.id)).join('')

       || '<div class="dim" style="font-size:13px">你还没有上传自己的模型（正在穿的多半是别人的公共模型，可在下方收藏里切换）</div>') + `</div>`

    : `<table><thead><tr><th style="width:46px"></th><th>名称</th><th>作者</th><th>状态</th></tr></thead><tbody>`+

      (own.map(a=>avRow(a, cur&&cur.id===a.id)).join('') ||

       '<tr><td colspan="4" class="dim" style="font-size:13px">你还没有上传自己的模型</td></tr>')+`</tbody></table>`;

  document.getElementById('avatarsFav').innerHTML = AV_VIEW==='grid'

    ? `<div class="avgrid">` + (fav.map(a=>avCard(a, cur&&cur.id===a.id)).join('')

       || '<div class="dim" style="font-size:13px">收藏夹里没有模型（在游戏里收藏别人的模型后会出现在这里）</div>') + `</div>`

    : `<table><thead><tr><th style="width:46px"></th><th>名称</th><th>作者</th><th>状态</th></tr></thead><tbody>`+

      (fav.map(a=>avRow(a, cur&&cur.id===a.id)).join('') ||

       '<tr><td colspan="4" class="dim" style="font-size:13px">收藏夹里没有模型</td></tr>')+`</tbody></table>`;

}

async function selectAvatar(id){

  const r = await gPost('/api/avatar-select', {id});

  if (r.ok){ closeModal(); loadAvatars(); loadSelf(); }

  else alert('切换失败: ' + (r.error||''));

}

/* ---------- 管理 ---------- */

function setSocTab(btn){

  if (!btn) return;

  const t = btn.dataset.t;

  document.querySelectorAll('#socTabs .tabbtn').forEach(b=>b.classList.toggle('active', b===btn));

  document.getElementById('soc-log').classList.toggle('hidden', t!=='log');

  document.getElementById('soc-list').classList.toggle('hidden', t!=='list');

  document.getElementById('soc-mod').classList.toggle('hidden', t!=='mod');

  if (t==='log') loadFriendLog();

  if (t==='list') loadFriendTable();

  if (t==='mod') loadModerations();

}

const FL_LABEL = {'friend-add':'新的好友','friend-delete':'删除好友',

  'trust':'等级变动','name':'昵称变动'};

const FL_COLOR = {'friend-add':'#16a34a','friend-delete':'#ef4444',

  'trust':'#b45309','name':'#6d28d9'};

async function loadFriendLog(){
  const task = APP.tasks.begin('loadFriendLog');

  try{

    const t = document.getElementById('flType').value;

    const q = encodeURIComponent(v('flSearch'));

    const r = await gGet(`/api/friendlog?type=${t}&name=${q}`);
    if (!task.current()) return;

    document.getElementById('friendlog').innerHTML = (r.events||[]).map(e=>{

      let player;

      if (e.event==='name')

        player = `${esc(e.previous||'?')} → <span class="name">${esc(e.display_name)}</span>`;

      else if (e.event==='trust')

        player = `<span class="name" style="cursor:pointer" onclick="openFriend('${esc(e.friend_id)}','${e._src||''}')">${esc(e.display_name)}</span> <span class="dim">${esc(e.status_description||'')}</span>`;

      else

        player = `<span class="name" style="cursor:pointer" onclick="openFriend('${esc(e.friend_id)}','${e._src||''}')">${esc(e.display_name)}</span>`;

      return `<tr><td class="dim">${fmtTs(e.ts)}</td>`+

        `<td><span class="chip" style="color:${FL_COLOR[e.event]||'inherit'};border-color:${FL_COLOR[e.event]||'inherit'}">${esc(FL_LABEL[e.event]||e.event)}</span></td>`+

        `<td>${player}</td>`+

        `<td><button class="ghost mini" onclick="deleteLogRow(${e.id})"></button></td></tr>`;

    }).join('') || '<tr><td colspan="4" class="dim">暂无记录（新的好友/等级变动/昵称变动会自动记录）</td></tr>';

  }catch(e){ reportError(e); }

}

async function deleteLogRow(id){

  await gPost('/api/log-delete', {id});

  loadFriendLog();

}

const FLAG = {zho:'',yue:'',eng:'',jpn:'',kor:'',vie:'',fra:'',

  deu:'',rus:'',spa:'',tha:'',por:'',ita:''};

async function loadFriendTable(){
  const task = APP.tasks.begin('loadFriendTable');

  try{

    const r = await gGet('/api/friends');
    if (!task.current()) return;

    window._FLTB = r.friends || [];

    renderFriendTable();

  }catch(e){ reportError(e); }

}

function renderFriendTable(){

  const all = window._FLTB || [];

  const q = (v('fltSearch')||'').toLowerCase();

  const list = all.filter(f=>!q || (f.name||'').toLowerCase().includes(q));

  document.getElementById('fltBody').innerHTML = list.map((f,i)=>{

    const langs = (f.languages||[]).map(l=>FLAG[l]||'').join(' ');

    return `<tr>`+

      `<td class="dim">${list.length - i}</td>`+

      `<td>${f.thumb?`<img ${mediaAttrs(f.thumb)} style="width:30px;height:30px;border-radius:50%;object-fit:cover">`:''}</td>`+

      `<td><span class="name" style="cursor:pointer" onclick="openFriend('${esc(f.id)}','${f._src||''}')">${esc(f.name)}</span></td>`+

      `<td><span style="color:${f.trust.color||'inherit'}">${esc(f.trust.name||'—')}</span></td>`+

      `<td>${f.online?`<span class="dot" style="background:${statusDotC(f.status)}"></span>${esc(f.desc||'')}`:''}</td>`+

      `<td>${langs}</td>`+

      `<td class="dim">—</td><td class="dim">—</td><td class="dim">—</td>`+

      `<td>${f.online?fmtDur((Date.now()/1000|0)-f.online_since):'—'}</td>`+

      `<td class="dim">${f.last_activity?fmtLast(f.last_activity):(f.online?fmtTs(Date.now()/1000|0):'—')}</td>`+

      `<td class="dim">${f.last_login?fmtLast(f.last_login):'—'}</td>`+

      `<td class="dim">—</td>`+

      `<td><button class="ghost mini" style="color:var(--red)" aria-label="删除好友" data-friend-id="${esc(f.id)}" data-friend-name="${esc(f.name)}" onclick="deleteFriend(this.dataset.friendId,this.dataset.friendName)">删除</button></td>`+

      `</tr>`;

  }).join('') || '<tr><td colspan="13" class="dim">没有好友</td></tr>';

}

async function deleteFriend(id, name){

  if (!confirm(`确认删除好友 ${name}？此操作会同步到 VRChat。`)) return;

  const r = await gPost('/api/friend-delete', {id});

  if (r.ok){ loadFriendTable(); loadFriends(); loadRPanel(); }

  else alert('删除失败: ' + (r.error||''));

}

async function loadModerations(){
  const task = APP.tasks.begin('loadModerations');

  try{

    const r = await gGet('/api/moderations');
    if (!task.current()) return;

    document.getElementById('moderations').innerHTML = (r.items||[]).map(m=>{

      const isBlock = m.type === 'block';

      return `<div class="fitem"><span class="ftime">${fmtLast(m.created)}</span>`+

        `<span>${isBlock?' 屏蔽':' 静音'}</span>`+

        `<span class="name" onclick="openFriend('${esc(m.user_id)}')" style="cursor:pointer">${esc(m.user)}</span>`+

        `<span style="margin-left:auto"><button class="ghost mini" onclick="moderate('${esc(m.user_id)}','${isBlock?'unblock':'unmute'}')">解除</button></span></div>`;

    }).join('') || `<div class="dim">${r.error? ' '+esc(r.error) : '没有屏蔽或静音任何用户'}</div>`;

  }catch(e){ reportError(e); }

}

const MOD_NAME = {block:'屏蔽', unblock:'解除屏蔽', mute:'静音', unmute:'解除静音'};

async function moderate(id, type, feedback){

  const r = await gPost('/api/moderate', {id, type});

  if (!r.ok){ alert((MOD_NAME[type]||type)+'失败: '+(r.error||'')); return; }

  if (feedback){ // 详情页内联反馈

    const btn = event.target; const old = btn.textContent;

    btn.textContent = ' ' + feedback;

    setTimeout(()=>btn.textContent=old, 2200);

  } else loadModerations();

}

/* ---------- 工具 ---------- */

async function toolWorld(){

  let q = v('toolWorld');

  const m = q.match(/wrld_[0-9a-f-]+/i);

  if (!m){ alert('没有识别到 wrld_ id'); return; }

  openWorld(m[0]);

}

async function toolInstance(){

  const loc = v('toolInst');

  openInstance(loc);

}

async function toolRandom(){

  document.getElementById('toolRandomOut').innerHTML = '<div class="dim">抽签中…</div>';

  const r = await gGet('/api/random-world');

  document.getElementById('toolRandomOut').innerHTML = r.world ? worldRow(r.world)

    : `<div class="msg">${esc(r.error||'失败')}</div>`;

}

/* ---------- 设置 ---------- */

function settingsBusy(busy,loading=busy){
  document.querySelectorAll('#page-settings input,#page-settings select,#page-push input,#page-push select').forEach(el=>el.disabled=busy);
  document.querySelectorAll('[data-settings-write]').forEach(el=>el.disabled=busy);
  document.querySelectorAll('#page-settings .sw,#page-push .sw').forEach(el=>{el.style.pointerEvents=busy?'none':'';el.style.opacity=busy?'0.5':'';el.setAttribute('aria-disabled',String(busy));});
  for(const id of ['page-settings','page-push'])document.getElementById(id)?.setAttribute('aria-busy',String(loading));
}
function settingsLoadState(message,retry=false){
  for(const prefix of ['settings','push']){
    const state=document.getElementById(prefix+'LoadStatus'),button=document.getElementById(prefix+'LoadRetry');
    if(state)state.textContent=message;
    button?.classList.toggle('hidden',!retry);
  }
}
async function loadSettings(force=false){
  const task = APP.tasks.begin('loadSettings');
  CFG=null;settingsBusy(true);
  settingsLoadState('正在加载当前账号设置…');
  try{
  let config;
  for(let attempt=0;attempt<2;attempt++){
    try{config=await gGet('/api/config',{force:force||attempt>0});break;}
    catch(error){
      if(!task.current())return;
      // A just-completed write (for example marking a notification read)
      // invalidates earlier reads even when we are still on this page.
      if(!VRCXRuntime.ignored(error)||attempt===1)throw error;
    }
  }
  if (!task.current()) return;
  CFG={...config,telegram:config.telegram||{},bark:config.bark||{}};

  const set = (id, val) =>document.getElementById(id).value = val??'';

  const sw = (id, on) =>{

    const el = document.getElementById(id);

    el.classList.toggle('on', !!on);

    el.dataset.v = on ? '1' : '0';

  };

  sw('sw-notify_online', CFG.notify_online);

  sw('sw-notify_offline', CFG.notify_offline);

  sw('sw-notify_active_offline', CFG.notify_active_offline !== false);  // 键缺省=开（与监控端默认一致）

  sw('sw-notify_world_change', CFG.notify_world_change);

  sw('sw-notify_active', CFG.notify_active);

  sw('sw-notify_status', CFG.notify_status);

  sw('sw-notify_desc', CFG.notify_desc);

  sw('sw-notify_avatar', CFG.notify_avatar);

  sw('sw-watch_favorites', CFG.watch_favorites);

  sw('sw-tg', CFG.telegram.enabled);

  sw('sw-bark_enabled', CFG.bark.enabled);

  set('set-level', CFG.bark.level);

  set('set-group', CFG.bark.group);

  set('set-sound', CFG.bark.sound);

  set('set-critical_volume', CFG.bark.critical_volume);

  set('set-favorites_sync_seconds', CFG.favorites_sync_seconds);

  set('set-poll_seconds', CFG.poll_seconds);

  set('set-tgtoken', CFG.telegram.bot_token_masked);

  set('set-tgchat', CFG.telegram.chat_id);

  document.getElementById('set-barkkey').textContent = CFG.bark.key_masked || '未配置（SSH 修改 config.json 填入）';

  document.getElementById('set-pwstate').textContent = CFG.has_web_password ? '已配置账号服务口令；不代表网关状态' : '未配置账号服务口令；网关状态需由部署者确认';
  settingsBusy(false);
  settingsLoadState('当前账号：'+GA_NAMES[GA]+'。配置改动保存到此账号。');
  if(CURPAGE==='settings')loadBackups();
  }catch(error){
    if(!task.current())return;
    CFG=null;
    settingsBusy(true,false);
    settingsLoadState('设置加载失败：'+(error.message||'无法连接服务器')+'。可重试或返回上一页。',true);
  }
}

function swToggle(el, key){
  if(!CFG) return;

  const val = el.dataset.v !== '1';

  el.classList.toggle('on', val);

  el.dataset.v = val ? '1' : '0';

  saveSetting(key, val);

}

function saveSettings(){
  if(!CFG) return;
  clearTimeout(SAVE_T);
  const account=GA, task=APP.tasks.begin('settings-save');
  const body={
    'bark.level':v('set-level'), 'bark.group':v('set-group'), 'bark.sound':v('set-sound'),
    'bark.critical_volume':+v('set-critical_volume')||0,
    favorites_sync_seconds:+v('set-favorites_sync_seconds')||90,
    poll_seconds:+v('set-poll_seconds')||30, 'telegram.chat_id':v('set-tgchat')
  };
  const token=v('set-tgtoken');
  if(token && !token.endsWith('****')) body['telegram.bot_token']=token;
  SAVE_T=setTimeout(async()=>{
    SAVE_T=null;
    if(!task.current()) return;
    try{
      const r=await gPost('/api/config-set',body,{account});
      if(task.current()) document.getElementById('settingsMsg').textContent=r.ok?' 已保存':' '+(r.error||'保存失败');
    }catch(e){if(task.current()) reportError(e);}
  },600);
}

async function saveSetting(key,value){
  if(!CFG) return;
  const task=APP.tasks.begin('setting-'+key);
  try{
    const r=await gPost('/api/config-set',{[key]:value});
    if(!task.current()) return;
    document.getElementById('settingsMsg').textContent=r.ok?' 已保存':' '+(r.error||'保存失败');
  }catch(e){if(task.current()) reportError(e);}
}

async function createBackup(){
  const r = await gPost('/api/backup-op', {op:'create'});
  alert(r.ok ? ' 备份完成: ' + r.file : ' '+(r.error||'失败'));
  loadBackups();
}
async function restoreBackup(){
  if(!CFG) return;
  const f = document.getElementById('bkList').value;
  if (!f){ alert('没有可选备份'); return; }
  if (!confirm('确认从 '+f+' 恢复数据库？当前数据将另存为 .pre-restore')) return;
  const r = await gPost('/api/backup-restore', {file: f});
  alert(r.ok ? ' 已恢复（监控服务建议重启）' : ' '+(r.error||'失败'));
}
async function loadBackups(force=false){
  const task=APP.tasks.begin('backup-list');
  const sel=document.getElementById('bkList'),retry=document.getElementById('backupRetry');
  retry?.classList.add('hidden');
  try{
    const r = await gGet('/api/backup',{force});
    if(!task.current())return;
    if (sel) sel.innerHTML = (r.backups||[]).map(b=>`<option>${esc(b)}</option>`).join('') || '<option value="">（无备份）</option>';
  }catch(e){
    if(!task.current())return;
    if(sel)sel.innerHTML='<option value="">备份列表加载失败</option>';
    retry?.classList.remove('hidden');
  }
}

async function downloadExport(kind){
  try{
    const account=GA;
    const r=await gGet('/api/export?format=json&kind='+encodeURIComponent(kind),{account});
    const url=URL.createObjectURL(new Blob([r.content],{type:r.content_type}));
    const a=document.createElement('a');a.href=url;a.download=r.filename;a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){reportError(e);}
}
