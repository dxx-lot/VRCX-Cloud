#!/usr/bin/env python3
"""Run the real UI with synthetic HTTP Responses, without credentials or a server.

This supplements (does not replace) HTTP integration and Pi validation. Open the
generated HTML in a browser; its visible report executes account/page/modal races.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "webui"
OUT = ROOT / "artifacts" / "acceptance" / "framework" / "browser-fixture.html"

FIXTURE = r"""
window.fixture={errors:[],calls:[],delayA:0,delayFriend:0};
window.addEventListener('error',e=>fixture.errors.push(e.message));
localStorage.setItem('ga','a');
const friendsOf=account=>[{id:'usr_'+account,name:'好友'+account,state:'online',online:true,
  web_online:false,location:'wrld_'+account+':1',world:'世界'+account,trust:{name:'用户',color:'#16a34a'},thumb:''}];
const me=account=>({id:'usr_self_'+account,name:'账号'+account,username:'test'+account,
  logged_in:true,state:'active',status:'active',desc:'',location:'',thumb:'',friends_count:1,trust:{color:'#16a34a'}});
const config={bark:{enabled:false,level:'active',group:'VRCX',sound:'',critical_volume:5,key_masked:''},
  telegram:{enabled:false,bot_token_masked:'',chat_id:''},poll_seconds:30,favorites_sync_seconds:300,
  notify_online:true,notify_offline:true,watch_favorites:false,watch:[],push_mode:'favorites'};
const eventsOf=account=>[{id:1,friend_id:'usr_'+account,display_name:'好友'+account,event:'online',ts:100,
  status:'active',world_name:'世界'+account,location:'wrld_'+account+':1'}];
