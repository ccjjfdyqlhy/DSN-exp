# DSN-exp/crypto_utils.py
# 数据库消息加密 — AES-256-GCM + SHA-256 密钥派生
# 主密钥持久化于 /.dsn/ : secret.key (密文) + keystore (解密用密钥)

import os
import stat
import hashlib
import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CryptoUtils")

_ENCRYPTION_MARKER = b"\x01"      # 前缀标记：0x01=已加密，无前缀=明文
_DSN_DIR_NAME = ".dsn"
_SECRET_FILE = "secret.key"         # 加密后的主密钥
_KEYSTORE_FILE = "keystore"         # 用于解密 secret.key 的 KEK


class MessageCipher:
    """
    消息加解密器。

    主密钥持久化:  /.dsn/keystore (32B random KEK) + /.dsn/secret.key (AES-GCM 加密的主密钥)
    用户密钥派生:  SHA-256(master_key || ":" || user_id)
    消息加密算法:  AES-256-GCM (12-byte nonce, 16-byte auth tag)
    存储格式:      base64( 0x01 || nonce[12] || ciphertext+tag )
    """

    def __init__(self):
        self._dsn_dir = self._resolve_dsn_dir()
        self._master_key = self._load_or_create_master_key()

    # ---- 主密钥生命周期 ----

    @staticmethod
    def _resolve_dsn_dir() -> Path:
        """定位 /.dsn 目录：优先当前工作目录，回退到本文件所在目录"""
        cwd = Path.cwd() / _DSN_DIR_NAME
        if cwd.exists():
            return cwd
        return Path(__file__).resolve().parent / _DSN_DIR_NAME

    def _load_or_create_master_key(self) -> bytes:
        self._dsn_dir.mkdir(mode=0o700, exist_ok=True)
        _secure_chmod(self._dsn_dir)
        secret_path = self._dsn_dir / _SECRET_FILE
        keystore_path = self._dsn_dir / _KEYSTORE_FILE

        if secret_path.exists() and keystore_path.exists():
            return self._load_master_key(keystore_path, secret_path)
        else:
            return self._create_master_key(keystore_path, secret_path)

    def _load_master_key(self, keystore_path: Path, secret_path: Path) -> bytes:
        try:
            keystore = keystore_path.read_bytes()
            secret_b64 = secret_path.read_text().strip()
            secret_ct = base64.b64decode(secret_b64)
            master_key = _aes_gcm_decrypt(keystore, secret_ct)
            if not master_key or len(master_key) != 32:
                raise ValueError("解密后主密钥长度异常")
            logger.info("已从 %s 加载主密钥", self._dsn_dir)
            return master_key
        except (PermissionError, OSError) as e:
            logger.warning("无法读取主密钥文件 (%s)，旧密钥文件已备份", e)
            self._backup_corrupted_keys(keystore_path, secret_path)
            logger.warning("已将损坏/不可访问的密钥文件移至 .bak，将创建新密钥。旧加密数据将无法解密！")
            return self._create_master_key(keystore_path, secret_path)
        except Exception as e:
            logger.error("加载主密钥失败: %s", e)
            self._backup_corrupted_keys(keystore_path, secret_path)
            logger.error("已将损坏的密钥文件移至 .bak，将创建新密钥。旧加密数据将无法解密！")
            return self._create_master_key(keystore_path, secret_path)

    @staticmethod
    def _backup_corrupted_keys(keystore_path: Path, secret_path: Path) -> None:
        import shutil
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for f in [keystore_path, secret_path]:
            if f.exists():
                bak = f.with_suffix(f.suffix + f".corrupted_{ts}.bak")
                shutil.copy2(str(f), str(bak))
                logger.warning("已备份损坏密钥文件: %s → %s", f, bak)

    def _create_master_key(self, keystore_path: Path, secret_path: Path) -> bytes:
        keystore = os.urandom(32)
        master_key = os.urandom(32)

        secret_ct = _aes_gcm_encrypt(keystore, master_key)
        secret_b64 = base64.b64encode(secret_ct).decode("ascii")

        keystore_path.write_bytes(keystore)
        _secure_chmod(keystore_path)
        secret_path.write_text(secret_b64)
        _secure_chmod(secret_path)

        logger.info("已创建新的主密钥 → %s", self._dsn_dir)
        return master_key

    # ---- 用户密钥派生 ----

    def derive_key(self, user_id: int) -> bytes:
        """为指定用户派生 32 字节 AES-256 密钥"""
        material = self._master_key + f":{user_id}".encode("utf-8")
        return hashlib.sha256(material).digest()

    # ---- 消息加密 ----

    def encrypt(self, user_id: int, plaintext: str) -> str:
        """
        加密消息文本，返回 base64 字符串。

        :param user_id:  用户 ID，用于派生密钥
        :param plaintext: 明文消息
        :return:          base64 编码的密文
        """
        if not plaintext:
            return plaintext

        try:
            key = self.derive_key(user_id)
            ct = _aes_gcm_encrypt(key, plaintext.encode("utf-8"))
            encrypted = _ENCRYPTION_MARKER + ct
            return base64.b64encode(encrypted).decode("ascii")
        except ImportError:
            logger.warning("cryptography 库未安装，消息将以明文存储")
            return plaintext
        except Exception as e:
            logger.error("消息加密失败 (uid=%d): %s", user_id, e)
            return plaintext

    # ---- 消息解密 ----

    def decrypt(self, user_id: int, ciphertext_b64: str) -> str:
        """
        解密消息文本。

        :param user_id:       用户 ID
        :param ciphertext_b64: base64 密文字符串（可能为明文）
        :return:              明文消息
        """
        if not ciphertext_b64:
            return ciphertext_b64

        try:
            raw = base64.b64decode(ciphertext_b64)
        except Exception:
            return ciphertext_b64  # 非 base64，视为明文

        if not raw.startswith(_ENCRYPTION_MARKER):
            return ciphertext_b64  # 无标记，旧明文数据

        try:
            key = self.derive_key(user_id)
            return _aes_gcm_decrypt(key, raw[1:]).decode("utf-8")
        except ImportError:
            logger.warning("cryptography 库未安装，无法解密")
            return ciphertext_b64
        except Exception as e:
            logger.error("消息解密失败 (uid=%d): %s", user_id, e)
            return ciphertext_b64


# ---- 底层 AES-256-GCM (nonce[12] + ciphertext+tag) ----

def _aes_gcm_encrypt(key: bytes, plaintext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def _aes_gcm_decrypt(key: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    nonce = data[:12]
    ct = data[12:]
    return aesgcm.decrypt(nonce, ct, None)


def _secure_chmod(path: Path) -> None:
    """将文件/目录权限设为仅 owner 可访问，目录额外保留执行位"""
    try:
        if path.is_dir():
            os.chmod(path, stat.S_IRWXU)  # 0700
        else:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)  # 0600
    except Exception:
        pass
