/* ---------- 弹窗: 用户 / 世界 / 实例 ---------- */

let UD = null, UTAB = 'info';

const UTABS = [['info','信息'],['mutual','共同好友'],['groups','群组'],

  ['worlds','创建的世界'],['avatars','创建的模型'],['activity','活动记录'],['json','原始 JSON']];

const LANGS = {zho:'中文', yue:'粤语', eng:'英语', jpn:'日语', kor:'韩语', vie:'越南语',

  fra:'法语', deu:'德语', rus:'俄语', spa:'西班牙语', tha:'泰语', por:'葡语', ita:'意语'};

const DETAIL_TRAIL = [];
let DETAIL_CURRENT = null;
function detailAccount(src){
  if(GA!=='m') return GA;
  if(src==='a'||src==='b') return src;
  return DETAIL_CURRENT?.account||'a';
}
function beginDetail(type, id, account=window._CURSRC || GA) {
  if (DETAIL_CURRENT && (DETAIL_CURRENT.type!==type || DETAIL_CURRENT.id!==id)) {
    DETAIL_TRAIL.push({current:DETAIL_CURRENT, html:document.getElementById('mcard').innerHTML,
      scroll:document.getElementById('mcard').scrollTop || 0,
      forms:[...document.getElementById('mcard').querySelectorAll('input,textarea,select')].map(el=>({id:el.id,value:el.value,checked:el.checked})),
      state:{UD,UTAB,WD_DATA,WTAB,AVD,AVTAB,GD,GTAB:typeof GTAB==='undefined'?null:GTAB,CURUSER,src:window._CURSRC}});
    if (DETAIL_TRAIL.length>12) DETAIL_TRAIL.shift();
  }
  APP.tasks.cancel('user-section');APP.tasks.cancel('user-room');APP.tasks.cancel('note-save');APP.tasks.cancel('world-note-save');
  const isNew = !DETAIL_CURRENT || DETAIL_CURRENT.type!==type || DETAIL_CURRENT.id!==id;
  DETAIL_CURRENT = {type,id,account};
  window._CURSRC=account;
  closeQS(); mbSheetsClose();
  document.getElementById('modal').classList.remove('hidden');
  document.getElementById('mcard').classList.add('wide');
  document.getElementById('mcard').scrollTop=0;
  document.body?.classList.add('detail-open');
  if(isNew) window.MobileUI?.detailOpened();
  return APP.tasks.begin('modal');
}
function detailBack(fromHistory=false) {
  if(!fromHistory && window.MobileUI?.isMobile() && MobileUI.depth){ MobileUI.detailBack(); return; }
  const frame = DETAIL_TRAIL.pop();
  if (!frame) { closeModal(fromHistory); return; }
  APP.tasks.cancel('modal');
  DETAIL_CURRENT=frame.current;
  ({UD,UTAB,WD_DATA,WTAB,AVD,AVTAB,GD,CURUSER}=frame.state);
  window._CURSRC=frame.state.src;
  if(frame.state.GTAB!=null && typeof GTAB!=='undefined') GTAB=frame.state.GTAB;
  const card=document.getElementById('mcard'); card.innerHTML=frame.html;card.scrollTop=frame.scroll;
  card.querySelectorAll('button[data-saving]').forEach(button=>{button.disabled=false;delete button.dataset.saving;});
  for(const field of frame.forms||[]){const el=document.getElementById(field.id);if(el){el.value=field.value;el.checked=field.checked;}}
  // The old resources were cancelled when entering the child. Resume only the
  // restored view's partition, without adding another history entry.
  if(DETAIL_CURRENT.type==='friend'){
    const task=APP.tasks.begin('modal');loadUserRoom(task);
    if(!UD.profile_loaded||UD.stale) refreshFriendProfile(CURUSER,DETAIL_CURRENT.account,task);
    else loadUserSection(UTAB);
  }
  if(DETAIL_CURRENT.type==='group'&&GTAB==='members') setGDTab(GTAB);
}
function detailHead(label) {
  return `<div class="head detail-head"><button class="ghost detail-back" onclick="detailBack()" aria-label="返回">‹ 返回</button><strong>${esc(label)}</strong><button class="ghost" onclick="closeModal()" aria-label="关闭详情">关闭</button></div>`;
}
function detailLater(task, fn, ms=1500) { setTimeout(()=>{if(task.current()) fn();},ms); }
function friendSeed(id, account) {
  const hit=APP.client.peek('/api/friend?id='+encodeURIComponent(id),account);
  if(hit?.user) return hit;
  const row=[...(window._FRIENDS||[]),...(window._LOCF||[])].find(f=>f.id===id);
  const f=row?._accounts?.[account] || row || {};
  return {user:{id,displayName:f.name||id,trust:f.trust||{},languages:[],bioLinks:[],
    state:f.state||'unknown',cur_state:f.state||'unknown',location:f.location||'',world:f.world||'',
    world_id:f.world_id||(f.location||'').split(':')[0],instance_label:f.instance_label||'',
    currentAvatarThumbnailImageUrl:f.thumb||'',status:f.status||'',statusDescription:f.desc||'',
    isFriend:!!row,online_since:f.online_since},events:[],groups:[],heat:[],mutual:{friends:[],counts:{}},
    stale:true,loaded_sections:[],profile_loaded:false};
}
async function openFriend(id, src){
  const row=(window._FRIENDS||[]).find(f=>f.id===id);
  const selected=GA==='m' ? (src==='a'||src==='b'?src:row?._detailSource||'a') : GA;
  const task=beginDetail('friend',id,selected); CURUSER=id;
  UD=friendSeed(id,selected); UTAB='info';renderUserShell();
  loadUserRoom(task); // Independent of the biography/groups/notes request.
  await refreshFriendProfile(id,selected,task);
}
async function refreshFriendProfile(id,selected,task){
  let tries=0;
  const update=async()=>{
    try {
      const result=await gGet('/api/friend?id='+encodeURIComponent(id),{account:selected,force:true});
      if(!task.current()) return;
      UD=result;
      // Background responses do not replace a form while it is being edited.
      if(!document.getElementById('mcard').contains?.(document.activeElement) || !['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) renderUserShell();
      loadUserRoom(task);
      if(result.stale && tries++<12) detailLater(task,update);
      else if(result.profile_loaded) loadUserSection(UTAB);
    }catch(e){
      if(!task.current()||VRCXRuntime.ignored(e)) return;
      const card=document.getElementById('utabBody');
      if(card) card.insertAdjacentHTML?.('beforeend',`<div class="msg">${esc(e.message)} <button class="ghost" onclick="openFriend('${esc(id)}','${selected}')">重试</button></div>`);
    }
  };
  await update();
}
async function loadUserSection(tab){
  if(!UD?.profile_loaded || !['info','groups','worlds','avatars','mutual'].includes(tab)) return;
  if(UD.loaded_sections?.includes(tab)&&Date.now()/1000-(UD.section_times?.[tab]||0)<300) return;
  const id=CURUSER, account=window._CURSRC, task=APP.tasks.begin('user-section');
  const box=document.getElementById('utabBody');
  if(tab!=='info' && box) box.innerHTML='<div class="detail-loading" role="status">加载中…</div>';
  try{
    const r=await gGet('/api/friend-section?id='+encodeURIComponent(id)+'&part='+tab,{account,force:true});
    if(!task.current()||CURUSER!==id||UTAB!==tab) return;
    UD=r;UD.loaded_sections=[...new Set([...(r.loaded_sections||[]),tab])];
    const card=document.getElementById('mcard');
    const editing=card.contains?.(document.activeElement)&&['INPUT','TEXTAREA'].includes(document.activeElement?.tagName);
    if(!editing) renderUserShell();
    loadUserRoom(APP.tasks.begin('user-room'));
  }catch(e){
    if(!task.current()||VRCXRuntime.ignored(e)) return;
    if(box) box.insertAdjacentHTML?.('beforeend',`<div class="msg">${esc(e.message)} <button class="ghost" onclick="loadUserSection('${tab}')">重试</button></div>`);
  }
}
function userRoomHTML(world, instance){
  const u=UD.user, current=u.cur_state==='online'||u.state==='online';
  const last=UD.last_room||{},loc=current?u.location:last.location;
  const wid=(loc||'').split(':')[0];
  const name=world?.world?.name || (current?u.world:last.world) || VRCXFeed.locationText({location:loc});
  const thumb=world?.world?.thumb || (current?u.world_thumb:'');
  const count=instance?.stale?null:instance?.live?.user_count;
  const owner=roomFacts(loc||'',instance?.live||{},window._CURSRC);
  return `<div class="room-preview"><div class="room-photo">${thumb?`<img ${mediaAttrs(thumb,window._CURSRC,'high')} alt="${esc(name)}">`:`<span>${wid.startsWith('wrld_')?'世界图片加载中…':esc(VRCXFeed.locationText({location:loc}))}</span>`}</div>
    <div class="room-copy"><span class="eyebrow">${current?'当前房间':'最后记录位置'}</span><strong>${esc(name)}</strong>
    <div class="room-meta">${loc?.includes(':')?`<span class="chip">${esc(owner.label)}</span>`:''}${count!=null?`<span class="chip">${count}${instance.live.capacity!=null?' / '+instance.live.capacity:''} 人</span>`:''}</div>
    ${owner.id?`<div class="dim">房间建立者：${esc(owner.name)}</div>`:''}
    ${!current&&last.ts?`<time>${fmtTs(last.ts)}</time>`:''}
    ${wid.startsWith('wrld_')?`<div class="row"><button class="ghost" onclick="openWorld('${esc(wid)}','${window._CURSRC}')">世界详情</button>${loc.includes(':')?`<button onclick="${esc(`openInstance(${JSON.stringify(loc)},${JSON.stringify(window._CURSRC)})`)}">房间详情</button>`:''}</div>`:''}</div></div>`;
}
async function loadUserRoom(task){
  if(!UD?.user||UTAB!=='info') return;
  const u=UD.user,loc=(u.cur_state==='online'||u.state==='online')?u.location:UD.last_room?.location;
  const wid=(loc||'').split(':')[0];
  const target=document.getElementById('userRoom');
  if(!target||!wid.startsWith('wrld_')) return;
  const account=window._CURSRC, id=CURUSER;
  let world=APP.client.peek('/api/world?id='+encodeURIComponent(wid),account),instance=null;
  const current=()=>task.current()&&CURUSER===id&&UTAB==='info'&&target.isConnected;
  const draw=()=>{
    if(!current()) return;
    const photos=IMAGES.capture(target,true);
    target.innerHTML=userRoomHTML(world,instance);
    IMAGES.restore(target,photos);
  };
  draw();
  let tries=0;
  const refresh=async()=>{
    const jobs=[gGet('/api/world?id='+encodeURIComponent(wid),{account,force:true}).then(value=>{
      if(current()){world=value;draw();}
    })];
    if(loc.includes(':')) jobs.push(gGet('/api/instance?location='+encodeURIComponent(loc),{account,force:true}).then(value=>{
      if(current()){instance=value;draw();}
    }));
    await Promise.allSettled(jobs);
    if(!current()) return;
    if((world?.stale||instance?.stale)&&tries++<10) detailLater(task,refresh,2000);
  };
  await refresh();
}

function detailPhotoError(image){
  if(image.isConnected===false) return;
  let chain;
  try { chain=JSON.parse(image.dataset.photos||'[]'); } catch { chain=[]; }
  const next=Number(image.dataset.photoIndex||0)+1;
  image.dataset.photoIndex=String(next);
  if(chain[next]) IMAGES.setURL(image,chain[next],image.dataset.mediaAccount||window._CURSRC);
  else image.style.display='none';
}
function renderUserShell(){

  const c = document.getElementById('mcard');

  const decodedPhotos=IMAGES.capture(c);

  const u = UD.user;

  const imgChain = [u.currentAvatarThumbnailImageUrl, u.currentAvatarImageUrl,

                    u.userIcon, u.profilePicOverride, u._avatar_fallback].filter(Boolean);

  const color = u.trust && u.trust.color ? u.trust.color : 'inherit';

  const langs = (u.languages||[]).map(l=>LANGS[l]||l);

  c.innerHTML = `

    <div class="head detail-head"><button class="ghost" onclick="detailBack()">‹ 返回</button><div style="font-weight:600;font-size:16px">用户详情${window._CURSRC==='b'?' <span class="badge badge-active" title="数据来自账号B的好友列表">B 号</span>':window._CURSRC==='a'?' <span class="badge badge-online" title="数据来自账号A的好友列表">A 号</span>':window._CURSRC==='ab'?' <span class="badge badge-status" title="两个号的好友列表里都有">双号</span>':''}${UD.stale?' <span class="dim" style="font-size:11px;font-weight:400">· 本地缓存，后台更新中…</span>':''}</div>

      <button class="ghost" onclick="closeModal()">关闭</button></div>

    <div class="ugrid">

      <div class="ucard">

        <div class="ubanner" style="background:${esc(u.bannerColor||'var(--hov)')}"></div>

        ${imgChain.length?`<img class="uavatar" ${mediaAttrs(imgChain[0],window._CURSRC)} referrerpolicy="no-referrer"
          data-photos="${esc(JSON.stringify([...new Set(imgChain)]))}" data-photo-index="0">`:''}

        <div class="uname" style="color:${color}">${esc(u.displayName)}</div>

        <div class="dim" style="font-size:12px">${esc(u.username||'')}${u.isFriend?' · 好友':' · 非好友'}</div>

        <div style="margin:6px 0">${stateDot(u.cur_state)}${esc(ST[u.status]||u.status||'—')}</div>

        ${u.statusDescription?`<div class="dim" style="font-size:12px;word-break:break-all">${esc(u.statusDescription)}</div>`:''}

        <div style="margin-top:8px">${trustChip(u.trust)}</div>

        ${langs.length?`<div style="margin-top:6px">${langs.map(l=>`<span class="chip">${esc(l)}</span>`).join('')}</div>`:''}

        ${u.pronouns?`<div class="dim" style="font-size:12px;margin-top:6px">${esc(u.pronouns)}</div>`:''}

        <div class="row" style="justify-content:center;margin-top:10px;flex-wrap:wrap">

          ${u.is_blocked

            ? `<span class="chip" style="color:var(--red);border-color:var(--red)">已屏蔽</span>

               <button class="ghost mini" ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} onclick="moderate('${esc(u.id)}','unblock','已解除屏蔽')">解除屏蔽</button>`

            : `<button class="ghost mini" ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} onclick="moderate('${esc(u.id)}','block','已屏蔽')">屏蔽</button>`}

          ${u.is_muted

            ? `<span class="chip" style="color:var(--yellow);border-color:var(--yellow)">已静音</span>

               <button class="ghost mini" ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} onclick="moderate('${esc(u.id)}','unmute','已解除静音')">解除静音</button>`

            : `<button class="ghost mini" ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} onclick="moderate('${esc(u.id)}','mute','已静音')">静音</button>`}

        </div>

        ${u.isFriend?`<div class="row" style="justify-content:center;margin-top:6px">

          <button class="ghost mini" ${GA==='m'?'disabled':''} onclick="notifAct('invite','x',{userId:'${esc(u.id)}'})">发送邀请</button>

          <button class="ghost mini" ${GA==='m'?'disabled':''} onclick="notifAct('request_invite','x',{userId:'${esc(u.id)}'})">申请加入</button>

        </div>`:''}

        ${u.currentAvatarThumbnailImageUrl||u.currentAvatarImageUrl||u._avatar_fallback?`<div class="card" style="margin:10px 0 0;text-align:left"><div class="dim" style="font-size:12px;margin-bottom:4px">正在使用的模型</div>

          <div class="row"><img ${mediaAttrs(u.currentAvatarThumbnailImageUrl||u.currentAvatarImageUrl||u._avatar_fallback,window._CURSRC)} style="width:42px;height:42px;border-radius:8px;object-fit:cover">

          <div class="name" style="font-size:13px">${esc(u.avatar_name||'—')}</div></div></div>`:''}

        ${u.representing?`<div class="card" style="margin:10px 0 0;text-align:left"><div class="dim" style="font-size:12px;margin-bottom:4px">展示群组</div>

          <div class="row">${u.representing.icon?`<img ${mediaAttrs(u.representing.icon,window._CURSRC)} style="width:32px;height:32px;border-radius:50%;object-fit:cover">`:''}

          <div class="name" style="font-size:13px">${esc(u.representing.name)}</div></div></div>`:''}

      </div>

      <div>

        <div class="tabs" id="utabs">${UTABS.map(([k,l])=>

          `<button class="tabbtn ${k===UTAB?'active':''}" data-t="${k}" onclick="setUTab('${k}')">${l}</button>`).join('')}</div>

        <div id="utabBody"></div>

      </div>

    </div>`;

  IMAGES.restore(c,decodedPhotos);
  renderUTab();

}

