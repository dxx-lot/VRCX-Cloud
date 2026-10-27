"""Probe the public manifest without consuming authentication failure attempts."""
import json
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def healthy(url='http://127.0.0.1:8080/manifest.webmanifest'):
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
            payload = json.loads(response.read(65536))
            return (response.status == 200 and isinstance(payload, dict)
                    and payload.get('start_url') == '/' and payload.get('display') == 'standalone'
                    and isinstance(payload.get('icons'), list) and bool(payload['icons']))
    except (OSError, URLError, ValueError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if healthy() else 1)
