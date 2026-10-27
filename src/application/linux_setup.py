"""Interactive first-run setup for the Linux source installation."""
import argparse
import ipaddress
from pathlib import Path
import subprocess
import sys

from . import launcher
from .gateway import valid_password_record

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def settings(path):
    args = argparse.Namespace(config=path, host=None, port=None, monitor=None, data_dir=None)
    return launcher.settings_from(args)


def ensure_password(data_dir):
    marker = data_dir / 'application.json'
    if marker.exists() or marker.is_symlink():
        application = launcher.read_json(marker)
        if valid_password_record(application.get('password')):
            return
    print('\n请设置网页的应用访问密码，至少 12 个字符；它与 VRChat 密码不同。')
    if launcher.main(['--data-dir', str(data_dir), '--set-password']) != 0:
        raise ValueError('访问密码尚未设置，程序未启动；请重新运行启动命令。')


def configure(path):
    if not sys.stdin.isatty():
        raise ValueError('首次配置需要交互式终端，请登录服务器后运行启动命令。')
    if path.parent.is_symlink():
        raise ValueError('启动配置目录不能是符号链接。')
    old = settings(path) if path.exists() or path.is_symlink() else None
    default_choice = '2' if old and old['host'] == '0.0.0.0' else '1'
    default_port = old['port'] if old else 8080
    print('\n选择访问方式：\n  1. 本机或云服务器（默认，仅监听本机）\n  2. 家中局域网（同一网络的手机、电脑访问）')
    choice = input(f'输入 1 或 2 [{default_choice}]：').strip() or default_choice
    if choice not in ('1', '2'):
        raise ValueError('请选择 1 或 2，配置未保存。')
    port_text = input(f'网页端口 [{default_port}]：').strip() or str(default_port)
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError('端口须为 1 到 65535 的整数，配置未保存。') from None
    if not 1 <= port <= 65535:
        raise ValueError('端口须为 1 到 65535 的整数，配置未保存。')
    data_dir = old['data_dir'] if old else launcher.default_data_dir().expanduser().absolute()
    ensure_password(data_dir)
    values = {'host': '0.0.0.0' if choice == '2' else '127.0.0.1',
              'port': port, 'data_dir': str(data_dir), 'monitor': old['monitor'] if old else True}
    launcher.private_directory(path.parent)
    launcher.write_json(path, values)
    return settings(path)


def print_access(values):
    port = values['port']
    print('\n网页用户名：vrcx；密码：你设置的应用访问密码。')
    print('打开网页后，进入“账号”页登录 VRChat。')
    print('私有数据目录：' + str(values['data_dir']))
    if values['host'] == '0.0.0.0':
        addresses = []
        try:
            output = subprocess.check_output(['hostname', '-I'], text=True, stderr=subprocess.DEVNULL)
            for word in output.split():
                address = ipaddress.ip_address(word)
                if address.version == 4 and not address.is_loopback:
                    addresses.append(str(address))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        for address in addresses:
            print(f'局域网访问地址：http://{address}:{port}/')
        if not addresses:
            print(f'局域网访问地址：http://服务器局域网IP:{port}/')
        print('手机须连接同一局域网；互联网访问请配置 HTTPS 入口。')
    else:
        print(f'同一台电脑打开：http://127.0.0.1:{port}/')
        print('云服务器：在你自己的电脑另开终端，替换下面的登录用户名和服务器地址：')
        print(f'  ssh -N -L 18080:127.0.0.1:{port} 登录用户名@服务器地址')
        print('保持该终端打开，然后在自己电脑浏览器访问：http://127.0.0.1:18080/')
        print('手机直接通过互联网访问时，按 server/README.md 配置 HTTPS 入口。')
    print('本次为前台运行；按 Ctrl+C 或关闭运行终端会停止程序。')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Linux 首次启动与访问向导')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--configure', action='store_true', help='重新选择访问方式和端口')
    actions.add_argument('--check', action='store_true', help='只检查配置与依赖，不启动程序')
    actions.add_argument('--set-password', action='store_true', help='重新设置应用访问密码')
    options = parser.parse_args(argv)
    path = PROJECT_ROOT / '.vrcx-cloud' / 'launch.json'
    try:
        existing = ['--config', str(path)] if path.exists() or path.is_symlink() else []
        if options.check:
            return launcher.main([*existing, '--check'])
        if options.set_password:
            return launcher.main([*existing, '--set-password'])
        values = configure(path) if options.configure or not existing else settings(path)
        ensure_password(values['data_dir'])
        print_access(values)
        return launcher.main(['--config', str(path)])
    except (OSError, ValueError, RuntimeError, EOFError) as error:
        print('无法完成启动向导：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
