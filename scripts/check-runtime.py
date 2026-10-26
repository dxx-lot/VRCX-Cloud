#!/usr/bin/env python3
"""验证服务器入口：空白账号、HTTP 入口、内部鉴权、数据隔离与停止清理。"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import queue
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener


def check(command):
    with tempfile.TemporaryDirectory(prefix='vrcx-release-check-') as folder:
        state=Path(folder)/'state'
        result=subprocess.run([*command,'--check','--data-dir',str(state)],capture_output=True,
                              text=True,encoding='utf-8',timeout=30)
        if result.returncode or state.exists():
            raise RuntimeError('发行程序只读检查失败：'+result.stderr)
        process=subprocess.Popen([*command,'--data-dir',str(state),'--port','0'],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        lines=queue.Queue()
        def read_lines():
            for line in process.stdout: lines.put(line)
            lines.put(None)
        reader=threading.Thread(target=read_lines,daemon=True);reader.start()
        addresses=[]
        opener=build_opener(ProxyHandler({}))
        try:
            try: line=lines.get(timeout=45)
            except queue.Empty: line=None
            if not line or 'http://' not in line:
                process.terminate();process.wait(timeout=15)
                logs='\n'.join(p.read_text(encoding='utf-8') for p in state.glob('accounts/*/*.log'))
                raise RuntimeError('发行程序启动失败：'+process.stderr.read()+'\n'+logs)
            base='http://'+line.strip().split('http://',1)[1]
            deadline=time.monotonic()+10
            while True:
                monitors=[state/'accounts'/account/'monitor.log' for account in ('a','b')]
                if all(path.is_file() and '未登录，等待' in path.read_text(encoding='utf-8') for path in monitors): break
                if process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('发行程序的空白账号监控启动失败')
                time.sleep(.05)
            if b'app-access-managed' not in opener.open(base,timeout=5).read():
                raise RuntimeError('网页入口未通过应用网关')
            for account in ('a','b'):
                path=state/'accounts'/account
                cfg=json.loads((path/'config.json').read_text(encoding='utf-8'))
                addresses.append(('127.0.0.1',cfg['web_port']))
                try: opener.open('http://127.0.0.1:'+str(cfg['web_port'])+'/api/status',timeout=3)
                except HTTPError as error:
                    if error.code!=401: raise
                else: raise RuntimeError('账号内部端口没有访问保护')
                with closing(sqlite3.connect(path/'vrc_watch.db')) as db:
                    db.execute('INSERT INTO events(friend_id,display_name,event,ts) VALUES(?,?,?,?)',
                               ('usr_'+account,'synthetic '+account,'online',time.time()))
                    db.commit()
            for account,prefix in [('a','api/feed'),('b','api/peer-relay?path=%2Fapi%2Ffeed')]:
                data=json.load(opener.open(base+prefix,timeout=5))
                if {row['friend_id'] for row in data['events']}!={'usr_'+account}:
                    raise RuntimeError('发行程序账号数据隔离失败')
        finally:
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
            reader.join(2);process.stdout.close();process.stderr.close()
            deadline=time.monotonic()+8
            for address in addresses:
                while True:
                    with socket.socket() as probe: closed=probe.connect_ex(address)!=0
                    if closed or time.monotonic()>deadline: break
                    time.sleep(.05)
                if not closed: raise RuntimeError('停止发行程序后账号端口仍在运行')
    return {'read_only_check':True,'gateway_http':True,'monitor_without_login':True,'internal_auth':True,'account_isolation':True,'shutdown':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable',type=Path)
    args=parser.parse_args()
    print(json.dumps(check([str(args.executable.absolute())]),indent=2))
