"""固定上游的浏览器网关；认证信息只在本机进程之间传递。"""
import base64
import hashlib
import hmac
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

MAX_BODY = 5 * 1024 * 1024
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade'}
ASSETS = Path(__file__).parent/'assets'
PUBLIC_ICONS = {'/icon-192.png': ('icon-192.png', 'image/png'),
                '/icon-512.png': ('icon-512.png', 'image/png'), '/icon.svg': ('icon.svg', 'image/svg+xml')}


def password_record(password):
    if len(password) < 12:
        raise ValueError('访问密码至少需要 12 个字符')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return {'algorithm': 'pbkdf2-sha256', 'iterations': 600000,
            'salt': salt.hex(), 'digest': digest.hex()}


def valid_password_record(record):
    try:
        return (record['algorithm'] == 'pbkdf2-sha256' and record['iterations'] == 600000
                and len(bytes.fromhex(record['salt'])) == 16
                and len(bytes.fromhex(record['digest'])) == 32)
    except (KeyError, TypeError, ValueError):
        return False


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, listener, upstream, token, password=None):
        super().__init__(listener.getsockname(), GatewayHandler, bind_and_activate=False)
        self.socket.close()
        self.socket = listener
        self.server_address = listener.getsockname()
        self.upstream, self.token, self.password = upstream, token, password
        self.failures, self.failures_lock = {}, threading.Lock()
        self.auth_cache = {}
        self.hash_slots = threading.BoundedSemaphore(4)
        self.request_slots = threading.BoundedSemaphore(32)

    def process_request(self, request, address):
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.request_slots.release()

    def check_access(self, address, authorization):
        if not self.password:
            return 200
        now = time.monotonic()
        cache_key = hmac.new(self.token.encode(), authorization.encode(), hashlib.sha256).digest()
        with self.failures_lock:
            self.failures = {key: value for key, value in self.failures.items() if now-value[1] < 60}
            if self.failures.get(address, (0, 0))[0] >= 5:
                return 429
            if self.auth_cache.get(cache_key, 0) > now:
                return 200
        valid = False
        if authorization.startswith('Basic ') and len(authorization) < 2048:
            try:
                user, password = base64.b64decode(authorization[6:], validate=True).decode('utf-8').split(':', 1)
                record = self.password
                if not self.hash_slots.acquire(blocking=False):
                    return 429
                try:
                    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), record['iterations'])
                finally:
                    self.hash_slots.release()
                valid = hmac.compare_digest(user.encode(), b'vrcx') and hmac.compare_digest(digest.hex(), record['digest'])
            except (ValueError, UnicodeError):
                pass
        with self.failures_lock:
            if valid:
                self.failures.pop(address, None)
                self.auth_cache = {key: expires for key, expires in self.auth_cache.items() if expires > now}
                if len(self.auth_cache) >= 128:
                    self.auth_cache.pop(next(iter(self.auth_cache)))
                self.auth_cache[cache_key] = now+300
                return 200
            if len(self.failures) >= 256 and address not in self.failures:
                self.failures.pop(next(iter(self.failures)))
            count = self.failures.get(address, (0, now))[0]
            self.failures[address] = (count+1, now)
        return 401


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'VRCX-Cloud'
    timeout = 60

    def log_message(self, *_):
        # Browser URLs, headers and credentials are deliberately not logged.
        pass

    def reply(self, status, message, challenge=False):
        body = json.dumps({'error': message}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if challenge:
            self.send_header('WWW-Authenticate', 'Basic realm="VRCX Cloud", charset="UTF-8"')
        if status == 429:
            self.send_header('Retry-After', '60')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def public_asset(self, path):
        if path in PUBLIC_ICONS:
            filename, content_type = PUBLIC_ICONS[path]
            data = (ASSETS/filename).read_bytes()
        elif path == '/manifest.webmanifest':
            content_type = 'application/manifest+json'
            data = json.dumps({'name':'VRCX Cloud', 'short_name':'VRCX Cloud', 'start_url':'/', 'scope':'/',
                               'display':'standalone', 'background_color':'#eef0f4', 'theme_color':'#6d5ef0',
                               'icons':[{'src':'/icon-'+str(size)+'.png','sizes':str(size)+'x'+str(size),'type':'image/png'}
                                        for size in (192,512)]}).encode()
        else:
            return False
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers();self.wfile.write(data)
        return True

    def forward(self):
        try:
            target = urlsplit(self.path)
        except ValueError:
            return self.reply(400, '请求地址无效')
        if target.scheme or target.netloc or not self.path.startswith('/') or self.path.startswith('//'):
            return self.reply(400, '请求地址无效')
        if len(self.headers.get_all('Host', [])) != 1:
            return self.reply(400, '请求地址无效')
        host = self.headers.get('Host', '')
        try:
            authority = urlsplit('http://'+host)
            hostname = authority.hostname
            authority.port
        except ValueError:
            return self.reply(400, '请求地址无效')
        if not hostname or any(c in host for c in ('/', '\\', '@')):
            return self.reply(400, '请求地址无效')
        # Prevent a DNS-rebinding page from reading an unprotected local app.
        if not self.server.password and hostname not in ('localhost', '127.0.0.1'):
            return self.reply(403, '请通过本机地址访问')
        if self.command == 'GET' and self.public_asset(target.path):
            return
        access = self.server.check_access(self.client_address[0], self.headers.get('Authorization', ''))
        if access != 200:
            return self.reply(access, '需要应用访问密码' if access == 401 else '尝试过于频繁，请稍后重试', access == 401)
        if self.command == 'POST':
            origin = self.headers.get('Origin')
            try:
                origin_ok = not origin or (urlsplit(origin).scheme in ('http', 'https') and urlsplit(origin).netloc == host)
            except ValueError:
                origin_ok = False
            if not origin_ok or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply(403, '不允许跨站操作')
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) > 1:
            return self.reply(400, '请求长度无效')
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            return self.reply(400, '请求长度无效')
        if not 0 <= length <= MAX_BODY:
            return self.reply(413, '请求内容过大')
        body = self.rfile.read(length) if length else None
        if body is not None and len(body) != length:
            return self.reply(400, '请求内容不完整')
        if self.command == 'POST' and target.path == '/api/config-set':
            try:
                payload = json.loads(body or b'{}')
            except (ValueError, UnicodeError):
                return self.reply(400, '请求内容无效')
            if isinstance(payload, dict) and 'web_password' in payload:
                return self.reply(400, '访问密码由应用统一管理')
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in HOP_HEADERS | {'authorization', 'cookie', 'x-web-token', 'accept-encoding', 'content-length'}}
        headers.update({'X-Web-Token': self.server.token, 'Accept-Encoding': 'identity'})
        upstream = HTTPConnection(*self.server.upstream, timeout=60)
        started = False
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            if response.status == 401:
                return self.reply(503, '账号服务暂不可用')
            html = None
            if target.path == '/' and response.status == 200 and 'text/html' in (response.getheader('Content-Type') or ''):
                html = response.read(2 * 1024 * 1024)
                html = html.replace(b'</head>', b'<meta name="app-access-managed" content="true"></head>', 1)
            self.send_response(response.status)
            started = True
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS | {'server', 'date'} and not (html is not None and key.lower() == 'content-length'):
                    self.send_header(key, value)
            if html is not None:
                self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            if html is not None:
                self.wfile.write(html)
            else:
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, ValueError, HTTPException):
            if not started:
                self.reply(502, '账号服务暂不可用，请重新启动应用')
        finally:
            upstream.close()