function setUTab(t){

  UTAB = t;

  document.querySelectorAll('#utabs .tabbtn').forEach(b=>b.classList.toggle('active', b.dataset.t===t));

  renderUTab();
  loadUserSection(t);
  if(t==='info') loadUserRoom(APP.tasks.begin('user-room'));

}

function miniHeat(heat){

  const map = {}; let hmax = 0;

  (heat||[]).forEach(([d,h,c])=>{ map[d+'-'+h]=c; hmax=Math.max(hmax,c); });

  let html = '<div class="heat">';

  for (const d of [1,2,3,4,5,6,0]){

    html += `<div class="lab">${WD[d]}</div>`;

    for (let h=0; h<24; h++){

      const c2 = map[d+'-'+h]||0;

      const a = c2 ? (0.3+0.7*c2/hmax) : 0;

      html += `<div class="cell" style="${c2?`background:rgba(139,92,246,${a.toFixed(2)})`:''}" title="${WD[d]} ${h}点 · ${c2}次"></div>`;

    }

  }

  return html + '</div>';

}

function renderUTab(){

  const u = UD.user;

  const box = document.getElementById('utabBody');

  const links = (u.bioLinks||[]).filter(l=>/^https?:\/\//i.test(l)).map(l=>

    `<a class="mlink" href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`).join('');

  if (UTAB==='info'){

    const room = `<div id="userRoom">${userRoomHTML(null,null)}</div>`;
    box.innerHTML = room +

      (u.bio||links?`<div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">个人简介</div><div class="bio">${esc(u.bio||'')}</div>${links?`<div style="margin-top:6px">${links}</div>`:''}</div>`:'') +

      (u.isFriend?`<div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">备注（同步到 VRChat）</div>

        <div class="row"><textarea ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} id="noteText" oninput="DETAIL_CURRENT.noteDraft=this.value" rows="2" style="flex:1">${esc(DETAIL_CURRENT?.noteDraft??u.note??'')}</textarea>

        <button class="ghost" ${!UD.loaded_sections?.includes('info')||GA==='m'?'disabled':''} onclick="saveNote(this)">保存</button></div></div>`:'') +

      `<div class="card" style="margin:0"><div class="kv">

        <span class="k">本次在线</span><span>${u.online_since?fmtDur((Date.now()/1000|0)-u.online_since):'—'}</span>

        <span class="k">上次登录</span><span>${fmtLast(u.last_login)}</span>

        <span class="k">最后活动</span><span>${fmtLast(u.last_activity)}</span>

        <span class="k">注册时间</span><span>${fmtLast(u.date_joined)}</span>

        <span class="k">允许克隆模型</span><span>${u.allowAvatarCopying?'是':'否'}</span>

        <span class="k">平台</span><span>${esc(PF[u.last_platform]||u.last_platform||'—')}</span>

        <span class="k">ID</span><span class="dim" style="word-break:break-all">${esc(u.id)}</span>

      </div></div>`;

  } else if (UTAB==='mutual'){

    const mc = (UD.mutual||{}).counts || {};

    const mf = (UD.mutual||{}).friends || [];

    const head = `<div class="dim" style="font-size:13px;margin-bottom:6px">共同好友 ${mc.friends!=null?mc.friends:mf.length} 个 · 共同群组 ${mc.groups!=null?mc.groups:0} 个</div>`;

    box.innerHTML = head + (mf.map(f=>

      `<div class="srow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">${f.thumb?`<img ${mediaAttrs(f.thumb,window._CURSRC)}>`:'<img>'}`+

      `<div><div class="name">${esc(f.name)}</div></div>`+

      `<span class="dot ${f.state==='online'?'on':f.state==='active'?'act':''}" style="margin-left:auto"></span></div>`).join('')

      || '<div class="dim">没有共同好友</div>');

  } else if (UTAB==='groups'){

    box.innerHTML = (UD.groups||[]).map(g=>

      `<div class="srow" onclick="openGroup('${esc(g.id)}')">${g.icon?`<img ${mediaAttrs(g.icon,window._CURSRC)}>`:'<img>'}`+

      `<div><div class="name">${esc(g.name)}</div>`+

      `<div class="dim" style="font-size:12px">${g.members!=null?g.members.toLocaleString()+' 名成员':''}</div></div></div>`).join('')

      || '<div class="dim">没有加入任何群组</div>';

  } else if (UTAB==='worlds'){

    const cards = (UD.worlds_created||[]).map(w=>

      `<div class="loccard" onclick="openWorld('${esc(w.id)}')">${w.thumb?`<img class="wthumb-s" ${mediaAttrs(w.thumb,window._CURSRC)}>`:''}`+

      `<div class="name" style="font-size:13px">${esc(w.name)}</div>`+

      `<div class="dim" style="font-size:11px">${w.visits!=null?w.visits.toLocaleString()+' 次访问':''}</div></div>`).join('');

    box.innerHTML = cards ? `<div class="locgrid">${cards}</div>` : '<div class="dim">没有创建的世界（或未公开）</div>';

  } else if (UTAB==='avatars'){

    const cards = (UD.avatars_created||[]).map(a=>

      `<div class="loccard">${a.image?`<img class="wthumb-s" ${mediaAttrs(a.image,window._CURSRC)}>`:''}`+

      `<div class="name" style="font-size:13px">${esc(a.name)}</div></div>`).join('');

    box.innerHTML = cards ? `<div class="locgrid">${cards}</div>`

      : '<div class="dim">无法查看（VRChat 不允许查看他人的模型列表）</div>';

  } else if (UTAB==='activity'){

    box.innerHTML = `

      <div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">近 30 天本地记录：上线 ${UD.logins30||0} 次 · 在线约 ${fmtHours(UD.hours30||0)}</div>

        ${miniHeat(UD.heat)}</div>

      <div class="dim" style="font-size:13px;margin-bottom:4px">近期动态</div>

      ${(UD.events||[]).map(e=>`<div class="fitem"><span class="ftime">${fmtTs(e.ts)}</span><span>${esc(WEB_OFFLINE_LABEL(e))} · ${feedDetailCell(e)}</span></div>`).join('') || '<div class="dim">暂无本地记录</div>'}`;

  } else {

    box.innerHTML = `<pre class="jsonbox">${esc(JSON.stringify(UD.raw, null, 2))}</pre>`;

  }

}

