"""旧引擎的窄适配边界：每个账号在自己的进程中导入会话模块。"""
import contextlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import stat
import sys
import threading
import time


def saved_session_available(state):
    path=Path(state)/'auth-ui.json'
    try:
        if path.is_symlink() or path.stat().st_nlink!=1: return False
        value=json.loads(path.read_text(encoding='utf-8'))
        cookies=value.get('cookies') if isinstance(value,dict) else None
        return isinstance(cookies,dict) and isinstance(cookies.get('auth'),str) and bool(cookies['auth'].strip())
    except (OSError,ValueError):
        return False


def await_saved_session(state):
    if saved_session_available(state): return
    print('未登录，等待用户在账号页面登录。',flush=True)
    while not saved_session_available(state): time.sleep(1)


def run_worker(runtime, state, token_file, kind, listener=None):
    # The parent never imports the engine's global account state.
    parent = multiprocessing.parent_process()
    if parent is not None:
        def stop_with_parent():
            parent.join()
            os._exit(1)
        threading.Thread(target=stop_with_parent, daemon=True).start()
    os.environ['VRCX_PI_STATE_DIR'] = state
    os.environ['VRCX_PI_ACCESS_TOKEN_FILE'] = token_file
    os.environ.pop('VRCX_PI_MONITOR_PAUSE_FILE', None)
    if os.name != 'nt':
        os.umask(0o077)
    sys.path.insert(0, runtime)
    log_path = Path(state) / (kind+'.log')
    if log_path.is_symlink():
        raise ValueError('日志文件不能是符号链接')
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(log_path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError('日志文件必须是独立的普通文件')
    with os.fdopen(fd, 'a', encoding='utf-8', buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                if kind == 'monitor':
                    # The legacy engine starts its WS thread before checking auth.
                    # Keep a fresh/invalid local account entirely offline here.
                    await_saved_session(state)
                    sys.argv = [str(Path(runtime)/'vrc_watch.py'), 'run']
                    runpy.run_path(sys.argv[0], run_name='__main__')
                    return
                from http.server import ThreadingHTTPServer
                web = importlib.import_module('web')
                web.init_db()
                proxy = (web.load_config().get('proxy') or '').strip()
                web.vrc_watch.PROXIES = {'http': proxy, 'https': proxy} if proxy else None
                threading.Thread(target=web._net_sampler, daemon=True).start()
                server = ThreadingHTTPServer(listener.getsockname(), web.Handler, bind_and_activate=False)
                server.socket.close()
                server.socket = listener
                server.server_address = listener.getsockname()
                server.daemon_threads = True
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
            except KeyboardInterrupt:
                pass
            except Exception:
                import traceback
                traceback.print_exc()
                raise SystemExit(1)
