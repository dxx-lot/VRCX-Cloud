'F-02 凭据加密存储。\n\n上游：Windows DPAPI 静态加密（configRepository 透明解密，免密）。\nPi  ：Fernet 加密密钥库——\n  - 无主密码：随机密钥文件 key（0600）\n  - 有主密码：PBKDF2-SHA256(600k 迭代) 从主密码派生密钥（盐文件 salt，0600）\n行为等价：凭据永不落明文（契约测试强制）。'







import base64
import json
import os
import stat

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SecretStoreError(Exception):
    pass


class SecretStore:
    def __init__(self, dir_path, primary_password=None):
        self.dir = str(dir_path)
        os.makedirs(self.dir, exist_ok=True)
        self._key_file = os.path.join(self.dir, "key")
        self._salt_file = os.path.join(self.dir, "salt")
        self._data_file = os.path.join(self.dir, "credentials.json")
        self._fernet = self._make_fernet(primary_password)
        # 凭据惰性读取：每次 load 都从磁盘解密，保证篡改/换密钥立即被检测

    # ---------- 密钥 ----------
    def _write_private(self, path, data):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(path, 0o600)

    def _make_fernet(self, primary_password):
        if primary_password:
            salt_p = self._salt_file
            if not os.path.exists(salt_p):
                self._write_private(salt_p, os.urandom(16))
            salt = open(salt_p, "rb").read()
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                             iterations=600_000)
            key = base64.urlsafe_b64encode(kdf.derive(primary_password.encode("utf-8")))
        else:
            if not os.path.exists(self._key_file):
                self._write_private(self._key_file, Fernet.generate_key())
            key = open(self._key_file, "rb").read()
        return Fernet(key)

    # ---------- 数据 ----------
    def _load_data(self):
        if not os.path.exists(self._data_file):
            return {}
        try:
            blob = open(self._data_file, "rb").read()
            return json.loads(self._fernet.decrypt(blob).decode("utf-8"))
        except InvalidToken:
            raise SecretStoreError(
                "decrypt failed: 密钥库无法解密（主密码错误/密钥损坏/被篡改）")

    def _save_data(self):
        blob = self._fernet.encrypt(json.dumps(self._data).encode("utf-8"))
        self._write_private(self._data_file, blob)

    # ---------- 公开接口 ----------
    def put(self, user_id, secrets):
        self._data = self._load_data()
        self._data[user_id] = secrets
        self._save_data()

    def load(self, user_id):
        self._data = self._load_data()
        return self._data.get(user_id)

    def remove(self, user_id):
        self._data = self._load_data()
        if user_id in self._data:
            del self._data[user_id]
            self._save_data()
