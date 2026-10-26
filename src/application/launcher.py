"""跨平台启动器：一个访问地址、两个隔离账号、应用私有数据目录。"""
import argparse
from contextlib import contextmanager
import getpass
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener

from .gateway import Gateway, password_record, valid_password_record
from .worker import run_worker

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(sys._MEIPASS)/'runtime' if getattr(sys, 'frozen', False) else ROOT/'src'/'webui'
ACCOUNTS = ('a', 'b')


def default_data_dir():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'VRCX Cloud'
    if sys.platform == 'darwin':
        return Path.home()/'Library'/'Application Support'/'VRCX Cloud'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local'/'share')/'vrcx-cloud'


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('应用数据目录不能是符号链接')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ValueError('应用数据路径不是目录')
    if os.name != 'nt':
        path.chmod(0o700)


def regular_file(path):
    if path.is_symlink():
        raise ValueError('应用状态文件不能是符号链接')
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('应用状态文件必须是独立的普通文件')


def read_json(path):
    regular_file(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('配置文件必须是 JSON 对象')
    return value


def write_private(path, data):
    regular_file(path)
    fd, temporary = tempfile.mkstemp(prefix='.app-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    write_private(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())


@contextmanager
def state_lock(root):
    path = root/'application.lock'
    regular_file(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if not os.fstat(fd).st_size:
                    os.write(fd, b'0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('这个数据目录已有应用在运行') from None
        yield
    finally:
        os.close(fd)


def ensure_state_root(root):
    if root.is_symlink():
        raise ValueError('应用数据目录不能是符号链接')
    if root.exists() and not (root/'application.json').exists() and any(path.name != 'application.lock' for path in root.iterdir()):
        raise ValueError('请选择空目录，或已由本应用初始化的数据目录')
    private_directory(root)


def prepare_state(root):
    marker = root/'application.json'
    ensure_state_root(root)
    if not marker.exists():
        write_json(marker, {'schema': 1, 'password': None})
    app = read_json(marker)
    if app.get('schema') != 1 or (app.get('password') is not None and not valid_password_record(app['password'])):
        raise ValueError('应用配置格式无效')
    for account in ACCOUNTS:
        folder = root/'accounts'/account
        private_directory(root/'accounts')
        private_directory(folder)
        config = folder/'config.json'
        if not config.exists():
            write_json(config, {'poll_seconds': 30, 'proxy': '', 'push_enabled': False,
                                'watch_favorites': False, 'user_agent': 'VRCX-Cloud/1.0.0 (unofficial self-hosted client)',
                                'bark': {'enabled': False}, 'telegram': {'enabled': False}})
    return app


def bind_listener(host, port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((host, port))
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise


def configure_accounts(root, listeners):
    for account in ACCOUNTS:
        config_path = root/'accounts'/account/'config.json'
        config = read_json(config_path)
        peer = 'b' if account == 'a' else 'a'
        config.update(web_bind='127.0.0.1', web_port=listeners[account].getsockname()[1],
                      peer_url='http://127.0.0.1:'+str(listeners[peer].getsockname()[1]))
        write_json(config_path, config)


def wait_for_workers(workers, listeners, timeout=20):
    opener = build_opener(ProxyHandler({}))
    pending = set(ACCOUNTS)
    deadline = time.monotonic()+timeout
    while pending and time.monotonic() < deadline:
        if any(not process.is_alive() for process in workers):
            raise RuntimeError('账号服务启动失败，请查看数据目录中的日志')
        for account in list(pending):
            try:
                with opener.open('http://127.0.0.1:'+str(listeners[account].getsockname()[1])+'/healthz', timeout=0.3) as response:
                    if response.status == 200 and json.load(response).get('status') == 'ok':
                        pending.remove(account)
            except (OSError, ValueError):
                pass
        if pending:
            time.sleep(0.1)
    if pending:
        raise RuntimeError('账号服务启动超时，请查看数据目录中的日志')


def serve(settings, app):
    root = settings['data_dir']
    if settings['host'] not in ('127.0.0.1', 'localhost') and not app.get('password'):
        raise ValueError('局域网访问需要先运行 --set-password 设置应用访问密码')
    token = secrets.token_urlsafe(48)
    token_file = root/'gateway.token'
    write_private(token_file, token.encode())
    listeners, processes, gateway, thread = {}, [], None, None
    stop = threading.Event()
    old_signals = {}
    try:
        listeners['public'] = bind_listener(settings['host'], settings['port'])
        for account in ACCOUNTS:
            listeners[account] = bind_listener('127.0.0.1', 0)
        configure_accounts(root, listeners)
        context = multiprocessing.get_context('spawn')
        for account in ACCOUNTS:
            process = context.Process(target=run_worker, args=(str(RUNTIME), str(root/'accounts'/account),
                                      str(token_file), 'web', listeners[account]), name='account-'+account+'-web')
            process.start()
            processes.append(process)
        wait_for_workers(processes, listeners)
        if settings['monitor']:
            for account in ACCOUNTS:
                process = context.Process(target=run_worker, args=(str(RUNTIME), str(root/'accounts'/account),
                                          str(token_file), 'monitor'), name='account-'+account+'-monitor')
                process.start()
                processes.append(process)
        gateway = Gateway(listeners['public'], listeners['a'].getsockname(), token, app.get('password'))
        thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_signals[sig] = signal.signal(sig, lambda *_: stop.set())
        host = '127.0.0.1' if settings['host'] == '0.0.0.0' else settings['host']
        print('VRCX Cloud 已启动：http://'+host+':'+str(listeners['public'].getsockname()[1])+'/', flush=True)
        print('账号A / 账号B 已就绪；按 Ctrl+C 停止应用。', flush=True)
        if app.get('password'):
            print('浏览器访问用户名：vrcx；密码为你设置的应用访问密码。', flush=True)
        while not stop.wait(0.3):
            if any(not process.is_alive() for process in processes):
                raise RuntimeError('账号服务已退出，应用已停止，请查看数据目录中的日志')
    finally:
        for sig, previous in old_signals.items():
            signal.signal(sig, previous)
        if gateway and thread:
            gateway.shutdown()
            thread.join(2)
            gateway.server_close()
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(2)
            process.close()
        for listener in listeners.values():
            listener.close()


def settings_from(args):
    values = {'host': '127.0.0.1', 'port': 8080, 'monitor': True, 'data_dir': str(default_data_dir())}
    if args.config:
        values_from_file = read_json(args.config)
        if set(values_from_file)-set(values):
            raise ValueError('应用配置包含不支持的选项')
        values.update(values_from_file)
    for key in values:
        option = getattr(args, key)
        if option is not None:
            values[key] = option
    if values['host'] not in ('127.0.0.1', 'localhost', '0.0.0.0'):
        raise ValueError('监听地址支持 127.0.0.1、localhost 或 0.0.0.0')
    if type(values['port']) is not int or not 0 <= values['port'] <= 65535 or type(values['monitor']) is not bool:
        raise ValueError('端口或监控配置无效')
    if not isinstance(values['data_dir'], (str, Path)):
        raise ValueError('数据目录配置无效')
    values['data_dir'] = Path(values['data_dir']).expanduser().absolute()
    return values


def main(argv=None):
    # Windows pipes otherwise use the system code page and can fail on Chinese.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='VRCX Cloud：一个地址管理两个隔离的 VRChat 账号。')
    parser.add_argument('--config', type=Path, help='可选的应用配置 JSON')
    parser.add_argument('--data-dir', type=Path, help='私有数据目录，默认使用系统应用数据目录')
    parser.add_argument('--host', help='默认 127.0.0.1；局域网访问可设为 0.0.0.0')
    parser.add_argument('--port', type=int, help='浏览器入口端口，默认 8080')
    parser.add_argument('--without-monitor', dest='monitor', action='store_false', default=None, help='只启动网页，暂停好友采集')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--init', action='store_true', help='初始化私有数据目录后退出')
    actions.add_argument('--check', action='store_true', help='只检查配置和依赖，不启动服务或修改数据')
    actions.add_argument('--set-password', action='store_true', help='交互设置应用访问密码，不保存明文')
    args = parser.parse_args(argv)
    try:
        settings = settings_from(args)
        if args.check:
            required = ('web.py', 'vrc_watch.py', 'services/routes.py', 'templates/index.html', 'static/core/runtime.js')
            if any(not (RUNTIME/name).is_file() for name in required):
                raise ValueError('运行源码不完整，请使用完整源码包')
            missing = [name for name in ('requests', 'websocket', 'cryptography', 'socks', 'python_socks') if importlib.util.find_spec(name) is None]
            if missing:
                raise ValueError('缺少运行依赖，请先安装 requirements.txt')
            if settings['host'] == '0.0.0.0':
                marker = settings['data_dir']/'application.json'
                if not marker.is_file() or not valid_password_record(read_json(marker).get('password')):
                    raise ValueError('局域网访问需要先运行 --set-password 设置应用访问密码')
            print('配置与依赖检查通过。数据目录：'+str(settings['data_dir']))
            return 0
        ensure_state_root(settings['data_dir'])
        with state_lock(settings['data_dir']):
            app = prepare_state(settings['data_dir'])
            if args.set_password:
                password = getpass.getpass('应用访问密码（至少 12 个字符）：')
                if password != getpass.getpass('再输入一次：'):
                    raise ValueError('两次输入的密码不同')
                app['password'] = password_record(password)
                write_json(settings['data_dir']/'application.json', app)
                print('应用访问密码已更新，明文密码未保存。')
            elif args.init:
                print('数据目录已初始化：'+str(settings['data_dir']))
            else:
                serve(settings, app)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print('无法启动：'+str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
