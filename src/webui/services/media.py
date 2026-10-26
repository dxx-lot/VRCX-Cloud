"""Bounded instance-local raster cache. Tickets never contain cookies or source URLs."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests
from services.session import SingleFlight

HOSTS = {'api.vrchat.cloud', 'files.vrchat.cloud', 'd348imysud55la.cloudfront.net', 'assets.vrchat.com'}
MEDIA_PATH = re.compile(r'^/media/([a-f0-9]{64})/([a-f0-9]{64})$')


def validate_url(url):
    value = urlsplit(url)
    if value.scheme != 'https' or value.hostname not in HOSTS or value.username or value.password or value.port not in (None, 443):
        raise ValueError('不支持的图片地址')
    if value.hostname == 'api.vrchat.cloud' and not value.path.startswith(('/api/1/file/', '/api/1/image/')):
        raise ValueError('不支持的图片地址')
    if value.fragment:
        raise ValueError('不支持的图片地址')
    return url


def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    raise ValueError('图片内容无效')


class NoPasswordAuth(requests.auth.AuthBase):
    def __call__(self, request):
        request.headers.pop('Authorization', None)
        return request


class MediaCache:
    def __init__(self, root, max_file=4*1024*1024, max_bytes=64*1024*1024, max_files=512):
        self.root = Path(root)
        self.max_file, self.max_bytes, self.max_files = max_file, max_bytes, max_files
        self.secret = secrets.token_bytes(32)
        self.flights = SingleFlight()
        self.capacity = threading.BoundedSemaphore(4)
        self.lock = threading.RLock()
        self.failures = {}

    def _key(self, scope, url):
        return hashlib.sha256((scope + '\0' + url).encode()).hexdigest()

    def _ticket(self, scope, key):
        return hmac.new(self.secret, (scope + '\0' + key).encode(), hashlib.sha256).hexdigest()

    def _read(self, key):
        if self.root.is_symlink(): return None
        path = self.root / key
        if path.is_symlink() or not path.is_file(): return None
        try:
            if path.stat().st_size > self.max_file: return None
            data = path.read_bytes()
            kind = image_type(data)
            os.utime(path, None)
            return data, kind
        except (OSError, ValueError):
            return None

    def read(self, scope, path):
        match = MEDIA_PATH.fullmatch(path)
        if not match: return None
        ticket, key = match.groups()
        if not hmac.compare_digest(ticket, self._ticket(scope, key)): return None
        with self.lock:
            return self._read(key)

    def _download(self, url, session):
        for _ in range(4):
            validate_url(url)
            with session.get(url, stream=True, allow_redirects=False, timeout=(4, 8), auth=NoPasswordAuth()) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                if response.status_code != 200: raise ValueError('图片暂不可用')
                size = int(response.headers.get('Content-Length') or 0)
                if size > self.max_file: raise ValueError('图片过大')
                chunks, size = [], 0
                for block in response.iter_content(64*1024):
                    size += len(block)
                    if size > self.max_file: raise ValueError('图片过大')
                    chunks.append(block)
                data = b''.join(chunks)
                image_type(data)
                return data
        raise ValueError('图片跳转过多')

    def get(self, scope, url, session_factory):
        validate_url(url)
        key = self._key(scope, url)
        with self.lock:
            hit = self._read(key)
        cached = hit is not None
        def work():
            with self.lock:
                if self._read(key) is not None: return
                if time.monotonic() - self.failures.get(key, -1000) < 60:
                    raise ValueError('图片暂不可用')
            if not self.capacity.acquire(blocking=False): raise ValueError('图片加载繁忙，请稍后重试')
            temporary = None
            try:
                with session_factory() as session:
                    data = self._download(url, session)
                with self.lock:
                    if self.root.is_symlink(): raise ValueError('图片缓存目录无效')
                    self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                    os.chmod(self.root, 0o700)
                    with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as output:
                        temporary = Path(output.name)
                        output.write(data);output.flush();os.fsync(output.fileno())
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, self.root / key)
                    temporary = None
                    entries = sorted((p for p in self.root.iterdir() if re.fullmatch(r'[a-f0-9]{64}', p.name) and p.is_file() and not p.is_symlink()), key=lambda p:p.stat().st_mtime, reverse=True)
                    total = 0
                    for index, entry in enumerate(entries):
                        total += entry.stat().st_size
                        if index >= self.max_files or total > self.max_bytes: entry.unlink(missing_ok=True)
            except (ValueError, OSError, requests.RequestException):
                with self.lock:
                    self.failures[key] = time.monotonic()
                    while len(self.failures) > 512: self.failures.pop(next(iter(self.failures)))
                raise
            finally:
                if temporary is not None: temporary.unlink(missing_ok=True)
                self.capacity.release()
        if not cached: self.flights.run(key, work)
        return {'src': '/media/' + self._ticket(scope, key) + '/' + key, 'cached': cached}
