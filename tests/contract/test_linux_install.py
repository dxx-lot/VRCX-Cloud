"""The Linux wizard preserves real application state and uses the normal CLI."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.application import launcher, linux_setup
from src.application.gateway import valid_password_record

PASSWORD = 'synthetic-wizard-password'


@pytest.fixture
def wizard(tmp_path, monkeypatch):
    project = tmp_path / 'source'
    project.mkdir()
    data = tmp_path / 'private'
    monkeypatch.setattr(linux_setup, 'PROJECT_ROOT', project)
    monkeypatch.setattr(launcher, 'default_data_dir', lambda: data)
    monkeypatch.setattr(sys, 'stdin', type('Terminal', (), {'isatty': lambda self: True})())
    monkeypatch.setattr(launcher.getpass, 'getpass', lambda *args: PASSWORD)
    return project, data


def answers(monkeypatch, *values):
    items = iter(values)
    monkeypatch.setattr('builtins.input', lambda *args: next(items))


def test_first_run_writes_private_settings_and_a_real_hashed_password(wizard, monkeypatch):
    project, data = wizard
    answers(monkeypatch, '2', '8081')
    path = project / '.vrcx-cloud/launch.json'
    values = linux_setup.configure(path)
    assert values['host'] == '0.0.0.0' and values['port'] == 8081 and values['data_dir'] == data
    assert json.loads(path.read_text())['data_dir'] == str(data)
    application = json.loads((data / 'application.json').read_text())
    assert valid_password_record(application['password'])
    assert PASSWORD not in (data / 'application.json').read_text()
    assert (data / 'accounts/a/config.json').is_file() and (data / 'accounts/b/config.json').is_file()
    if sys.platform != 'win32':
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_next_start_reuses_the_settings_password_and_normal_launcher(wizard, monkeypatch):
    project, data = wizard
    answers(monkeypatch, '', '')
    path = project / '.vrcx-cloud/launch.json'
    linux_setup.configure(path)
    before = (data / 'application.json').read_bytes()
    monkeypatch.setattr('builtins.input', lambda *args: pytest.fail('Configuration repeated'))
    monkeypatch.setattr(launcher.getpass, 'getpass', lambda *args: pytest.fail('Password reset'))
    calls = []
    monkeypatch.setattr(launcher, 'main', lambda args: calls.append(args) or 0)
    assert linux_setup.main([]) == 0
    assert calls == [['--config', str(path)]]
    assert (data / 'application.json').read_bytes() == before


def test_reconfigure_preserves_the_selected_data_directory_and_monitor_setting(wizard, monkeypatch):
    project, default = wizard
    custom = project.parent / 'existing-private'
    assert launcher.main(['--data-dir', str(custom), '--set-password']) == 0
    path = project / '.vrcx-cloud/launch.json'
    launcher.private_directory(path.parent)
    launcher.write_json(path, {'host': '0.0.0.0', 'port': 8123, 'data_dir': str(custom), 'monitor': False})
    before = (custom / 'application.json').read_bytes()
    monkeypatch.setattr(launcher.getpass, 'getpass', lambda *args: pytest.fail('Existing password reset'))
    answers(monkeypatch, '1', '')
    values = linux_setup.configure(path)
    assert values['data_dir'] == custom and values['port'] == 8123 and not values['monitor']
    assert values['host'] == '127.0.0.1'
    assert (custom / 'application.json').read_bytes() == before and not default.exists()


@pytest.mark.parametrize('choice,port', [('3', ''), ('1', '0'), ('2', '65536'), ('1', 'bad')])
def test_invalid_choices_do_not_create_data_or_save_configuration(wizard, monkeypatch, choice, port):
    project, data = wizard
    answers(monkeypatch, choice, port)
    with pytest.raises(ValueError):
        linux_setup.configure(project / '.vrcx-cloud/launch.json')
    assert not (project / '.vrcx-cloud').exists() and not data.exists()


def test_first_setup_needs_a_terminal_and_does_not_guess_passwords(wizard, monkeypatch):
    project, data = wizard
    monkeypatch.setattr(sys, 'stdin', type('Pipe', (), {'isatty': lambda self: False})())
    assert linux_setup.main([]) == 1
    assert not (project / '.vrcx-cloud').exists() and not data.exists()


def test_failed_password_confirmation_does_not_save_a_launch_configuration(wizard, monkeypatch):
    project, _ = wizard
    answers(monkeypatch, '', '')
    values = iter([PASSWORD, PASSWORD + '-different'])
    monkeypatch.setattr(launcher.getpass, 'getpass', lambda *args: next(values))
    assert linux_setup.main([]) == 1
    assert not (project / '.vrcx-cloud/launch.json').exists()


def test_linked_launch_directory_is_rejected_before_creating_private_state(wizard, monkeypatch):
    project, data = wizard
    outside = project.parent / 'outside'
    outside.mkdir()
    try:
        (project / '.vrcx-cloud').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('当前系统不支持创建测试软链')
    assert linux_setup.main([]) == 1
    assert not data.exists() and not list(outside.iterdir())


def test_check_is_read_only_before_first_setup(wizard):
    project, data = wizard
    assert linux_setup.main(['--check']) == 0
    assert not data.exists() and not (project / '.vrcx-cloud').exists()


def test_access_instructions_distinguish_localhost_and_lan(wizard, monkeypatch, capsys):
    _, data = wizard
    linux_setup.print_access({'host': '127.0.0.1', 'port': 8123, 'data_dir': data})
    text = capsys.readouterr().out
    assert 'http://127.0.0.1:8123/' in text and 'ssh -N -L 18080:127.0.0.1:8123' in text
    monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: '127.0.0.1 192.0.2.20\n')
    linux_setup.print_access({'host': '0.0.0.0', 'port': 8081, 'data_dir': data})
    text = capsys.readouterr().out
    assert 'http://192.0.2.20:8081/' in text and 'http://0.0.0.0' not in text
    assert 'Ctrl+C' in text and PASSWORD not in text


def test_shell_entrypoints_parse_and_explain_their_usage_without_installing():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('当前系统没有 Bash')
    for name in ('install-linux.sh', 'start-linux.sh'):
        path = ROOT / 'scripts' / name
        subprocess.run([bash, '-n', str(path)], check=True)
        result = subprocess.run([bash, str(path), '--help'], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0 and '用法' in result.stdout


@pytest.mark.skipif(sys.platform != 'linux', reason='需要实际 Linux 操作系统身份文件')
def test_bootstrap_refuses_to_overwrite_an_existing_directory(tmp_path):
    standalone = tmp_path / 'download/install-linux.sh'
    standalone.parent.mkdir()
    shutil.copyfile(ROOT / 'scripts/install-linux.sh', standalone)
    existing = tmp_path / 'existing'
    existing.mkdir()
    marker = existing / 'keep.txt'
    marker.write_text('unchanged')
    result = subprocess.run(['bash', str(standalone), '--dir', str(existing), '--no-start'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and '目录已存在' in result.stderr
    assert marker.read_text() == 'unchanged'
