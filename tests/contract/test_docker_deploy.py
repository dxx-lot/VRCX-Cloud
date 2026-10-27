"""Docker CLI orchestration boundaries plus real local HTTP health responses."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / 'source with spaces'
    (source / 'scripts').mkdir(parents=True)
    (source / 'server').mkdir()
    shutil.copyfile(ROOT / 'scripts/deploy-docker.sh', source / 'scripts/deploy-docker.sh')
    shutil.copyfile(ROOT / 'run.py', source / 'run.py')
    template = ROOT / 'public/server/compose.yaml' if (ROOT / 'public').is_dir() else ROOT / 'server/compose.yaml'
    shutil.copyfile(template, source / 'server/compose.yaml')
    commands = tmp_path / 'commands.jsonl'
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    docker = binaries / 'docker'
    docker.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
args=sys.argv[1:]
with open(os.environ['DOCKER_TEST_LOG'],'a') as log:log.write(json.dumps(args)+'\\n')
if args==['info'] or args==['compose','version']:sys.exit(0)
if args==['compose','up','--help']:print('--wait --wait-timeout');sys.exit(0)
if args and args[0]=='ps':print('abc123' if os.environ.get('DOCKER_TEST_OWNER') else '');sys.exit(0)
if args and args[0]=='inspect':print(os.environ['DOCKER_TEST_OWNER']);sys.exit(0)
if args[:2]==['volume','inspect']:sys.exit(int(os.environ.get('DOCKER_TEST_VOLUME_MISSING','1')))
if args and args[0]=='compose':
    if 'build' in args:sys.exit(int(os.environ.get('DOCKER_TEST_BUILD_FAIL','0')))
    if 'run' in args and '--entrypoint' in args:sys.exit(int(os.environ.get('DOCKER_TEST_PASSWORD_STATUS','0')))
    if 'up' in args:sys.exit(int(os.environ.get('DOCKER_TEST_UP_FAIL','0')))
    sys.exit(0)
sys.exit(2)
''')
    docker.chmod(0o755)
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'], DOCKER_TEST_LOG=str(commands))
    def run(*args, **values):
        return subprocess.run(['bash', str(source / 'scripts/deploy-docker.sh'), *args],
                              env=dict(env, **values), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
    def log():
        return [json.loads(line) for line in commands.read_text().splitlines()] if commands.exists() else []
    return source, run, log


def test_deploy_uses_isolated_configuration_and_waits_for_health(deployment):
    source, run, log = deployment
    result = run('--bind', '127.0.0.1', '--port', '18080', '--project', 'test-cloud')
    assert result.returncode == 0, result.stderr
    config = source / '.vrcx-cloud/docker.env'
    assert config.read_text() == 'VRCX_BIND_HOST=127.0.0.1\nVRCX_PORT=18080\nVRCX_PROJECT=test-cloud\n'
    calls = log()
    assert any(call[-2:] == ['build', 'app'] for call in calls)
    assert any('--wait' in call and call[-1] == 'app' for call in calls)
    assert not any('--set-password' in call for call in calls)
    assert not any('down' in call or 'prune' in call or '--volumes' in call for call in calls)
    if os.name != 'nt':
        assert config.stat().st_mode & 0o777 == 0o600
    assert '关闭终端不会停止' in result.stdout and 'http://127.0.0.1:18080/' in result.stdout


@pytest.mark.parametrize('args', [('--bind', 'bad'), ('--port', '0'), ('--port', '70000'), ('--project', '../other')])
def test_invalid_settings_do_not_build_or_create_configuration(deployment, args):
    source, run, log = deployment
    result = run(*args)
    assert result.returncode != 0
    assert not (source / '.vrcx-cloud').exists()
    assert not any('build' in call or ('up' in call and '--help' not in call) for call in log())


def test_an_existing_project_from_another_directory_is_untouched(deployment):
    source, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_OWNER='/synthetic/other-project')
    assert result.returncode != 0 and '其他目录' in result.stderr
    assert not any('build' in call or 'stop' in call or ('up' in call and '--help' not in call) for call in log())
    assert not (source / '.vrcx-cloud').exists()


def test_unregistered_volume_is_not_adopted(deployment):
    source, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_VOLUME_MISSING='0')
    assert result.returncode != 0 and '同名数据卷' in result.stderr
    assert not any('build' in call or 'run' in call for call in log())


def test_corrupt_password_check_never_resets_password_or_starts(deployment):
    _, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_PASSWORD_STATUS='1')
    assert result.returncode != 0 and '未改动密码' in result.stderr
    assert not any('--set-password' in call or ('up' in call and '--help' not in call) for call in log())


def test_first_password_setup_refuses_a_noninteractive_terminal(deployment):
    _, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_PASSWORD_STATUS='3')
    assert result.returncode != 0 and '交互式终端' in result.stderr
    assert not any('--set-password' in call or ('up' in call and '--help' not in call) for call in log())


def test_configuration_is_parsed_as_data_and_not_sourced(deployment, tmp_path):
    source, run, log = deployment
    config_dir = source / '.vrcx-cloud'
    config_dir.mkdir()
    sentinel = tmp_path / 'must-not-exist'
    (config_dir / 'docker.env').write_text('VRCX_BIND_HOST=127.0.0.1\nVRCX_PORT=8080\nVRCX_PROJECT=$(touch ' + str(sentinel) + ')\n')
    result = run()
    assert result.returncode != 0 and not sentinel.exists()
    assert not any('build' in call for call in log())


def test_stop_and_status_reuse_settings_and_keep_data(deployment):
    source, run, log = deployment
    assert run('--bind', '127.0.0.1', '--port', '18080').returncode == 0
    config = source / '.vrcx-cloud/docker.env'
    before = config.read_bytes()
    assert run('--status').returncode == 0
    assert run('--stop').returncode == 0
    assert config.read_bytes() == before
    assert any(call[-2:] == ['stop', 'app'] for call in log())
    assert not any('down' in call or '--volumes' in call for call in log())
    assert run('--project', 'different').returncode != 0


@pytest.mark.parametrize('kind', ['symbolic', 'hard'])
def test_linked_configuration_is_rejected_without_touching_its_target(deployment, tmp_path, kind):
    source, run, log = deployment
    config_dir = source / '.vrcx-cloud'
    config_dir.mkdir()
    outside = tmp_path / 'outside.env'
    outside.write_text('VRCX_BIND_HOST=127.0.0.1\nVRCX_PORT=8080\nVRCX_PROJECT=test-cloud\n')
    before = outside.read_bytes()
    try:
        if kind == 'symbolic':
            (config_dir / 'docker.env').symlink_to(outside)
        else:
            os.link(outside, config_dir / 'docker.env')
    except OSError:
        pytest.skip('当前系统不支持创建所需测试链接')
    assert run().returncode != 0
    assert outside.read_bytes() == before
    assert not any('build' in call for call in log())


def test_build_failure_does_not_continue_to_password_or_start(deployment):
    _, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_BUILD_FAIL='1')
    assert result.returncode != 0 and '部署完成' not in result.stdout
    assert not any('run' in call or ('up' in call and '--help' not in call) for call in log())


def test_failed_health_wait_is_not_reported_as_success(deployment):
    _, run, log = deployment
    result = run('--bind', '127.0.0.1', DOCKER_TEST_UP_FAIL='1')
    assert result.returncode != 0 and '部署完成' not in result.stdout
    assert not any('down' in call or '--volumes' in call for call in log())


@pytest.mark.parametrize('status,valid,expected', [(200, True, True), (401, True, False), (503, True, False), (200, False, False)])
def test_container_health_uses_a_real_local_http_response(status, valid, expected):
    health_path = ROOT / 'public/server/healthcheck.py' if (ROOT / 'public').is_dir() else ROOT / 'server/healthcheck.py'
    spec = importlib.util.spec_from_file_location('docker_health', health_path)
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            body = json.dumps({'start_url': '/', 'display': 'standalone', 'icons': [{'src': '/icon.png'}]} if valid else {}).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert health.healthy('http://127.0.0.1:' + str(server.server_address[1]) + '/') is expected
    finally:
        server.shutdown(); server.server_close(); thread.join(3)