let AVD = null, AVTAB = 'info';

async function openAvatarDlg(id){
  const account=detailAccount();
  const task = beginDetail('avatar',id,account);

  const m = document.getElementById('modal'), c = document.getElementById('mcard');

  m.classList.remove('hidden');

  c.classList.add('wide');

  const lst = ((window._AVD||{}).own||[]).concat((window._AVD||{}).favorites||[]);

  const pre = lst.find(a=>a.id===id);

  c.innerHTML = pre ?

    `<div class="rrow" style="pointer-events:none">${pre.thumb||pre.image?`<img ${mediaAttrs(pre.thumb||pre.image,window._CURSRC)}>`:'<img>'}`+

    `<div><div class="rn">${esc(pre.name)}</div><div class="rl">by ${esc(pre.author||'?')}</div></div></div>`+

    `<div class="dim" id="mload" style="margin-top:8px">详情加载中…</div>`

    : '<div class="dim" id="mload">加载中…</div>';

  c.innerHTML = detailHead('模型详情')+c.innerHTML;
  const r = await gGet('/api/avatar?id='+encodeURIComponent(id),{account});
  if (!task.current()) return;

  if (r.error){

    const le = document.getElementById('mload');

    const msg = `<div class="msg">${esc(r.error)}</div>`;

    if (le) le.outerHTML = msg; else c.innerHTML = msg;

    return;

  }

  AVD = r; AVTAB = 'info';

  renderAvatarDlg();

}

