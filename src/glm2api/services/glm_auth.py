from __future__ import annotations

import hashlib
import gzip
import json
import os
import random
import threading
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from logging import Logger

from ..config import AppConfig, DEFAULT_SIGN_SECRET, GUEST_REFRESH_TOKEN_MARKER
from ..logging_utils import debug_dump, mask_sensitive_headers


# 签名密钥：模块加载时先从真实环境变量读取一次（供 build_sign 在管理器构造前使用），
# 之后 GLMAccessTokenManager.__init__ 会用 config.glm_sign_secret（已合并 .env）覆盖。
SIGN_SECRET = os.environ.get("GLM_SIGN_SECRET") or DEFAULT_SIGN_SECRET
ACCESS_TOKEN_EXPIRES_SECONDS = 3600


def build_sign() -> tuple[str, str, str]:
    now = str(int(time.time() * 1000))
    digits = [int(char) for char in now]
    checksum = (sum(digits) - digits[-2]) % 10
    timestamp = now[:-2] + str(checksum) + now[-1]
    nonce = uuid.uuid4().hex
    sign = hashlib.md5(f"{timestamp}-{nonce}-{SIGN_SECRET}".encode("utf-8")).hexdigest()
    return timestamp, nonce, sign


@dataclass(slots=True)
class AccessToken:
    access_token: str
    refresh_token: str
    expires_at: float


