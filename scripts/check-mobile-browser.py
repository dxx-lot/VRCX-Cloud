#!/usr/bin/env python3
"""Real Chromium/HTTP tests of shipped UI with synthetic native Responses.

No VRChat requests or credentials. Screenshots contain only generated test data.
"""
import hashlib
import base64
import importlib.util
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src/webui'
OUT = Path(os.environ.get('VRCX_BROWSER_OUTPUT', str(ROOT / 'artifacts/acceptance/mobile'))).resolve()
spec = importlib.util.spec_from_file_location('fixture', ROOT/'scripts/build-browser-fixture.py')
fixture = importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

EXTRA = r"""
const scene='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450"><defs><linearGradient id="s" x2="0" y2="1"><stop stop-color="#65749e"/><stop offset="1" stop-color="#b6becb"/></linearGradient></defs><path fill="url(#s)" d="M0 0h800v450H0z"/><circle cx="635" cy="80" r="28" fill="#f6e9ba"/><path d="M0 270 150 130 310 280 490 120 800 290v160H0" fill="#505d75"/><path d="M0 330 150 230 330 310 600 210 800 320v130H0" fill="#313e54"/><path d="M280 300v105h240V300L400 205Z" fill="#53637a"/><path d="m255 305 145-120 145 120" fill="none" stroke="#213145" stroke-width="22"/><path d="M330 320h45v55h-45zm95 0h45v55h-45z" fill="#efd29b"/><path d="M0 410h800v40H0" fill="#29374d"/></svg>');
const people=account=>['小林','阿澄','叶子','Moon'].map((name,i)=>({id:'usr_'+account+'_'+i,name:account==='B'?name+' B':name,
 state:i<2?'online':i===2?'active':'offline',online:i<3,web_online:i===2,
 location:i<2?'wrld_cabin:42~hidden(usr_owner)~region(jp)':i===2?'offline':'',
 world:i<2?'夜色小屋':'',world_id:i<2?'wrld_cabin':'',instance_label:'好友+',
 trust:{name:'用户',color:'#58728c'},status:'active',thumb:scene,online_since:Date.now()/1000-900}));
const baseTime=Date.UTC(2026,9,8,12,40)/1000;
const activity=account=>['online','location','offline','active','status','avatar'].map((event,i)=>({id:i+1,
 friend_id:'usr_'+account+'_'+(i%4),display_name:people(account)[i%4].name,event,ts:baseTime-i*430,
 world_name:'夜色小屋',location:event==='avatar'?scene:'wrld_cabin:42~hidden(usr_owner)~region(jp)',
 previous:event==='status'?'busy':'',status:'active',status_description:'今天一起看看星星',duration:i===2?0:null,prev_state:'online'}));
const profile=(id,account)=>({user:{id,displayName:people(account).find(f=>f.id===id)?.name||'合成好友',
 trust:{name:'用户',color:'#58728c'},languages:['zho'],bio:'很高兴认识你。一起探索新的世界。',bioLinks:[],
 state:'online',cur_state:'online',location:'wrld_cabin:42~hidden(usr_owner)~region(jp)',world_id:'wrld_cabin',
 world:'夜色小屋',world_thumb:scene,_avatar_fallback:scene,status:'active',isFriend:true,note:'',is_blocked:false,is_muted:false,
 online_since:baseTime-900,last_platform:'android'},events:activity(account),heat:[],groups:[],
 mutual:{counts:{friends:3,groups:1},friends:[]},worlds_created:[],avatars_created:[],
 loaded_sections:['profile'],profile_loaded:true,stale:false,raw:{id}});
const originalFetch=window.fetch;
fixture.delayWorld=0;
fixture.delayInstance=0;fixture.instanceResponses=0;
window.fetch=async(url,opts={})=>{
 let target=new URL(url,'http://fixture.local'),account='A';
 if(target.pathname==='/api/peer-relay'||target.pathname==='/api/peer-relay-post'){
  account='B';target=new URL(target.searchParams.get('path'),'http://fixture.local');
 }
 if(target.pathname==='/api/config'&&fixture.settingsUnavailable)return new Response(JSON.stringify({error:'合成设置加载失败'}),{status:503,headers:{'Content-Type':'application/json'}});
 let value;
 switch(target.pathname){
  case '/api/self':value={...me(account),thumb:scene};break;
  case '/api/group':value={group:{id:'grp_fixture',name:fixture.groupName||'合成群组',description:'合成描述'}};break;
  case '/api/image':value={src:'/media/'+(account==='B'?'peer/':'')+'a'.repeat(64)+'/'+'1'.repeat(64),cached:true};break;
  case '/api/friends':value={friends:people(account)};break;
  case '/api/feed':case '/api/history':value={events:activity(account)};break;
  case '/api/favgroups':value={type:'friend',groups:[{name:'friends1',displayName:'一起玩',visibility:'private'},{name:'friends2',displayName:'常联系',visibility:'private'}],items:[{group:'friends1',fid:'usr_'+account+'_0',name:'小林',fav_id:'fav_one'},{group:'friends2',fid:'usr_'+account+'_1',name:'阿澄',fav_id:'fav_two'}]};break;
  case '/api/notifications':value={items:[{id:'not_one',type:'friendRequest',sender:'合成好友',sender_id:'usr_'+account+'_0',message:'一起探索新的世界吧',created:'2026-10-08T12:00:00Z',seen:false}]};break;
  case '/api/friend':
   if(fixture.delayFriend)await new Promise(r=>setTimeout(r,fixture.delayFriend));
   value=profile(target.searchParams.get('id'),account);break;
  case '/api/friend-section':
   value=profile(target.searchParams.get('id'),account);value.loaded_sections.push(target.searchParams.get('part'));value.section_times={[target.searchParams.get('part')]:Date.now()/1000};break;
  case '/api/world':
   if(fixture.delayWorld)await new Promise(r=>setTimeout(r,fixture.delayWorld));
   value={world:{id:target.searchParams.get('id'),name:'夜色小屋',thumb:scene,image:scene,author:'合成作者',capacity:32,
    platforms:['standalonewindows','android'],visits:1234,favorites:88,tags:[],description:'安静的小屋与夜空',raw:{}},
    instances:[{num:'42',location:'wrld_cabin:42~hidden(usr_owner)~region(jp)',label:'好友+',region:'jp',count:null,friends_in:['小林','阿澄']}],
    pub_online:12,priv_online:null,visits_local:4,note:'',stale:false};break;
  case '/api/instance':
   if(fixture.delayInstance)await new Promise(r=>setTimeout(r,fixture.delayInstance));
   fixture.instanceResponses++;
   value={world:{id:'wrld_cabin',name:'夜色小屋',thumb:scene},instance_id:'42~hidden(usr_owner)~region(jp)',
    location:target.searchParams.get('location'),label:'好友+',live:{user_count:7,capacity:32,creator_id:'usr_owner'},friends_in:[{id:'usr_'+account+'_0',name:'小林'}],stale:false};break;
  default:return originalFetch(url,opts);
 }
 fixture.calls.push({path:target.pathname,query:target.search,account,method:opts.method||'GET',part:target.searchParams.get('part')});
 return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
};
"""