function renderAvatarDlg(){

  const c = document.getElementById('mcard');

  const a = AVD.avatar;

  const rel = a.release==='public' ? ['公开','#3ddc84'] : ['私人','#f5a623'];

  c.innerHTML = `

    ${detailHead('模型详情')}

    <div class="ugrid">

      <div>

        ${a.image?`<img ${mediaAttrs(a.image,window._CURSRC)} style="width:100%;border-radius:10px;object-fit:cover">`:''}

        <div class="name" style="font-size:17px;margin:8px 0 2px">${esc(a.name)}</div>

        <div class="dim" style="font-size:12.5px">${esc(a.author||'')}</div>

        <div class="row" style="margin:8px 0">

          <span class="chip" style="color:${rel[1]};border-color:${rel[1]}">${rel[0]}</span>

          ${a.version?`<span class="chip">模型替身 v${esc(a.version)}</span>`:''}

          ${a.platform?`<span class="chip">${esc(a.platform)}</span>`:''}

        </div>

        <button style="width:100%;margin-top:4px" onclick="selectAvatar('${esc(a.id)}')">使用此模型</button>

        <div class="card" style="margin:10px 0 0"><div class="dim" style="font-size:12px;margin-bottom:4px">信息</div>

          <div class="kv">

            <span class="k">创建时间</span><span>${fmtLast(a.created)}</span>

            <span class="k">最后更新时间</span><span>${fmtLast(a.updated)}</span>

            <span class="k">版本</span><span>${a.version??'—'}</span>

            <span class="k">支持的平台</span><span>${esc(a.platform||'—')}</span>

          </div></div>

        <div class="card" style="margin:10px 0 0"><div class="dim" style="font-size:12px;margin-bottom:4px">VRCX 信息（本地统计）</div>

          <div class="kv"><span class="k">使用时长</span><span>—</span></div></div>

      </div>

      <div>

        <div class="tabs" id="avdtabs">

          <button class="tabbtn active" data-t="info" onclick="setAVTab('info')">信息</button>

          <button class="tabbtn" data-t="json" onclick="setAVTab('json')">原始 JSON 信息</button>

        </div>

        <div id="avdBody"></div>

      </div>

    </div>`;

  renderAVTab();

}

function setAVTab(t){

  AVTAB = t;

  document.querySelectorAll('#avdtabs .tabbtn').forEach(b=>b.classList.toggle('active', b.dataset.t===t));

  renderAVTab();

}

function renderAVTab(){

  const box = document.getElementById('avdBody');

  if (AVTAB==='info'){

    box.innerHTML = `

      <div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">模型相册</div>

        <div class="dim" style="text-align:center;padding:30px 0">相册为游戏本地数据，网页版暂无</div></div>

      <div class="card" style="margin:0"><div class="dim" style="font-size:12px;margin-bottom:4px">描述</div>

        <div class="bio">${esc(AVD.avatar.description||'—')}</div></div>`;

  } else {

    box.innerHTML = `<pre class="jsonbox">${esc(JSON.stringify(AVD.avatar.raw, null, 2))}</pre>`;

  }

}

async function saveNote(button){
  if(!CURUSER||GA==='m'||!UD?.loaded_sections?.includes('info')) return;
  const id=CURUSER,account=window._CURSRC,task=APP.tasks.begin('note-save');
  const value=document.getElementById('noteText').value;
  if(button){button.disabled=true;button.dataset.saving='true';}
  try {
    const result=await gPost('/api/friend-note',{id,note:value},{account});
    if(!task.current()||CURUSER!==id) return;
    if(!result.ok) throw new Error(result.error||'保存失败');
    UD.user.note=value;
    if(DETAIL_CURRENT?.noteDraft===value) delete DETAIL_CURRENT.noteDraft;
    if(button) button.textContent='已保存';
  }catch(e){if(task.current()&&!VRCXRuntime.ignored(e)) reportError(e);}
  finally{if(task.current()&&button?.isConnected){button.disabled=false;delete button.dataset.saving;}}
}

let WD_DATA = null, WTAB = 'rooms';

const INST_DOT = {'公开':'#3ddc84','好友+':'#ff5f56','仅限好友':'#ff5f56',

  '邀请+':'#f5a623','仅限邀请':'#f5a623','群组+':'#8b5cf6','群组':'#8b5cf6'};

async function openWorld(wid,src){
  if(!wid||!wid.startsWith('wrld_')) return;
  const account=detailAccount(src);
  const task=beginDetail('world',wid,account);
  WD_DATA=APP.client.peek('/api/world?id='+encodeURIComponent(wid),account) || {
    world:{id:wid,name:(window._FRIENDS||[]).find(f=>f.world_id===wid)?.world||wid},instances:[],stale:true};
  WTAB='rooms';renderWorldShell();
  let tries=0;
  const update=async()=>{
    try{
      const r=await gGet('/api/world?id='+encodeURIComponent(wid),{account,force:true});
      if(!task.current()) return;
      WD_DATA=r;
      if(document.activeElement?.id!=='wnoteText') renderWorldShell();
      if(r.stale&&tries++<10) detailLater(task,update,2000);
    }catch(e){if(task.current()&&!VRCXRuntime.ignored(e)) reportError(e);}
  };
  await update();
}

function setWTab(t){

  WTAB = t;

  document.querySelectorAll('#wtabs .tabbtn').forEach(b=>b.classList.toggle('active', b.dataset.t===t));

  renderWTab();

}

async function saveWorldNote(button){
  if(!WD_DATA?.world?.id||GA==='m') return;
  const id=WD_DATA.world.id,account=window._CURSRC,task=APP.tasks.begin('world-note-save');
  const note=document.getElementById('wnoteText').value;
  if(button){button.disabled=true;button.dataset.saving='true';}
  try{
    const result=await gPost('/api/world-note',{id,note},{account});
    if(!task.current()||WD_DATA?.world?.id!==id) return;
    if(!result.ok) throw new Error(result.error||'保存失败');
    WD_DATA.note=note;
    if(DETAIL_CURRENT?.noteDraft===note) delete DETAIL_CURRENT.noteDraft;
    if(button) button.textContent='已保存';
  }catch(e){if(task.current()&&!VRCXRuntime.ignored(e)) reportError(e);}
  finally{if(task.current()&&button?.isConnected){button.disabled=false;delete button.dataset.saving;}}
}