@dataclass(slots=True)
class AccountState:
    refresh_token: str
    is_guest: bool = False
    cached_token: AccessToken | None = None
    # 每个账号持有一个稳定的 device_id，所有请求复用同一个值，
    # 避免每次请求都换 device_id（真实浏览器同一个会话不会频繁换设备指纹）。
    device_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class GLMAccessTokenManager:
    def __init__(self, config: AppConfig, logger: Logger) -> None:
        self.config = config
        self.logger = logger
        # 用 config（已合并 .env 与真实环境变量）覆盖模块级 SIGN_SECRET，
        # 这样 build_sign() 在后续所有调用中都会使用配置中的密钥。
        global SIGN_SECRET
        SIGN_SECRET = config.glm_sign_secret
        self._accounts = [
            AccountState(
                refresh_token="" if token == GUEST_REFRESH_TOKEN_MARKER else token,
                is_guest=(token == GUEST_REFRESH_TOKEN_MARKER),
            )
            for token in config.glm_refresh_tokens
        ]
        self._current_index = 0
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        logger.info(
            "账号管理器初始化 账号数=%s 游客模式=%s",
            len(self._accounts),
            any(a.is_guest for a in self._accounts),
        )

    def get_device_id(self, account_index: int) -> str:
        with self._lock:
            return self._accounts[account_index].device_id

    def get_browser_headers(self, app_fr: str = "web") -> dict[str, str]:
        # X-App-Fr 必须与 Origin 保持一致：Origin 是 https://chatglm.cn 且
        # Sec-Fetch-Site 是 same-origin，说明伪装的是 chatglm.cn 网页端自身发起的请求，
        # 因此 X-App-Fr 应取网页端取值（"web"），而不是 "browser_extension"
        # （浏览器扩展的 Origin 应为 chrome-extension://...，与 chatglm.cn 矛盾）。
        return {
            "Accept": "application/json, text/plain, */*" if app_fr == "default" else "text/event-stream",
            "Accept-Encoding": "gzip, deflate" if app_fr == "default" else "identity",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "App-Name": "chatglm",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "Origin": "https://chatglm.cn",
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Sec-Ch-Ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": self.config.glm_user_agent,
            "X-App-Fr": app_fr,
            "X-App-Platform": "pc",
            "X-App-Version": "0.0.1",
            "X-Device-Brand": "",
            "X-Device-Model": "",
            "X-Lang": "zh",
        }

    def read_json_response(self, response) -> dict[str, object]:
        try:
            raw_body = response.read()
            content_encoding = response.headers.get("Content-Encoding", "").lower()

            if content_encoding == "gzip":
                raw_body = gzip.decompress(raw_body)

            debug_dump(self.logger, self.config.debug_dump_all, "GLM 原始 JSON 响应体", raw_body)
            payload = json.loads(raw_body.decode("utf-8"))
        except gzip.BadGzipFile as exc:
            raise RuntimeError("GLM 响应 gzip 解压失败") from exc
        except UnicodeDecodeError as exc:
            raise RuntimeError("GLM 响应不是合法 UTF-8") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GLM 响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"GLM 响应格式异常，期望 JSON 对象，实际是: {type(payload).__name__}")
        return payload

    def get_access_token(self) -> str:
        with self._lock:
            return self._get_access_token_for_index(self._current_index)

    def get_account_count(self) -> int:
        return len(self._accounts)

    def get_current_account_index(self) -> int:
        with self._lock:
            return self._current_index

    def is_guest_account(self, account_index: int) -> bool:
        with self._lock:
            return self._accounts[account_index].is_guest

    def advance_account(self, failed_index: int, reason: str) -> int:
        with self._lock:
            if failed_index != self._current_index:
                return self._current_index
            next_index = (failed_index + 1) % len(self._accounts)
            self._current_index = next_index
            self.logger.warning(
                "账号请求失败，切换 refresh_token 账号 index=%s -> %s reason=%s",
                failed_index,
                next_index,
                reason,
            )
            return next_index

    def reset_account_cycle(self) -> None:
        with self._lock:
            self._current_index = 0

    def invalidate_account(self, account_index: int) -> None:
        with self._lock:
            self._accounts[account_index].cached_token = None

    def get_access_token_for_account(self, account_index: int) -> str:
        with self._lock:
            return self._get_access_token_for_index(account_index)

    def _get_access_token_for_index(self, account_index: int) -> str:
        account = self._accounts[account_index]
        if account.cached_token and time.time() < account.cached_token.expires_at - 60:
            self.logger.debug("使用缓存 access_token account=%s 剩余=%.0fs", account_index, account.cached_token.expires_at - time.time())
            return account.cached_token.access_token
        account.cached_token = self._refresh_access_token(account_index)
        return account.cached_token.access_token

    def _refresh_access_token(self, account_index: int) -> AccessToken:
        account = self._accounts[account_index]
        if account.is_guest or not account.refresh_token:
            return self._fetch_guest_access_token(account_index)
        timestamp, nonce, sign = build_sign()
        request = urllib.request.Request(
            self.config.refresh_url,
            data=b"{}",
            method="POST",
            headers={
                **self.get_browser_headers(),
                "Authorization": f"Bearer {account.refresh_token}",
                "X-Device-Id": account.device_id,
                "X-Nonce": nonce,
                "X-Request-Id": uuid.uuid4().hex,
                "X-Sign": sign,
                "X-Timestamp": timestamp,
            },
        )
        debug_dump(self.logger, self.config.debug_dump_all, f"GLM 刷新 access_token 请求头 account={account_index}", mask_sensitive_headers(dict(request.header_items())))
        debug_dump(self.logger, self.config.debug_dump_all, f"GLM 刷新 access_token 请求体 account={account_index}", b"{}")
        with urllib.request.urlopen(request, timeout=self.config.request_timeout) as response:
            payload = self.read_json_response(response)
        code = payload.get("code", payload.get("status"))
        result = payload.get("result") or {}
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token", account.refresh_token)
        if response.status != 200 or code not in {0, None} or not access_token:
            raise RuntimeError(f"刷新 GLM token 失败: {payload}")
        if refresh_token != account.refresh_token:
            try:
                self._persist_refresh_token(account_index, refresh_token)
            except Exception as exc:
                self.logger.warning("写回 GLM refresh_token 失败 index=%s error=%s", account_index, exc)
            account.refresh_token = refresh_token
            self.config.glm_refresh_tokens[account_index] = refresh_token
            if account_index == 0:
                self.config.glm_refresh_token = refresh_token
            self.logger.info("GLM refresh_token 已自动刷新并写回账号存储 index=%s", account_index)
        return AccessToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + ACCESS_TOKEN_EXPIRES_SECONDS - random.randint(10, 30),
        )

    def _fetch_guest_access_token(self, account_index: int) -> AccessToken:
        account = self._accounts[account_index]
        timestamp, nonce, sign = build_sign()
        request_id = uuid.uuid4().hex
        request = urllib.request.Request(
            self.config.guest_refresh_url,
            data=b"",
            method="POST",
            headers={
                **self.get_browser_headers(app_fr="default"),
                "Content-Length": "0",
                "Referer": "https://chatglm.cn/",
                "X-Device-Id": account.device_id,
                "X-Nonce": nonce,
                "X-Request-Id": request_id,
                "X-Sign": sign,
                "X-Timestamp": timestamp,
            },
        )
        debug_dump(self.logger, self.config.debug_dump_all, f"GLM 游客 token 请求头 account={account_index}", mask_sensitive_headers(dict(request.header_items())))
        debug_dump(self.logger, self.config.debug_dump_all, f"GLM 游客 token 请求体 account={account_index}", b"")
        with urllib.request.urlopen(request, timeout=self.config.request_timeout) as response:
            payload = self.read_json_response(response)
        code = payload.get("code", payload.get("status"))
        result = payload.get("result") or {}
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        if response.status != 200 or code not in {0, None} or not access_token or not refresh_token:
            raise RuntimeError(f"获取 GLM 游客 token 失败: {payload}")
        account.refresh_token = str(refresh_token)
        self.logger.info("已获取新的 GLM 游客 refresh_token index=%s", account_index)
        return AccessToken(
            access_token=str(access_token),
            refresh_token=str(refresh_token),
            expires_at=time.time() + ACCESS_TOKEN_EXPIRES_SECONDS - random.randint(10, 30),
        )

    def _persist_refresh_token(self, account_index: int, refresh_token: str) -> None:
        with self._persist_lock:
            if self._accounts[account_index].is_guest:
                return
            if self.config.token_file_path.exists() or len(self.config.glm_refresh_tokens) > 1:
                tokens = list(self.config.glm_refresh_tokens)
                tokens[account_index] = refresh_token
                content = "\n".join(tokens) + "\n"
                try:
                    self.config.token_file_path.write_text(content, encoding="utf-8")
                except OSError as exc:
                    raise RuntimeError(f"写入 token 文件失败: {self.config.token_file_path} error={exc}") from exc
                return
            self._persist_env_refresh_token(refresh_token)

    def _persist_env_refresh_token(self, refresh_token: str) -> None:
        env_path = self.config.env_file_path
        if not env_path.exists():
            self.logger.warning(".env 文件不存在，无法自动写回新的 refresh_token")
            return

        # 跨进程文件锁：防止多实例并发写回 .env 造成内容覆盖。
        # 单实例时 _persist_lock（threading.Lock）已保证线程安全，
        # 这里再加 OS 级锁兜底多进程场景。Windows 无 fcntl，回退到仅线程锁。
        lock_path = env_path.parent / ".env.lock"
        lock_fh = open(lock_path, "w")
        try:
            try:
                import fcntl
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass  # Windows: fcntl 不可用，依赖 threading.Lock

            try:
                content = env_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(f".env 不是有效的 UTF-8 编码: {env_path}") from exc
            except OSError as exc:
                raise RuntimeError(f"读取 .env 失败: {env_path} error={exc}") from exc
            lines = content.splitlines()
            updated = False

            for index, line in enumerate(lines):
                if line.startswith("GLM_REFRESH_TOKEN="):
                    lines[index] = f"GLM_REFRESH_TOKEN={refresh_token}"
                    updated = True
                    break

            if not updated:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(f"GLM_REFRESH_TOKEN={refresh_token}")

            new_content = "\n".join(lines) + "\n"
            try:
                env_path.write_text(new_content, encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(f"写入 .env 失败: {env_path} error={exc}") from exc
        finally:
            try:
                import fcntl
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
            lock_fh.close()

    def should_switch_account(self, exc: Exception) -> bool:
        if hasattr(exc, "status_code"):
            return True
        if isinstance(exc, urllib.error.HTTPError):
            return True
        if isinstance(exc, urllib.error.URLError):
            return True
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, RuntimeError):
            return "token" in str(exc).lower()
        return False
