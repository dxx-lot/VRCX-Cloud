"""Exercise one fresh Docker deployment with synthetic state in a unique project."""
import base64
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import pty
import select
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-docker-ci-password'


def main():
    project = 'vrcx-ci-' + uuid.uuid4().hex[:16]
    with tempfile.TemporaryDirectory(prefix='vrcx-docker-ci-') as temporary:
        directory = Path(temporary)
        source = directory / 'source'
        bootstrap = directory / 'deploy-docker.sh'
        shutil.copyfile(ROOT / 'scripts/deploy-docker.sh', bootstrap)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        command = ['bash', str(bootstrap), '--dir', str(source), '--project', project,
                   '--bind', '127.0.0.1', '--port', str(port)]
        compose_prefix = ['docker', 'compose', '--env-file', str(source / '.vrcx-cloud/docker.env'),
                          '--project-directory', str(source / 'server'), '-p', project,
                          '-f', str(source / 'server/compose.yaml')]
        env = dict(os.environ, VRCX_BIND_HOST='127.0.0.1', VRCX_PORT=str(port))
        def compose(*args):
            return subprocess.check_output([*compose_prefix, *args], env=env, text=True, stderr=subprocess.STDOUT).strip()
        def request(auth=False):
            connection = HTTPConnection('127.0.0.1', port, timeout=5)
            headers = {'Authorization': 'Basic ' + base64.b64encode(('vrcx:' + PASSWORD).encode()).decode()} if auth else {}
            try:
                connection.request('GET', '/', headers=headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        transcript = bytearray()
        process = None
        try:
            master, slave = pty.openpty()
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                       start_new_session=True, close_fds=True)
            os.close(slave)
            try:
                prompts = ['应用访问密码（至少 12 个字符）：'.encode(), '再输入一次：'.encode()]
                answered = 0
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], 0.5)
                    if ready:
                        try:
                            block = os.read(master, 65536)
                        except OSError:
                            block = b''
                        if block:
                            transcript.extend(block)
                            if answered < len(prompts) and prompts[answered] in transcript:
                                os.write(master, (PASSWORD + '\n').encode())
                                answered += 1
                    if process.poll() is not None:
                        break
                else:
                    raise AssertionError('Fresh Docker deployment timed out')
                assert process.wait(timeout=10) == 0, transcript.decode(errors='replace')[-10000:].replace(PASSWORD, '[synthetic-redacted]')
                assert answered == 2
            finally:
                os.close(master)
            source_sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            if os.environ.get('GITHUB_SHA'):
                assert source_sha == os.environ['GITHUB_SHA']
            assert request()[0] == 401
            assert request(True)[0] == 200
            container = compose('ps', '-q', 'app')
            inspection = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
            assert inspection['State']['Health']['Status'] == 'healthy'
            assert inspection['HostConfig']['ReadonlyRootfs']
            assert inspection['HostConfig']['PortBindings']['8080/tcp'] == [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]
            assert compose('exec', '-T', 'app', 'id', '-u') == '10001'
            compose('exec', '-T', 'app', 'python', '-c', 'from pathlib import Path; Path("/state/ci-preserve.txt").write_text("synthetic persistence marker")')
            fingerprint = compose('exec', '-T', 'app', 'python', '-c', 'import hashlib;from pathlib import Path;print(hashlib.sha256(Path("/state/application.json").read_bytes()).hexdigest())')
            again = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
            assert again.returncode == 0, (again.stdout + again.stderr).replace(PASSWORD, '[synthetic-redacted]')
            compose('restart', 'app')
            compose('up', '-d', '--wait', '--wait-timeout', '90', 'app')
            assert request(True)[0] == 200
            assert compose('exec', '-T', 'app', 'cat', '/state/ci-preserve.txt') == 'synthetic persistence marker'
            assert compose('exec', '-T', 'app', 'python', '-c', 'import hashlib;from pathlib import Path;print(hashlib.sha256(Path("/state/application.json").read_bytes()).hexdigest())') == fingerprint
            result = {'passed': True, 'source_commit': source_sha, 'fresh_bootstrap': True,
                      'real_password_prompt': True, 'anonymous_http': 401, 'authenticated_http': 200,
                      'nonroot_uid': 10001, 'readonly_root': True, 'loopback_only': True,
                      'repeat_deploy': True, 'password_preserved': True, 'restart_persistence': True,
                      'temporary_project': project}
            print(json.dumps(result))
            return 0
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            # Only this randomly named synthetic project is removed.
            if (source / '.vrcx-cloud/docker.env').is_file():
                subprocess.run([*compose_prefix, 'down', '--volumes'], env=env, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


if __name__ == '__main__':
    raise SystemExit(main())