function renderWorldShell(){

  const c = document.getElementById('mcard');
  const photos = IMAGES.capture(c,true);

  const r = WD_DATA, w = r.world;

  const tags = (w.tags||[]).filter(t=>!t.startsWith('language_') && !t.startsWith('system_')).slice(0,6);

  c.innerHTML = `

${detailHead('世界详情')}

    <div class="ugrid">

      <div>

        ${w.thumb?`<img class="wthumb" ${mediaAttrs(w.thumb,window._CURSRC,'high')}>`:''}

        <div class="name" style="font-size:17px;margin:8px 0 4px">${esc(w.name)}</div>

        <div class="row" style="margin-bottom:8px">

          <span class="chip">${(w.platforms||[]).map(p=>PF[p]||p).join(' / ')||'平台信息未缓存'}</span>

          <span class="chip">容量 ${w.capacity||'—'}</span>

        </div>

        <div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">信息</div>

          <div class="kv">

            <span class="k">作者</span><span>${esc(w.author||'—')}</span>

            <span class="k">创建时间</span><span>${fmtLast(w.created)}</span>

            <span class="k">最后更新</span><span>${fmtLast(w.updated)}</span>

            <span class="k">访问量</span><span>${w.visits!=null? w.visits.toLocaleString() : '—'}</span>

            <span class="k">收藏数</span><span>${w.favorites!=null? w.favorites.toLocaleString() : '—'}</span>

            <span class="k">当前热度</span><span>${w.heat!=null? w.heat : '—'}</span>

            <span class="k">推荐人数</span><span>${w.recommended_capacity? w.recommended_capacity+'（上限 '+ (w.capacity||'—') +'）':'—'}</span>

            <span class="k">发布时间</span><span>${fmtLast(w.publication)}</span>

          </div>

          ${tags.length?`<div style="margin-top:6px">${tags.map(t=>`<span class="chip">${esc(t)}</span>`).join('')}</div>`:''}

        </div>

        <div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">VRCX 信息（本地统计）</div>

          <div class="kv">

            <span class="k">游玩次数</span><span>${r.visits_local!=null? r.visits_local : '—'}</span>

            <span class="k">最后游玩</span><span>${r.last_visit?fmtTs(r.last_visit):'—'}</span>

          </div></div>

        <div class="card" style="margin:0"><div class="dim" style="font-size:12px;margin-bottom:4px">备注（本地保存）</div>

          <textarea id="wnoteText" oninput="DETAIL_CURRENT.noteDraft=this.value" rows="2" style="width:100%">${esc(DETAIL_CURRENT?.noteDraft??r.note??'')}</textarea>

          <div class="row" style="margin-top:6px;justify-content:flex-end">

            <button class="ghost mini" onclick="saveWorldNote(this)">保存备注</button></div></div>

      </div>

      <div>

        <div class="tabs" id="wtabs">

          <button class="tabbtn ${WTAB==='rooms'?'active':''}" data-t="rooms" onclick="setWTab('rooms')">房间</button>

          <button class="tabbtn ${WTAB==='json'?'active':''}" data-t="json" onclick="setWTab('json')">原始 JSON 信息</button>

        </div>

        <div id="wtabBody"></div>

      </div>

    </div>`;

  IMAGES.restore(c,photos);
  renderWTab();

}

function renderWTab(){

  const r = WD_DATA, w = r.world;

  const box = document.getElementById('wtabBody');

  if (WTAB==='rooms'){

    const rows = (r.instances||[]).map(i=>{

      const dot = INST_DOT[i.label]||'#3ddc84';

      return `<div class="fitem" style="cursor:pointer;display:block" onclick="openInstance('${esc(i.location)}')">`+

        `<div style="display:flex"><span><span class="dot" style="background:${dot};margin-right:8px"></span>${esc(i.label)} · <b>#${esc(i.num)}</b>`+

        `${i.region?` <span class="dim">· ${esc(i.region)}</span>`:''}</span>`+

        `<span class="dim" style="margin-left:auto">${i.count!=null?i.count+' 人在线':'人数待查询'}</span></div>`+

        ((i.friends_in&&i.friends_in.length)?`<div class="dim" style="font-size:12px;margin-top:4px;padding-left:18px">房内好友: ${i.friends_in.map(x=>esc(x)).join('、')}</div>`:'')+

        (i.creator?`<div class="dim" style="font-size:12px;padding-left:18px">创建者: ${esc(i.creator)}</div>`:'')+

        `</div>`;

    }).join('') || `<div class="detail-loading">${r.stale?'房间信息加载中…':'当前没有可见实例'}</div>`;

    box.innerHTML = `

      <div class="card" style="margin:0 0 10px"><div class="dim" style="font-size:12px;margin-bottom:4px">房间</div>

        <div class="dim" style="font-size:13px">公开房间 <b>${r.pub_online??'—'}</b>人在线 · 非公开房间 <b>${r.priv_online??'—'}</b>人在线</div></div>

      <div class="card" style="margin:0">${rows}</div>`;

  } else {

    box.innerHTML = `<pre class="jsonbox">${esc(JSON.stringify(w.raw, null, 2))}</pre>`;

  }

}

// Same ownership priority as the pinned VRCX locationParser: private, friends,
// hidden, then group. A world author is never an instance creator.
function roomFacts(loc,live={},account=window._CURSRC){
  const tags=new Map((loc.split(':')[1]||'').split('~').slice(1).map(tag=>{
    const match=/^([^()]+)\(([^()]*)\)$/.exec(tag);return match?[match[1],match[2]]:[tag,''];
  }));
  const token=['private','friends','hidden','group'].find(key=>tags.has(key));
  const candidate=live.creator_id||live.ownerId||(token?tags.get(token):'')||'';
  const id=/^(usr|grp)_[A-Za-z0-9_-]+$/.test(candidate)?candidate:'';
  const row=(window._FRIENDS||[]).find(f=>f.id===id);
  const friend=row?._accounts?row._accounts[account]:row;
  const kind=id.startsWith('grp_')?'group':id.startsWith('usr_')?'user':'';
  let label='公开';
  if(tags.has('private'))label=tags.has('canRequestInvite')?'邀请+':'仅限邀请';
  else if(tags.has('friends'))label='仅限好友';
  else if(tags.has('hidden'))label='好友+';
  else if(tags.has('group'))label=tags.get('groupAccessType')==='plus'?'群组+':'群组';
  return {id,kind,name:live.creator_name||friend?.name||friend?.display_name||id,label,region:tags.get('region')||''};
}