window.fetch=async (url,opts={})=>{
  let target=new URL(url,'http://fixture.local'),account='A';
  if(target.pathname==='/api/peer-relay'||target.pathname==='/api/peer-relay-post'){
    target=new URL(target.searchParams.get('path'),'http://fixture.local');account='B';
  }
  fixture.calls.push({path:target.pathname,account,method:opts.method||'GET'});
  if(account==='A'&&fixture.delayA) await new Promise(r=>setTimeout(r,fixture.delayA));
  if(target.pathname==='/api/friend'&&fixture.delayFriend) await new Promise(r=>setTimeout(r,fixture.delayFriend));
  let value={ok:true};
  switch(target.pathname){
    case '/api/self':value=me(account);break;
    case '/api/status':value={logged_in:true,watch_source:{ids:['usr_'+account]}};break;
    case '/api/friends':value={friends:friendsOf(account)};break;
    case '/api/feed':case '/api/history':value={events:eventsOf(account)};break;
    case '/api/friend':value={user:{id:target.searchParams.get('id'),displayName:'详情'+target.searchParams.get('id'),
      trust:{name:'用户',color:'#16a34a'},languages:[],state:'active',cur_state:'active',bioLinks:[]},
      events:[],groups:[],worlds_created:[],avatars_created:[],heat:[],mutual:{friends:[],counts:[]},raw:{}};break;
    case '/api/config':value=config;break;
    case '/api/push-config':value={mode:'favorites',friends:friendsOf(account),watch:[]};break;
    case '/api/status-presets':value={presets:[{status:'active',desc:'test'}]};break;
    case '/api/net-stats':value={rate:0,total:0,today:0,hour1:0,hour24:0,mem_pct:1,cpu_pct:1};break;
    case '/api/vrc-status':value={issue:false,summary:'正常'};break;
    case '/api/ui-version':value={v:'fixture'};break;
    case '/api/favgroups':value={groups:[],items:[],type:'friend'};break;
    case '/api/notifications':value={items:[],notifications:[]};break;
    case '/api/avatars':value={own:[],favorites:[],current:null};break;
    case '/api/moderations':value={items:[]};break;
    case '/api/friendlog':value={events:[]};break;
    case '/api/backup':value={files:[]};break;
    case '/api/stats':value={friends:[],worlds:[],daily:[],heat:[],hours:[],heatmap:[],hour_bins:[]};break;
    case '/api/search':value={users:[]};break;
    case '/api/world-search':value={worlds:[]};break;
    case '/api/group-search':value={groups:[]};break;
    case '/api/mutual-graph':value={nodes:[],edges:[]};break;
  }
  return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
};
window.EventSource=class {
  constructor(){setTimeout(()=>this.onopen?.(),0);}
  addEventListener(type,callback){if(type==='feed')fixture.localEvent=callback;}
  close(){}
};
"""

CHECKS = r"""
window.addEventListener('load',async()=>{
  const report=document.getElementById('fixtureReport');
  const results=[];
  const pause=ms=>new Promise(r=>setTimeout(r,ms));
  const check=(label,condition)=>{results.push((condition?'PASS ':'FAIL ')+label);report.textContent=results.join('\n');};
  try{
    await pause(150);APP.scheduler.stop();
    check('初始账号 A',document.getElementById('selfName').textContent==='账号A');
    APP.client.invalidate('a');fixture.delayA=250;loadSelf();loadAccount();
    switchGA('b');await pause(350);fixture.delayA=0;
    check('慢 A 响应不会覆盖 B',document.getElementById('selfName').textContent==='账号B');
    check('A/B 胶囊标签隔离',document.querySelector('#gswitch [data-g="a"]').textContent==='账号A' && document.querySelector('#gswitch [data-g="b"]').textContent==='账号B');
    check('B 动态不混入 A',document.getElementById('feedTable').textContent.includes('好友B') && !document.getElementById('feedTable').textContent.includes('好友A'));
    fixture.localEvent({data:JSON.stringify(eventsOf('A')[0])});await pause(300);
    check('本机 SSE 不污染 B 动态',!document.getElementById('feedTable').textContent.includes('好友A'));
    switchGA('m');await pause(150);
    check('合并左右账号一致',document.getElementById('scMerge').textContent.includes('账号A') && document.getElementById('scMerge').textContent.includes('账号B'));
    switchGA('b');switchPage('favorites');await pause(60);switchGA('a');await pause(60);
    check('切账号保持合法页面',!document.getElementById('page-favorites').classList.contains('hidden'));
    switchGA('m');await pause(80);
    check('合并视角不进入写操作页',document.getElementById('page-favorites').classList.contains('hidden') && !document.getElementById('page-feed').classList.contains('hidden'));
    switchGA('b');await pause(80);fixture.delayFriend=180;
    openFriend('usr_old');await pause(10);closeModal();await pause(250);
    check('关闭详情后慢响应不会重开弹窗',document.getElementById('modal').classList.contains('hidden'));
    fixture.delayFriend=150;openFriend('usr_old');await pause(10);fixture.delayFriend=0;openFriend('usr_new');await pause(220);
    check('旧详情不会覆盖新详情',document.getElementById('mcard').textContent.includes('详情usr_new'));
    closeModal();switchPage('dash');await pause(100);
    check('仪表板动态遵循 B 视角',!document.getElementById('widgetsGrid').textContent.includes('世界A'));
    check('无 JavaScript 运行错误',fixture.errors.length===0);
    report.dataset.failed=String(results.filter(x=>x.startsWith('FAIL')).length);
    report.dataset.finished='true';
  }catch(e){report.textContent+='\nFAIL '+e.stack;report.dataset.failed='1';report.dataset.finished='true';}
  APP.scheduler.stop();
});
"""


def build():
    html = (WEB / "templates" / "index.html").read_text().replace("__UI_VER__", "fixture")
    html = re.sub(r'<link rel="stylesheet" href="/static/([^?]+)\?[^>]+>',
                  lambda m: "<style>" + (WEB / "static" / m[1]).read_text() + "</style>", html)
    html = html.replace("<head>", "<head><script>" + FIXTURE + "</script>", 1)
    html = re.sub(r'<script defer src="/static/([^?]+)\?[^\"]+"></script>',
                  lambda m: "<script>" + (WEB / "static" / m[1]).read_text() + "</script>", html)
    report = '<pre id="fixtureReport" style="position:relative;z-index:999;background:#111;color:#fff;padding:12px;white-space:pre-wrap">Synthetic browser regression: running…</pre>'
    html = html.replace("<body>", "<body>" + report, 1)
    html = html.replace("</body>", "<script>" + CHECKS + "</script></body>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(OUT)


if __name__ == "__main__":
    build()
