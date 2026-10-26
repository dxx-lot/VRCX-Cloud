"F-02 凭据加密存储 · 契约测试\n\n对照上游：VRCX 将保存的凭据存于本地（configRepository 'savedCredentials'，\nWindows 侧经 DPAPI 静态加密——src/stores/auth.js:126 getAllSavedCredentials）。\n\n硬规则（主提示词 §十）：VRChat 密码不得明文落盘；0600 只是最低要求不是许可。"







import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from secret_store import SecretStore, SecretStoreError


def store(tmp_path, primary=None):
    return SecretStore(dir_path=tmp_path / "keystore", primary_password=primary)


def test_roundtrip(tmp_path):
    s = store(tmp_path)
    s.put("usr_x", {"username": "user@test.com", "password": "S3cret!",
                    "totp_secret": "JBSWY3DPEHPK3PXP"})
    got = s.load("usr_x")
    assert got["password"] == "S3cret!" and got["totp_secret"] == "JBSWY3DPEHPK3PXP"


def test_no_plaintext_on_disk(tmp_path):
    s = store(tmp_path)
    s.put("usr_x", {"username": "user@test.com", "password": "S3cret!"})
    blob = b"".join(p.read_bytes() for p in (tmp_path / "keystore").iterdir())
    assert b"user@test.com" not in blob
    assert b"S3cret!" not in blob


def test_key_file_permissions_0600(tmp_path):
    s = store(tmp_path)
    s.put("usr_x", {"username": "u", "password": "p"})
    keyfile = tmp_path / "keystore" / "key"
    assert (stat.S_IMODE(keyfile.stat().st_mode) & 0o077) == 0  # 组/其他无任何权限


def test_primary_password_required(tmp_path):
    s1 = store(tmp_path, primary="correct horse")
    s1.put("usr_x", {"username": "u", "password": "p"})
    # 主密码错误 → 明确错误，而不是抛裸异常或返回空
    s2 = store(tmp_path, primary="wrong")
    with pytest.raises(SecretStoreError) as e:
        s2.load("usr_x")
    assert "primary" in str(e.value).lower() or "decrypt" in str(e.value).lower()


def test_missing_entry_is_distinct(tmp_path):
    s = store(tmp_path)
    assert s.load("usr_nobody") is None


def test_remove(tmp_path):
    s = store(tmp_path)
    s.put("usr_x", {"username": "u", "password": "p"})
    s.remove("usr_x")
    assert s.load("usr_x") is None


def test_tampered_ciphertext_detected(tmp_path):
    s = store(tmp_path)
    s.put("usr_x", {"username": "u", "password": "p"})
    datafile = tmp_path / "keystore" / "credentials.json"
    data = datafile.read_bytes()
    datafile.write_bytes(data[:-4] + b"AAAA")
    with pytest.raises(SecretStoreError):
        s.load("usr_x")