async function openInstance(loc,src){
  if(!loc||!loc.includes(':')) return;
  const account=detailAccount(src);
  const task=beginDetail('instance',loc,account);
  const wid=loc.split(':')[0],path='/api/instance?location='+encodeURIComponent(loc);
  let result=APP.client.peek(path,account)||{world:APP.client.peek('/api/world?id='+encodeURIComponent(wid),account)?.world,stale:true};
  let world=result.world||{},worldLoaded=false,resolvedOwner=null,resolving='';
  let tries=0;
  const render=()=>{
    const live=result.live||{},facts=roomFacts(loc,live,account);
    const owner=resolvedOwner?.id===facts.id?resolvedOwner:facts;
    const card=document.getElementById('mcard'),photos=IMAGES.capture(card,true);
    const pending=result.stale&&tries<10;
    const ownerAction=owner.kind==='group'?'openGroup':'openFriend';
    card.innerHTML=detailHead('实例详情')+
      `${world.thumb?`<img class="wthumb" ${mediaAttrs(world.thumb,account,'high')} alt="${esc(world.name||'世界')}">`:''}<h2>${esc(world.name||wid)}</h2>`+
      `${result.stale?'<p class="dim">当前房间状态未确认，以下显示已有信息。</p>':''}`+
      `<div class="kv"><span class="k">实例编号</span><span style="overflow-wrap:anywhere">${esc(result.instance_id||loc.split(':')[1])}</span><span class="k">类型</span><span>${esc(facts.label)}</span>`+
      `<span class="k">房间建立者</span><span>${owner.id&&owner.kind?`<button class="text-button" onclick="${ownerAction}('${esc(owner.id)}','${account}')">${esc(owner.name||owner.id)}</button>`:'未记录'}</span>`+
      `<span class="k">区域</span><span>${esc(facts.region||'未记录')}</span>`+
      `<span class="k">${result.stale&&live.user_count!=null?'上次记录人数':'当前人数'}</span><span>${live.user_count!=null?esc(live.user_count):pending?'查询中…':'未能获取'}${live.capacity!=null?' / '+esc(live.capacity):''}</span></div>`+
      `<details><summary>完整房间地址</summary><code style="overflow-wrap:anywhere">${esc(loc)}</code></details>`+
      `<div class="card"><strong>房内好友</strong>${(result.friends_in||live.friends_in||[]).map(f=>`<button class="room-friend" onclick="openFriend('${esc(f.id)}','${account}')">${esc(f.name)}</button>`).join('')||'<p class="dim">没有已知好友</p>'}</div>`+
      `<button class="ghost" onclick="openWorld('${esc(wid)}','${account}')">世界详情</button>`;
    IMAGES.restore(card,photos);
  };
  const resolveOwner=()=>{
    const owner=roomFacts(loc,result.live||{},account);
    if(!owner.kind||owner.name!==owner.id||resolving===owner.id)return;
    resolving=owner.id;
    let attempts=0;
    const load=async()=>{
      try{
        const data=await gGet('/api/'+(owner.kind==='group'?'group':'friend')+'?id='+encodeURIComponent(owner.id),{account,force:true});
        if(!task.current()||roomFacts(loc,result.live||{},account).id!==owner.id)return;
        const info=owner.kind==='group'?data.group:data.user;
        const name=owner.kind==='group'?info?.name:info?.displayName;
        if(info?.id===owner.id&&name&&name!==owner.id){resolvedOwner={...owner,name};render();}
        else if(data.stale&&attempts++<4)detailLater(task,load,2000);
      }catch(e){/* The recorded owner ID remains usable when its profile is unavailable. */}
    };
    load();
  };
  render();resolveOwner();
  const update=async()=>{
    try{
      const next=await gGet(path,{account,force:true});
      if(!task.current()) return;
      result=next;if(!worldLoaded&&(next.world?.thumb||!world.thumb))world=next.world||world;
      if(next.stale)tries++;
      render();resolveOwner();
      if(next.stale&&tries<10) detailLater(task,update,2000);
    }catch(e){if(task.current()&&!VRCXRuntime.ignored(e)) reportError(e);}
  };
  // World metadata and its image must not wait for the instance/creator request.
  let worldTries=0;
  const updateWorld=async()=>{
    try{
      const next=await gGet('/api/world?id='+encodeURIComponent(wid),{account,force:true});
      if(!task.current())return;
      if(next.world?.thumb||!world.thumb)world=next.world||world;
      if(next.world?.thumb)worldLoaded=true;
      render();
      if(next.stale&&worldTries++<10)detailLater(task,updateWorld,2000);
    }catch(e){/* The instance can still show its recorded room information. */}
  };
  updateWorld();
  await update();
}
function closeModal(fromHistory=false){
  APP.tasks.cancel('modal');APP.tasks.cancel('user-section');APP.tasks.cancel('user-room');
  const wasOpen=!document.getElementById('modal').classList.contains('hidden');
  CURUSER=null; UD=null; AVD=null; WD_DATA=null; GD=null;
  DETAIL_CURRENT=null;DETAIL_TRAIL.length=0;
  window._CURSRC=null;
  document.getElementById('modal').classList.add('hidden');
  document.getElementById('mcard').classList.remove('wide');
  document.body?.classList.remove('detail-open');
  if(wasOpen&&!fromHistory) window.MobileUI?.detailClosed();
}

/* ---------- 直达 direct-access（审计 A6，上游 navMenuUtils:127 恒末位） ---------- */

function directGo(){

  const raw = v('directInput');

  const msg = document.getElementById('directMsg');

  let id = '';

  const mUrl = raw.match(/vrchat\.com\/home\/(user|world|avatar|group)\/(usr_|wrld_|avtr_|grp_)?([0-9a-f-]{20,})/i);

  const mId = raw.match(/\b(usr|wrld|avtr|grp)_[0-9a-f-]{20,}\b/i);

  if (mUrl){ id = (mUrl[2] || ({user:'usr_',world:'wrld_',avatar:'avtr_',group:'grp_'})[mUrl[1].toLowerCase()]) + mUrl[3]; }

  else if (mId){ id = mId[0]; }

  if (!id){ msg.textContent = ' 未识别到有效的 ID 或链接'; return; }

  msg.textContent = '打开中…';

  if (id.startsWith('usr_')){ openFriend(id); msg.textContent=''; }

  else if (id.startsWith('wrld_')){ openWorld(id); msg.textContent=''; }

  else if (id.startsWith('avtr_')){ openAvatarDlg(id); msg.textContent=''; }

  else { openGroup(id); msg.textContent=''; }

}

/* ---------- 共同好友图（上游 MutualFriends 的 Pi 等价，API 数据） ---------- */

async function loadMutualGraph(){
  const task = APP.tasks.begin('loadMutualGraph');

  const box = document.getElementById('mutualGraph');

  box.innerHTML = '<div class="dim">拉取中（好友两两共同好友，逐个调用 mutuals API，可能需要一点时间）…</div>';

  const r = await gGet('/api/mutual-graph');
    if (!task.current()) return;

  if (r.error){ box.innerHTML = '<div class="msg">'+esc(r.error)+'</div>'; return; }

  const edges = r.edges || [];

  const byUser = {};

  edges.forEach(e=>{ byUser[e.a]=byUser[e.a]||new Set(); byUser[e.a].add(e.b);

                     byUser[e.b]=byUser[e.b]||new Set(); byUser[e.b].add(e.a); });

  const ranked = Object.entries(byUser).map(([n,s])=>[n,s.size]).sort((x,y)=>y[1]-x[1]).slice(0,25);

  const max = ranked.length? ranked[0][1] : 1;

  box.innerHTML = ranked.map(([n,c])=>

    `<div class="bar-row"><span class="bar-name">${esc(n)}</span>`+

    `<span class="bar-track"><span class="bar-fill" style="width:${Math.round(c/max*100)}%"></span></span>`+

    `<span class="bar-val">与 ${c} 位好友有共同好友</span></div>`).join('')

    || '<div class="dim">没有共同好友数据</div>';

}

/* ---------- 状态预设（F-18） / VRChat 服务状态（F-19） / 群组详情（F-14） ---------- */

async function loadPresets(){

  try{

    const r = await gGet('/api/status-presets');

    const sel = document.getElementById('presetSel');

    const list = r.presets||[];

    sel.innerHTML = list.length

      ? list.map((p,i)=>`<option value="${i}">${esc(p.desc||STATUS_LABEL[p.status]||p.status)}</option>`).join('')

      : '<option value="">（无预设）</option>';

  }catch(e){ reportError(e); }

}

async function savePreset(){

  const r = await gPost('/api/preset-add', {status: document.getElementById('myStatus').value,

    desc: document.getElementById('myDesc').value});

  const msg = document.getElementById('myStatusMsg');

  if (r.ok && r.result==='ok'){ msg.textContent=' 已保存为预设'; loadPresets(); }

  else if (r.result==='exists'){ msg.textContent=' 已存在相同预设'; }

  else if (r.result==='limit'){ msg.textContent=' 预设已满（上限10个），请先删除'; }

  setTimeout(()=>document.getElementById('myStatusMsg').textContent='', 2500);

}

async function removePreset(){

  const i = +(document.getElementById('presetSel').value||0);

  const r = await gPost('/api/preset-remove', {index: i});

  if (r.ok){ loadPresets(); } else alert('删除失败');

}

let VRC_STATUS = null;

async function loadVrcStatus(){

  try{

    if (!VRC_STATUS || Date.now()-VRC_STATUS.at >120000){

      VRC_STATUS = {at: Date.now(), data: await gGet('/api/vrc-status')};

    }

    const s = VRC_STATUS.data;

    const vsc = document.getElementById('vrcStatusCard');

    if (!vsc) return;  // 该卡所在区块不在当前页

    vsc.innerHTML = s.issue

      ? `<div class="num" style="color:var(--red);font-size:15px;line-height:1.3">${esc(s.summary||'服务异常')}</div>

         <div class="lbl"><a href="https://status.vrchat.com" target="_blank" rel="noopener" style="color:inherit">状态页 ↗</a>· ${fmtLast(s.updated)}</div>`

      : `<div class="num" style="color:var(--green);font-size:20px">正常</div><div class="lbl">VRChat 服务</div>`;

  }catch(e){ reportError(e); }

}

