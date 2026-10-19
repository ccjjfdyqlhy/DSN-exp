# apps/dsn_ui/credentials.py
"""dsn_ui 凭据加密 —— 基于 Fernet 的静态加密与主密钥管理。

## 为什么需要

apps/dsn_ui/api_providers.py 过去把第三方 API 的 api_key **明文**写进
apps/dsn_ui/data/api_providers.json。任何能读到该文件的人（备份、日志打包、
误提交、同机其它用户）都直接拿到可用密钥。本模块提供"静态加密"：

  * 落盘时加密（encrypt_str），内存中仍是明文（引擎需要明文才能调用远端 API）；
  * 读取时透明解密（decrypt_str），旧版明文数据原样透传，平滑升级。

## 主密钥解析顺序

  1. 环境变量 DSN_UI_SECRET_KEY（Fernet 密钥，base64 44 字符 / 32 字节）；
  2. 密钥文件 apps/dsn_ui/data/.secret_key（首次使用时生成，权限 0600）；
  3. 两者都不可用时抛出带中文提示的错误。

**绝不**记录密钥或明文；日志里只出现文件路径。

## 密文格式

    enc:v1:<fernet-token>

带版本前缀是为了将来更换算法时仍能识别旧密文。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("DSNUIProviders")

#: 密文版本前缀（便于将来平滑更换算法）
PREFIX = "enc:v1:"

#: 环境变量名：直接提供 Fernet 主密钥
ENV_KEY_NAME = "DSN_UI_SECRET_KEY"


class CredentialError(RuntimeError):
    """凭据加密/解密相关的可操作错误（已是中文提示）。"""


def is_encrypted(value: object) -> bool:
    """判断某个值是否已是本模块产出的密文。"""
    return isinstance(value, str) and value.startswith(PREFIX)


def _import_fernet():
    """延迟导入 cryptography.fernet。

    延迟导入的原因与仓库其它模块一致：避免在"根本没用到凭据"的场景
    （CLI、纯本地 llama.cpp 部署）也付出导入成本。
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as e:  # pragma: no cover - 依赖缺失时的可操作提示
        raise CredentialError(
            "缺少 cryptography 依赖，无法加密保存 API 凭据。"
            "请执行 pip install cryptography（或安装本项目的 full 可选依赖）。"
        ) from e
    return Fernet, InvalidToken


def _default_data_dir() -> Path:
    """dsn_ui 自有数据目录。"""
    from apps.dsn_ui.config import UIConfig

    return Path(UIConfig.DATA_DIR)


def _read_env_key() -> Optional[bytes]:
    """读取并校验环境变量里的主密钥。"""
    raw = (os.getenv(ENV_KEY_NAME) or "").strip()
    if not raw:
        return None
    key = raw.encode("utf-8")
    Fernet, _ = _import_fernet()
    try:
        Fernet(key)
    except Exception as e:  # noqa: BLE001
        raise CredentialError(
            f"环境变量 {ENV_KEY_NAME} 不是合法的 Fernet 密钥"
            "（应为 base64 编码的 32 字节）。可用以下命令生成：\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from e
    return key


def _write_key_file(key_file: Path, key: bytes) -> None:
    """以 0600 权限写入密钥文件。"""
    key_file.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):  # pragma: no cover - Windows
        flags |= os.O_BINARY
    fd = os.open(str(key_file), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    finally:
        # 某些 umask 会让 0600 变成更宽的权限，显式收紧
        try:
            os.chmod(key_file, 0o600)
        except OSError:  # pragma: no cover - 极端文件系统
            pass


def load_or_create_master_key(data_dir: Optional[Path] = None) -> bytes:
    """解析主密钥：环境变量 -> 密钥文件 -> 首次生成。

    返回 32 字节 Fernet 密钥（base64 形式）。绝不记录密钥本身。
    """
    env_key = _read_env_key()
    if env_key is not None:
        logger.debug("使用环境变量 %s 提供的凭据主密钥", ENV_KEY_NAME)
        return env_key

    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    key_file = data_dir / ".secret_key"

    if key_file.exists():
        key = key_file.read_bytes().strip()
        Fernet, _ = _import_fernet()
        try:
            Fernet(key)
        except Exception as e:  # noqa: BLE001
            raise CredentialError(
                f"凭据主密钥文件已损坏或格式非法: {key_file}。"
                "请删除该文件以重新生成（注意：已加密的凭据将无法解密），"
                f"或改用环境变量 {ENV_KEY_NAME} 提供原密钥。"
            ) from e
        return key

    Fernet, _ = _import_fernet()
    key = Fernet.generate_key()
    try:
        _write_key_file(key_file, key)
    except OSError as e:
        raise CredentialError(
            f"无法写入凭据主密钥文件 {key_file}: {e}。"
            f"请检查目录权限，或改用环境变量 {ENV_KEY_NAME} 提供密钥。"
        ) from e
    logger.warning(
        "已生成新的 dsn_ui 凭据主密钥: %s（权限 0600）。"
        "请妥善备份：丢失后已保存的第三方 API Key 将无法解密。",
        key_file,
    )
    return key


class CredentialCipher:
    """Fernet 加解密器（可显式注入密钥，便于测试）。"""

    def __init__(self, key: Optional[bytes] = None, data_dir: Optional[Path] = None):
        Fernet, self._invalid_token = _import_fernet()
        self.key = key if key is not None else load_or_create_master_key(data_dir)
        self._fernet = Fernet(self.key)

    # ── 字符串 ──

    def encrypt_str(self, plaintext: object) -> str:
        """加密字符串。

        * 空值 / None 原样返回空串（不产出"空密文"）；
        * 已是密文则原样返回（幂等，避免双重加密）。
        """
        if plaintext is None:
            return ""
        if isinstance(plaintext, bytes):
            plaintext = plaintext.decode("utf-8", errors="replace")
        text = str(plaintext)
        if not text:
            return ""
        if is_encrypted(text):
            return text
        token = self._fernet.encrypt(text.encode("utf-8")).decode("ascii")
        return PREFIX + token

    def decrypt_str(self, value: object) -> str:
        """解密字符串。

        * 非密文（旧版明文 / 空值）原样返回 —— 保证旧安装无缝升级；
        * 密文但解不开（密钥轮换/文件损坏）时记录错误并返回空串，
          避免因为一个坏凭据把整个启动流程打挂。
        """
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value)
        if not is_encrypted(text):
            # 旧版明文，透传
            return text
        token = text[len(PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except self._invalid_token:
            logger.error(
                "凭据解密失败（密文无法用当前主密钥解开）。"
                "通常是主密钥变更或密钥文件被替换；该凭据将被视为空值。"
            )
            return ""
        except Exception:  # noqa: BLE001
            logger.exception("凭据解密异常；该凭据将被视为空值")
            return ""


# ── 默认单例（懒加载）──

_default_cipher: Optional[CredentialCipher] = None


def get_cipher() -> CredentialCipher:
    """返回进程级默认加解密器（首次调用时解析主密钥）。"""
    global _default_cipher
    if _default_cipher is None:
        _default_cipher = CredentialCipher()
    return _default_cipher


def reset_cipher() -> None:
    """丢弃缓存的默认加解密器（测试用）。"""
    global _default_cipher
    _default_cipher = None


def encrypt_str(plaintext: object) -> str:
    """加密（默认加解密器）。"""
    return get_cipher().encrypt_str(plaintext)


def decrypt_str(value: object) -> str:
    """解密（默认加解密器）；旧版明文原样返回。"""
    return get_cipher().decrypt_str(value)