def html():
    content=(WEB/'templates/index.html').read_text().replace('__UI_VER__','fixture')
    content=re.sub(r'<link rel="stylesheet" href="/static/([^?]+)\?[^>]+>',lambda m:'<style>'+(WEB/'static'/m[1]).read_text()+'</style>',content)
    content=content.replace('<head>','<head><script>'+fixture.FIXTURE+EXTRA+'</script>',1)
    content=re.sub(r'<script defer src="/static/([^?]+)\?[^\"]+"></script>',lambda m:'<script>'+(WEB/'static'/m[1]).read_text()+'</script>',content)
    return content.encode()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    body=html()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/media/'):
                data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII=')
                self.send_response(200);self.send_header('Content-Type','image/png');self.end_headers();self.wfile.write(data);return
            self.send_response(200 if self.path=='/' else 204)
            self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
            if self.path=='/':self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results=[]
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for width,height,mobile in [(390,844,True),(320,740,True),(844,390,True),(1024,900,False),(1440,1000,False),(1920,1080,False)]:
                context=browser.new_context(viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile)
                page=context.new_page();page.set_default_timeout(12000);errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_timeout(250)
                assert not errors,errors
                page.evaluate('APP.scheduler.stop()')
                page.wait_for_selector('#feedTable tr',state='attached')
                # Exercise the real observer + native image HTTP path. The
                # browser must never request the VRChat/CDN source directly.
                external=[]
                page.on('request',lambda request:external.append(request.url) if request.url.startswith('https://assets.vrchat.com/') else None)
                page.evaluate("""()=>{
                    const box=document.createElement('div');box.id='mediaTest';box.style='position:fixed;top:0;left:0;width:24px;height:24px';
                    box.innerHTML='<img '+mediaAttrs('https://assets.vrchat.com/fixture.png','a')+'>';
                    document.body.appendChild(box);
                }""")
                page.wait_for_function("document.querySelector('#mediaTest img').naturalWidth>0")
                page.evaluate("IMAGES.setURL(document.querySelector('#mediaTest img'),'https://assets.vrchat.com/fixture-b.png','b')")
                page.wait_for_function("document.querySelector('#mediaTest img').getAttribute('src').startsWith('/media/peer/')&&document.querySelector('#mediaTest img').naturalWidth>0")
                assert not external,'browser-fetched-remote-photo'
                page.evaluate("document.getElementById('mediaTest').remove()")
                contrast=page.evaluate("""()=>{
                    const chip=document.querySelector('.chip.click'),css=getComputedStyle(chip);
                    const probe=document.createElement('span');probe.style.color='var(--dim)';document.body.appendChild(probe);
                    const dim=getComputedStyle(probe).color;probe.style.color='var(--accent)';
                    const accent=getComputedStyle(probe).color;probe.remove();
                    return css.color!==dim&&css.color!==css.backgroundColor&&css.backgroundColor!==accent;
                }""")
                assert contrast,'world-chip-foreground-and-background'
                print(f'Browser viewport {width}x{height}',flush=True)
                metrics={}
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'overflow {width}'
                if mobile:
                    assert page.locator('#mobileNav button').count()==5
                    assert page.evaluate("[...document.querySelectorAll('#mobileNav button')].every(b=>b.getBoundingClientRect().width>=44)")
                    page.screenshot(path=str(OUT/f'feed-{width}.png'))
                    page.locator('#mobileNav [data-mb=friendfeed]').click()
                    page.wait_for_selector('#mobileFeedFriendList [data-friend-id=usr_A_0]')
                    page.get_by_role('textbox',name='搜索好友列表').fill('小林')
                    assert page.locator('.feed-friend-option').count()==1
                    page.screenshot(path=str(OUT/f'friend-picker-{width}.png'))
                    page.locator('.feed-friend-option').click()
                    page.wait_for_function("FEED_FRIEND==='usr_A_0'&&document.querySelectorAll('#mobileFeed .timeline-card').length===2")
                    assert page.locator('#mobileTitle').inner_text()=='单人动态'
                    assert page.locator('#mobileNav [data-mb=friendfeed]').get_attribute('aria-current')=='page'
                    assert '小林' in page.locator('#mobileFeedSelection').inner_text()
                    assert page.evaluate("fixture.calls.some(c=>c.path==='/api/history'&&new URLSearchParams(c.query).get('friend_id')==='usr_A_0')")
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'single feed overflow {width}'
                    page.screenshot(path=str(OUT/f'single-feed-{width}.png'))
                    page.get_by_role('button',name='换一位',exact=True).click()
                    page.wait_for_selector('#mobileFeedFriendList [data-friend-id=usr_A_1]')
                    page.locator('#mobileFeedFriendList [data-friend-id=usr_A_1]').click()
                    page.wait_for_function("FEED_FRIEND==='usr_A_1'&&document.querySelectorAll('#mobileFeed .timeline-card').length===2")
                    page.get_by_role('button',name='全部动态',exact=True).click()
                    page.wait_for_function("FEED_FRIEND===''&&document.querySelectorAll('#mobileFeed .timeline-card').length===6")
                    assert page.locator('#mobileNav [data-mb=feed]').get_attribute('aria-current')=='page'
                    if width==390:
                        for account in ['b','m']:
                            page.evaluate(f"switchGA('{account}')")
                            page.locator('#mobileNav [data-mb=friendfeed]').click()
                            page.wait_for_selector('#mobileFeedFriendList [data-friend-id=usr_B_1]')
                            page.locator('#mobileFeedFriendList [data-friend-id=usr_B_1]').click()
                            page.wait_for_function("FEED_FRIEND==='usr_B_1'&&document.querySelectorAll('#mobileFeed .timeline-card').length===2")
                            assert '阿澄 B' in page.locator('#mobileFeedSelection').inner_text()
                            assert page.evaluate("[...document.querySelectorAll('#mobileFeed .timeline-person button')].every(b=>b.textContent==='阿澄 B')")
                            page.locator('#mobileNav [data-mb=feed]').click()
                        assert page.evaluate("fixture.calls.some(c=>c.path==='/api/history'&&c.account==='B'&&new URLSearchParams(c.query).get('friend_id')==='usr_B_1')")
                        page.evaluate("switchGA('a');loadFeed()")
                    metrics['single_friend_feed']=True
                    page.locator('#mobileNav [data-mb=locations]').click()
                    page.wait_for_selector('#locations .locgrid')
                    assert page.locator('#page-locations .page-heading h2').is_hidden()
                    assert page.locator('#locCount').is_visible()
                    # Opening shows existing user information before the delayed API.
                    page.evaluate('fixture.delayFriend=600')
                    immediate=page.evaluate("(()=>{const t=performance.now();openFriend('usr_A_0');return {elapsed:performance.now()-t,text:document.getElementById('mcard').textContent};})()")
                    assert immediate['elapsed']<150 and '小林' in immediate['text']
                    metrics['friend_shell_ms']=round(immediate['elapsed'],2)
                    page.wait_for_selector('#userRoom img')
                    page.wait_for_function('UD?.loaded_sections?.includes("info")')
                    page.wait_for_function("(()=>{const img=document.querySelector('.uavatar');return img?.complete&&img.naturalWidth>0&&getComputedStyle(img).display!=='none';})()")
                    assert page.evaluate("(()=>{const photo=document.querySelector('.uavatar');renderUserShell();return document.querySelector('.uavatar')===photo&&photo.naturalWidth>0;})()"),'decoded-photo-replaced-on-redraw'
                    # The profile omits avatar URLs: the list mirror must survive
                    # the profile AND info partition replacing the detail shell.
                    page.wait_for_timeout(1700)
                    assert page.evaluate("(()=>{const img=document.querySelector('.uavatar');return img?.naturalWidth>0&&getComputedStyle(img).display!=='none';})()"),'avatar-lost-after-profile'
                    assert page.locator('.ucard button').filter(has_text='屏蔽').first.is_enabled()
                    page.screenshot(path=str(OUT/f'friend-{width}.png'))
                    page.locator('#noteText').fill('未保存的测试备注')
                    page.evaluate("setUTab('activity');setUTab('info')")
                    assert page.locator('#noteText').input_value()=='未保存的测试备注'
                    page.evaluate('fixture.delayWorld=700')
                    immediate=page.evaluate("(()=>{const t=performance.now();openWorld('wrld_cabin');return {elapsed:performance.now()-t,text:document.getElementById('mcard').textContent};})()")
                    assert immediate['elapsed']<150 and '世界详情' in immediate['text']
                    metrics['world_shell_ms']=round(immediate['elapsed'],2)
                    page.wait_for_timeout(800)
                    assert '人数待查询' in page.locator('#mcard').inner_text()
                    page.screenshot(path=str(OUT/f'world-{width}.png'))
                    page.go_back();page.wait_for_selector('#noteText')
                    assert page.locator('#noteText').input_value()=='未保存的测试备注'
                    page.go_back();page.wait_for_function('document.getElementById("modal").classList.contains("hidden")')
                    # The account-required flow resolves to a real destination.
                    page.evaluate('switchGA("m")')
                    page.locator('#mobileNav [data-mb=favorites]').click()
                    page.wait_for_selector('.account-options')
                    page.locator('.account-option').first.click()
                    page.wait_for_function('CURPAGE==="favorites"')
                    page.wait_for_selector('#favGroups [data-group=friends2]')
                    page.locator('#favGroups [data-group=friends2]').click()
                    assert page.locator('#favItems').inner_text().find('阿澄')>=0
                    assert page.locator('#favSelName').inner_text()=='常联系'
                    page.screenshot(path=str(OUT/f'favorites-{width}.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'favorites overflow {width}'
                    page.locator('#mobileNav [data-mb=home]').click()
                    page.wait_for_selector('#mobileProfile .profile-summary')
                    page.locator('.home-actions button').last.click()
                    page.wait_for_selector('.menu-group')
                    assert page.locator('#moreSheet .sheet').is_visible()
                    page.locator('#moreSheet .sheet-heading button').click()
                    assert page.locator('#moreSheet').is_hidden()
                    page.evaluate("mobileGo('notifs')")
                    page.wait_for_selector('#mobileNotifs .notification-card')
                    page.locator('#mobileNotifs button').filter(has_text='已读').click()
                    assert page.evaluate("fixture.calls.some(c=>c.path==='/api/notification-act'&&c.method==='POST'&&c.account==='A')")
                    if width==390:
                        page.evaluate("switchGA('b');mobileGo('locations')")
                        page.wait_for_selector('#locations .locgrid')
                        page.evaluate("fixture.delayFriend=500;openFriend('usr_B_0')")
                        assert 'B' in page.locator('#mcard').inner_text()
                        page.evaluate("switchGA('a')")
                        page.wait_for_timeout(650)
                        assert page.locator('#modal').is_hidden()
                        assert not page.locator('#locations').inner_text().find('小林 B')>=0
                else:
                    assert page.locator('.side').is_visible() and page.locator('.mobile-header').is_hidden()
                    page.evaluate('loadSelf()')
                    page.wait_for_function("document.getElementById('selfThumb').naturalWidth>0")
                    assert page.locator('#selfThumb').get_attribute('data-media-priority')=='high'
                    metrics['account_header_photo_loaded']=True
                    safety=page.evaluate("""async()=>{
                        const name="');window.injected=1;//",groupName="x'));window.injected=1;//",calls=[],prompts=[];
                        const originalDelete=window.deleteFriend,originalConfirm=window.confirm;
                        try{
                            window._FLTB=[{id:'usr_fixture',name,trust:{},online:false}];renderFriendTable();
                            window.deleteFriend=(id,value)=>calls.push([id,value]);
                            document.querySelector('#fltBody [data-friend-id]').click();
                            fixture.groupName=groupName;await openGroup('grp_fixture');
                            window.confirm=text=>{prompts.push(text);return false;};
                            document.querySelector('#mcard [data-group-id]').click();
                            return {friend:calls[0]?.[0]==='usr_fixture'&&calls[0]?.[1]===name,
                                group:prompts[0]===`确认退出群组「${groupName}」？此操作同步到 VRChat。`,injected:!!window.injected};
                        }finally{window.deleteFriend=originalDelete;window.confirm=originalConfirm;fixture.groupName='';closeModal();}
                    }""")
                    assert safety=={'friend':True,'group':True,'injected':False},safety
                    metrics['untrusted_names_stay_data']=True
                    typography=page.evaluate("""()=>{
                        const table=document.querySelector('.feed-table'),row=table.querySelector('.feed-row');
                        const read=()=>({font:parseFloat(getComputedStyle(row).fontSize),height:row.getBoundingClientRect().height});
                        const after=read();table.classList.remove('feed-table');const before=read();table.classList.add('feed-table');
                        return {before,after};
                    }""")
                    assert typography['after']['font']>typography['before']['font'],typography
                    assert abs(typography['after']['height']-typography['before']['height'])<=.5,typography
                    metrics['feed_typography']=typography
                    page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
                # Settings child pages expose an actual return control on every
                # viewport, including native mobile back/forward history.
                page.evaluate("switchGA('a');switchPage('feed');switchPage('settings')")
                try:
                    page.wait_for_function('CFG!==null')
                except Exception:
                    print(page.evaluate("({page:CURPAGE,account:GA,active:APP.pages.active,running:!!APP.pages.running,error:document.getElementById('appError').textContent,status:document.getElementById('settingsLoadStatus').textContent,history:history.state})"),errors,flush=True)
                    raise
                for destination in ('login','extensions','netstats'):
                    page.locator(f"#page-settings button[onclick=\"switchPage('{destination}')\"]").click()
                    page.wait_for_function(f'CURPAGE==="{destination}"')
                    assert page.locator('#pageBack').inner_text()=='‹ 返回设置'
                    if mobile:
                        page.go_back();page.wait_for_function('CURPAGE==="settings"')
                        page.go_forward();page.wait_for_function(f'CURPAGE==="{destination}"')
                    page.locator('#pageBack').click()
                    page.wait_for_function('CURPAGE==="settings"')
                page.evaluate('fixture.settingsUnavailable=true;APP.client.invalidate("a");loadSettings(true)')
                page.wait_for_selector('#settingsLoadRetry:not(.hidden)')
                assert page.locator('#set-poll_seconds').is_disabled()
                assert page.locator('#pageBack').is_enabled()
                page.evaluate('fixture.settingsUnavailable=false')
                page.locator('#settingsLoadRetry').click()
                page.wait_for_function('CFG!==null&&!document.getElementById("set-poll_seconds").disabled')
                assert page.locator('#page-settings > .page-heading #pageBack').count()==1
                if mobile:
                    assert page.locator('#page-settings > .page-heading h2').is_hidden()
                    assert page.locator('#pageBack').bounding_box()['height']>=44
                else:
                    compact=page.evaluate("""()=>{
                        const heading=document.querySelector('#page-settings>.page-heading').getBoundingClientRect();
                        const title=document.querySelector('#page-settings>.page-heading h2').getBoundingClientRect();
                        const back=document.getElementById('pageBack').getBoundingClientRect();
                        const card=document.querySelector('#page-settings>.card').getBoundingClientRect();
                        return {header_to_content:card.top-heading.top,title_back_center:Math.abs((title.top+title.height/2)-(back.top+back.height/2))};
                    }""")
                    assert compact['header_to_content']<=80,compact
                    assert compact['title_back_center']<=1,compact
                    metrics['settings_compact_header']=compact
                assert '局域网访问' in page.locator('.access-help').inner_text()
                assert '互联网访问' in page.locator('.access-help').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'settings overflow {width}'
                page.screenshot(path=str(OUT/f'settings-{width}.png'),full_page=not mobile)
                metrics['settings_return_and_retry']=True
                # Use the shipped lifecycle with a native-shaped stalled source;
                # real timers verify timeout/fallback and source switches.
                page.evaluate("""()=>{
                    realtimeChannel.stop();fixture.sourceFactory=realtimeChannel.create;
                    realtimeChannel.timeout=50;
                    realtimeChannel.create=()=>({addEventListener(){},close(){this.closed=true;}});
                    realtimeChannel.start();
                }""")
                page.wait_for_function('ES_STATE==="failed"')
                assert '每 5 秒刷新' in page.locator('#esState').inner_text()
                page.evaluate("switchGA('b')")
                assert page.evaluate('!realtimeChannel.enabled&&realtimeChannel.source===null')
                page.evaluate("realtimeChannel.create=fixture.sourceFactory;realtimeChannel.timeout=8000;switchGA('a')")
                page.wait_for_function('ES_STATE==="connected"')
                metrics['stream_fallback_and_account_switch']=True
                # Click the real feed link: complete historical location survives,
                # and its world image appears while the room request is still slow.
                page.evaluate("fixture.delayWorld=0;fixture.delayFriend=0;fixture.delayInstance=1500;fixture.instanceResponses=0;APP.client.invalidate('a');switchGA('a');switchPage('feed');")
                page.evaluate('loadFeed()')
                page.wait_for_function("FEEDDATA.length>0&&FEEDDATA.every(e=>e._src==='a')")
                try:
                    page.wait_for_function('CURPAGE==="feed"&&!document.getElementById("page-feed").classList.contains("hidden")')
                except Exception:
                    print(page.evaluate("({page:CURPAGE,nav:APP.navigation.current,history:history.state})"),errors,flush=True)
                    raise
                if not mobile:
                    compact=page.evaluate("""()=>{
                        const box=id=>document.getElementById(id).getBoundingClientRect();
                        const search=box('feedSearch'),friend=box('feedFriendSel');
                        const toolbar=document.querySelector('.feed-toolbar').getBoundingClientRect();
                        const heading=document.querySelector('#page-feed>.page-heading').getBoundingClientRect();
                        const card=document.querySelector('#page-feed>.card').getBoundingClientRect();
                        return {toolbar_height:toolbar.height,search_friend_top:Math.abs(search.top-friend.top),header_to_content:card.top-heading.top};
                    }""")
                    assert compact['toolbar_height']<=80,compact
                    assert compact['search_friend_top']<=1,compact
                    assert compact['header_to_content']<=80,compact
                    assert page.locator('#feedSearch').count()==1
                    assert page.locator('#feedFilter [data-f]').count()==9
                    page.screenshot(path=str(OUT/f'compact-feed-{width}.png'))
                    metrics['feed_compact_controls']=compact
                page.locator('#mobileFeed .timeline-card .chip.click' if mobile else '#feedTable .chip.click').first.click()
                page.wait_for_function("DETAIL_CURRENT?.type==='instance'&&document.querySelector('#mcard .wthumb')?.naturalWidth>0")
                assert page.evaluate('fixture.instanceResponses===0'),'world-photo-waited-for-instance'
                assert page.evaluate("DETAIL_CURRENT.id==='wrld_cabin:42~hidden(usr_owner)~region(jp)'")
                assert page.evaluate("(()=>{const photo=document.querySelector('#mcard .wthumb');fixture.worldPhoto=photo;return photo.loading==='eager'&&photo.getAttribute('fetchpriority')==='high';})()")
                page.wait_for_function('fixture.instanceResponses>0')
                page.wait_for_timeout(100)
                assert page.evaluate("document.querySelector('#mcard .wthumb')===fixture.worldPhoto"),'world-photo-node-replaced'
                assert '房间建立者' in page.locator('#mcard').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'instance overflow {width}'
                page.screenshot(path=str(OUT/f'instance-{width}.png'))
                metrics['world_photo_before_instance']=True
                assert not errors,errors
                results.append({'viewport':[width,height],'mobile':mobile,'passed':True,'timings':metrics})
                context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
    sources=[WEB/'templates/index.html',*sorted((WEB/'static').rglob('*.js')),*sorted((WEB/'static').rglob('*.css'))]
    report={'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},'cases':results}
    (OUT/'browser-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(results))


if __name__=='__main__':main()