let GD = null, GTAB = 'info';

async function openGroup(gid){
  const account=detailAccount();
  const task = beginDetail('group',gid,account);

  const m = document.getElementById('modal'), c = document.getElementById('mcard');

  m.classList.remove('hidden');

  c.classList.add('wide');

  c.innerHTML = detailHead('群组详情')+'<div class="dim">加载中…</div>';

  const r = await gGet('/api/group?id='+encodeURIComponent(gid),{account});
  if (!task.current()) return;

  if (r.error){ c.innerHTML = `<div class="msg">${esc(r.error)}</div>`; return; }

  GD = r.group;

  c.innerHTML = `

    ${detailHead('群组详情')}

    <div class="ugrid">

      <div class="ucard">

        ${GD.banner?`<div class="ubanner" style="background:url('${esc(GD.banner)}') center/cover"></div>`:''}

        ${GD.icon?`<img class="uavatar" ${mediaAttrs(GD.icon,window._CURSRC)}>`:''}

        <div class="uname">${esc(GD.name)}</div>

        <div class="kv" style="text-align:left">

          <span class="k">成员</span><span>${GD.memberCount!=null? GD.memberCount.toLocaleString() : '—'}</span>

          <span class="k">创建时间</span><span>${fmtLast(GD.createdAt)}</span>

          <span class="k">可见性</span><span>${esc(GD.visibility||'—')}</span>
        <button class="ghost mini" style="color:var(--red);border-color:var(--red);width:100%;margin-top:6px"
          data-group-id="${esc(GD.id)}" data-group-name="${esc(GD.name)}"
          onclick="if(confirm('确认退出群组「'+this.dataset.groupName+'」？此操作同步到 VRChat。'))leaveGroup(this.dataset.groupId)">退出群组</button>

        </div>

      </div>

      <div>

        <div class="tabs" id="gdtabs">

          <button class="tabbtn active" data-t="info" onclick="setGDTab('info')">信息</button>

          <button class="tabbtn" data-t="members" onclick="setGDTab('members')">成员</button>

          <button class="tabbtn" data-t="json" onclick="setGDTab('json')">原始 JSON 信息</button>

        </div>

        <div id="gdBody"></div>

      </div>

    </div>`;

  setGDTab('info');

}

async function leaveGroup(gid){
  const r = await gPost('/api/group-leave', {id: gid, confirm: '是，退出'});
  alert(r.ok ? ' 已退出群组' : ' '+(r.error||'失败'));
  if (r.ok){ closeModal(); loadFavorites(); }
}
function setGDTab(t){
  const task=APP.tasks.begin('group-tab'), group=GD;
  GTAB=t;
  if (!group) return;

  document.querySelectorAll('#gdtabs .tabbtn').forEach(b=>b.classList.toggle('active', b.dataset.t===t));

  const box = document.getElementById('gdBody');

  if (t==='json') box.innerHTML = `<pre class="jsonbox">原始 JSON 需重新拉取（详情页信息即全部字段）</pre>`;

  else if (t==='members'){

    box.innerHTML = '<div class="dim">拉取成员名单…</div>';

    gGet('/api/group-members?id='+encodeURIComponent(group.id),{account:DETAIL_CURRENT?.account||GA}).then(r=>{
      if (!task.current() || GD!==group || !box.isConnected) return;

      if (r.error){ box.innerHTML = `<div class="msg">${esc(r.error)}</div>`; return; }

      box.innerHTML = (r.length? r.map(m=>

        `<div class="fitem"><span class="name">${esc(m.name)}</span>`+

        (m.id && m.id.startsWith('usr_')?`<button class="ghost mini" style="margin-left:auto" onclick="openFriend('${esc(m.id)}')">详情</button>`:'')+

        `</div>`).join('') : '<div class="dim">无法获取成员名单（非成员不可见）</div>');

    }).catch(e=>{if(task.current()) reportError(e);});

  }

  else box.innerHTML = GD.description ? `<div class="card" style="margin:0"><div class="bio">${esc(GD.description)}</div></div>` : '<div class="dim">无描述</div>';

}

/* ---------- F-16 仪表板 widget 化 ---------- */
const DEFAULT_DASHS=[{name:'默认仪表板',widgets:['feed','online','web','vrcsvc']}];
let DASHS;
try{ DASHS=JSON.parse(localStorage.getItem('vrcxDashs')||'null'); }catch(e){ DASHS=null; }
if(!Array.isArray(DASHS)||!DASHS.length) DASHS=DEFAULT_DASHS;
DASHS=DASHS.filter(d=>d && typeof d.name==='string' && Array.isArray(d.widgets));
if(!DASHS.length) DASHS=DEFAULT_DASHS;
for(const d of DASHS) d.widgets=d.widgets.filter(t=>['feed','online','web','vrcsvc','gamelog','instance'].includes(t));
let DASH_IDX = 0;
const WIDGET_TITLES = {feed:'最近动态', online:'游戏内好友', web:'网页在线好友',
  vrcsvc:'VRChat 服务状态', gamelog:'游戏日志（Companion）', instance:'当前实例（Companion）'};
