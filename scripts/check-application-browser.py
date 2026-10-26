#!/usr/bin/env python3
"""在全新临时状态中验证统一入口、访问认证和无登录信息的交互。"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.application.launcher import prepare_state, write_json
from src.application.gateway import password_record


def check():
    output = ROOT/'artifacts/acceptance/open-source'
    output.mkdir(parents=True, exist_ok=True)
    python = ROOT/('.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python')
    if not python.is_file(): python = Path(sys.executable)
    with tempfile.TemporaryDirectory(prefix='vrcx-app-browser-') as temporary:
        state = Path(temporary)/'state'
        config = prepare_state(state)
        password = 'synthetic-browser-access-123'
        config['password'] = password_record(password)
        write_json(state/'application.json', config)
        process = subprocess.Popen([str(python), '-B', str(ROOT/'run.py'), '--data-dir', str(state), '--port', '0', '--without-monitor'],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines = queue.Queue()
        threading.Thread(target=lambda:[lines.put(line) for line in process.stdout], daemon=True).start()
        try:
            line = lines.get(timeout=25)
            assert '已启动' in line, line
            base = 'http://'+line.strip().split('http://', 1)[1]
            paths = []
            with sync_playwright() as automation:
                browser = automation.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width':1440, 'height':1000},
                                              http_credentials={'username':'vrcx', 'password':password})
                page = context.new_page()
                page.route('**/api/vrc-status', lambda route:route.fulfill(content_type='application/json', body='{}'))
                page.on('request', lambda request:paths.append(urlsplit(request.url).path))
                page.goto(base, wait_until='domcontentloaded')
                page.wait_for_function("document.getElementById('sideState').textContent==='登录异常'")
                assert page.locator('#gswitch [data-g=a]').inner_text() == '账号A'
                assert page.locator('#gswitch [data-g=b]').inner_text() == '账号B'
                assert page.locator('#selfName').inner_text() == '账号A'
                assert '/api/self' not in paths
                page.locator('#selfCard').click()
                page.locator('#loginBtn').wait_for(state='visible')
                page.wait_for_function("document.getElementById('acctSelf').textContent.includes('登录异常')")
                assert '登录异常' in page.locator('#acctSelf').inner_text()
                assert not page.locator('#loginBtn').is_disabled()
                page.screenshot(path=str(output/'empty-account-desktop.png'))
                page.locator('#gswitch [data-g=b]').click()
                page.locator('#p_loginBtn').wait_for(state='visible')
                page.wait_for_function("document.getElementById('acctPeer').textContent.includes('登录异常')")
                assert '登录异常' in page.locator('#acctPeer').inner_text()
                assert not any(text in page.locator('body').inner_text() for text in ('8000', '8001', password))
                page.locator('#gswitch [data-g=m]').click()
                assert not page.locator('#sideSettings').is_visible()
                assert page.locator('#nav [data-dash]').count() == 0
                page.set_viewport_size({'width':390, 'height':844})
                page.screenshot(path=str(output/'empty-account-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert page.locator('meta[name="app-access-managed"]').count() == 1
                context.close();browser.close()
            result={'passed':True, 'authenticated_entry':True, 'empty_names':['账号A','账号B'],
                    'empty_login_label':'登录异常', 'empty_primary_skips_profile_request':True,
                    'merged_settings_hidden':True, 'merged_dashboard_hidden':True, 'real_vrchat_login':False}
            (output/'browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False))
        finally:
            process.terminate()
            try: process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=3)
            process.stdout.close();process.stderr.close()


if __name__ == '__main__':
    check()