if (!localStorage.getItem('vrcxDashs')) saveDashs();  // 首次访问持久化默认布局
function saveDashs(){ localStorage.setItem('vrcxDashs', JSON.stringify(DASHS)); }
function buildDashNav(){
  const nav = document.getElementById('nav');
  [...nav.querySelectorAll('button[data-dash]')].forEach(b=>b.remove());
  if(!pageAllowed('dash')) return;
  const directBtn = nav.querySelector('button[data-p="direct"]');
  DASHS.forEach((d,i)=>{
    const b = document.createElement('button');
    b.dataset.p = 'dash-'+i; b.dataset.dash = '1';
    b.innerHTML = `<span></span><span>${esc(d.name)}</span>`;
    b.onclick = ()=>switchPage('dash-'+i);
    nav.insertBefore(b, directBtn);
  });
}
function renderDashWidgets(){
  const d = DASHS[DASH_IDX];
  const grid = document.getElementById('widgetsGrid');
  if (!d || !grid) return;
  grid.innerHTML = d.widgets.map((t,i)=>
    `<div class="widget"><div class="whead"><span class="t">${esc(WIDGET_TITLES[t]||t)}</span>`+
    `<span><button class="ghost mini" onclick="moveWidget(${i},-1)">↑</button>`+
    `<button class="ghost mini" onclick="moveWidget(${i},1)">↓</button>`+
    `<button class="ghost mini" onclick="removeWidget(${i})" aria-label="移除此面板">移除</button></span></div>`+
    `<div id="wd-${t}-${i}"><div class="dim">加载中…</div></div></div>`).join('')
    || '<div class="dim">没有面板——上方“添加面板”</div>';
  return Promise.all(d.widgets.map((t,i)=>renderWidget(t, `wd-${t}-${i}`)));
}
function renderWidget(t, elId){
  const el = document.getElementById(elId), task=APP.tasks.begin('widget-'+elId);
  if(!el) return;
  const current=()=>task.current() && el.isConnected;
  if (t==='feed'){
    return gGet('/api/feed').then(r=>{
      if(!current()) return;
      el.innerHTML = r.events.slice(0,12).map(e=>{
        const badge = `<span class="chip big ${EV_BADGE[e.event]||''}">${WEB_OFFLINE_LABEL(e)}</span>`;
        const dt = e.event==='offline'
          ? `${sessionDurationText(e)}${e.world_name?' · '+esc(e.world_name):''}`
          : e.event==='location' ? '→ '+esc(e.world_name||'')
          : e.event==='active' ? '<span style="color:#2563eb">网页在线</span>'
          : esc(e.world_name||'');
        return `<div class="fitem"><span class="ftime">${fmtTs(e.ts)}</span>${badge}<span>${dt}</span></div>`;
      }).join('') || '<div class="dim">暂无</div>';
    }).catch(e=>{if(current()) reportError(e);});
  } else if (t==='online' || t==='web'){
    return gGet('/api/friends').then(r=>{
      if(!current()) return;
      const fs = r.friends.filter(f=>t==='online' ? (f.online&&!f.web_online) : f.web_online);
      el.innerHTML = fs.map(f=>
        `<div class="frow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">`+
        `<span class="name" style="color:${f.trust.color||'inherit'}">${esc(f.name)}</span>`+
        `<span class="dim" style="margin-left:auto;font-size:12px">${esc(f.world||'网页')}</span></div>`).join('')
        || '<div class="dim">无</div>';
    }).catch(e=>{if(current()) reportError(e);});
  } else if (t==='vrcsvc'){
    el.innerHTML = '<div class="dim">加载中…</div>';
    return gGet('/api/vrc-status').then(s=>{
      if(!current()) return;
      el.innerHTML = s.issue
        ? `<div style="color:var(--red)">${esc(s.summary||'服务异常')}</div>`+
          `<div class="dim" style="font-size:11px"><a href="https://status.vrchat.com" target="_blank" rel="noopener" style="color:inherit">状态页 ↗</a></div>`
        : '<div style="color:var(--green)">全部系统正常</div>';
    }).catch(e=>{if(current()) reportError(e);});
  } else if (t==='gamelog' || t==='instance'){
    el.innerHTML = `<div class="dim">此组件需要尚未提供的游戏端连接，可以使用上方按钮移除。</div>`;
  }
}
function addWidget(){
  const t = document.getElementById('addWidgetSel').value;
  DASHS[DASH_IDX].widgets.push(t); saveDashs(); renderDashWidgets();
}
function removeWidget(i){ DASHS[DASH_IDX].widgets.splice(i,1); saveDashs(); renderDashWidgets(); }
function moveWidget(i, d){
  const w = DASHS[DASH_IDX].widgets;
  const j = i + d;
  if (j<0 || j>=w.length) return;
  [w[i], w[j]] = [w[j], w[i]]; saveDashs(); renderDashWidgets();
}
function createDash(){
  const name = prompt('新仪表板名称:', '仪表板 ' + (DASHS.length));
  if (!name) return;
  DASHS.push({name, widgets:['feed']}); saveDashs(); buildDashNav();
  switchPage('dash-'+(DASHS.length-1));
}
function deleteDash(){
  if (DASHS.length<=1){ alert('至少保留一个仪表板'); return; }
  if (!confirm('删除仪表板「'+DASHS[DASH_IDX].name+'」？')) return;
  DASHS.splice(DASH_IDX,1); saveDashs(); buildDashNav(); switchPage('dash-0');
}
function renameDash(){
  const name = prompt('重命名仪表板:', DASHS[DASH_IDX].name);
  if (!name) return;
  DASHS[DASH_IDX].name = name; saveDashs(); buildDashNav();
  document.querySelectorAll('.nav button[data-dash]')[DASH_IDX].innerHTML = `<span></span><span>${esc(name)}</span>`;
}

/* ---------- F-10 Quick Search（Ctrl+K） ---------- */
let QS_T = null;
function openQS(){
  clearTimeout(QS_T); APP.tasks.cancel('doQuickSearch');
  document.getElementById('qsOverlay').classList.remove('hidden');
  const i = document.getElementById('qsInput'); i.value=''; i.focus();
  document.getElementById('qsBody').innerHTML = '<div class="dim">输入关键词，或直接粘贴 usr_/wrld_/avtr_/grp_ ID</div>';
}
function closeQS(){ clearTimeout(QS_T); APP.tasks.cancel('doQuickSearch'); document.getElementById('qsOverlay').classList.add('hidden'); }
function qsOnInput(){ APP.tasks.cancel('doQuickSearch'); clearTimeout(QS_T); QS_T = setTimeout(doQuickSearch, 350); }
async function doQuickSearch(){
  const task = APP.tasks.begin('doQuickSearch');
  const q = v('qsInput').trim();
  const box = document.getElementById('qsBody');
  if (!q){ box.innerHTML = '<div class="dim">输入开始搜索</div>'; return; }
  const mId = q.match(/\b(usr|wrld|avtr|grp)_[0-9a-f-]{20,}\b/i);
  if (mId && mId[0]){
    const id = mId[0]; const kind = id.slice(0,4);
    box.innerHTML = `<div class="srow" onclick="${kind==='usr_'?"openFriend":kind==='wrld_'?"openWorld":kind==='avtr_'?"openAvatarDlg":"openGroup"}('${esc(id)}')"><span class="name">直达: ${esc(id)}</span></div>`;
    return;
  }
  const fs = (window._FRIENDS||[]).filter(f=>(f.name||'').toLowerCase().includes(q.toLowerCase()));
  let html = fs.length ? '<div class="dim" style="margin:4px 0">好友</div>' + fs.slice(0,6).map(f=>
    `<div class="srow" onclick="openFriend('${esc(f.id)}','${f._src||''}')">`+
    `<span class="name" style="color:${f.trust.color||'inherit'}">${esc(f.name)}</span>`+
    `<span class="dim" style="margin-left:auto;font-size:12px">${f.online?'在线':'离线'}</span></div>`).join('') : '';
  box.innerHTML = html || '<div class="dim">搜索中…</div>';
  return Promise.all([
    gGet('/api/search?q='+encodeURIComponent(q)),
    gGet('/api/world-search?q='+encodeURIComponent(q)),
    gGet('/api/group-search?q='+encodeURIComponent(q))]).then(([u,w,g])=>{
    if(!task.current()) return;
    let extra = '';
    if ((u.users||[]).length)
      extra += '<div class="dim" style="margin:6px 0 2px">用户</div>' + u.users.map(x=>
        `<div class="srow" onclick="openFriend('${esc(x.id)}')">${x.thumb?`<img ${mediaAttrs(x.thumb,window._CURSRC)}>`:''}`+
        `<span class="name" style="color:${x.trust.color||'inherit'}">${esc(x.name)}</span></div>`).join('');
    if ((w.worlds||[]).length)
      extra += '<div class="dim" style="margin:6px 0 2px">世界</div>' + w.worlds.slice(0,6).map(x=>
        `<div class="srow" onclick="openWorld('${esc(x.id)}')">${x.thumb?`<img ${mediaAttrs(x.thumb,window._CURSRC)}>`:''}`+
        `<span class="name">${esc(x.name)}</span></div>`).join('');
    if ((g.groups||[]).length)
      extra += '<div class="dim" style="margin:6px 0 2px">群组</div>' + g.groups.slice(0,6).map(x=>
        `<div class="srow" onclick="openGroup('${esc(x.id)}')">${x.icon?`<img ${mediaAttrs(x.icon,window._CURSRC)}>`:''}`+
        `<span class="name">${esc(x.name)}</span></div>`).join('');
    box.innerHTML = html + extra || '<div class="dim">没有结果</div>';
  }).catch(e=>{if(task.current()) reportError(e);});
}
document.addEventListener('keydown', e=>{
  if ((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openQS(); }
});
async function applyPreset(){
  const i = +(document.getElementById('presetSel').value||0);
  const r = await gGet('/api/status-presets');
  const p = (r.presets||[])[i];
  if (!p){ alert('没有可用的预设'); return; }
  const res = await gPost('/api/set-status', {status: p.status, desc: p.desc});
  const el = document.getElementById('myStatusMsg');
  el.textContent = res.ok ? ' 预设已应用' : ' '+(res.error||'失败');
  setTimeout(()=>el.textContent='', 2500);
}

async function applyPresetByIndex(i){
  const r0 = await gGet('/api/status-presets');
  const p = (r0.presets||[])[i];
  if (!p) return;
  const res = await gPost('/api/set-status', {status: p.status, desc: p.desc});
  loadSelf();
  if (!res.ok) alert('应用失败: ' + (res.error||''));
}
