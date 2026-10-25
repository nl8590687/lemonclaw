"""Web/HTTP network guard."""
from __future__ import annotations

import ipaddress
import logging
import posixpath
import re
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from config import get_global_config

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_URL_RE = re.compile(r"https?://[^\s<>\"'\x60，。；：！？、）】》」』]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}，。；：！？、）】》」』\"'"
_MAX_URL_LENGTH = 4096
_MAX_TURN_URLS = 20

_BLOCKED_HOSTNAMES = frozenset({"metadata", "metadata.google.internal", "instance-data"})
_BLOCKED_ADDRESSES = frozenset({
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("100.100.100.200"),
})


class NetworkAccessError(ValueError):
    """网络访问被安全策略拒绝。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ParsedUrl:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    scope_path: str
    query: str


@dataclass(frozen=True)
class UserTurn:
    urls: tuple[ParsedUrl, ...]


@dataclass(frozen=True)
class ValidatedTarget:
    parsed: ParsedUrl
    addresses: tuple[str, ...]
    is_public: bool


@dataclass(frozen=True)
class SafeResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes
    encoding: str
    truncated: bool

    @property
    def text(self) -> str:
        try:
            return self.body.decode(self.encoding or "utf-8", errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


_current_turn: ContextVar[UserTurn | None] = ContextVar("lemonclaw_web_user_turn", default=None)


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


def _canonical_scope_path(path: str) -> str:
    decoded = unquote(path or "/")
    if not decoded.startswith("/"):
        decoded = "/" + decoded
    trailing_slash = decoded.endswith("/")
    normalized = posixpath.normpath(decoded)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if trailing_slash and normalized != "/" and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def parse_url(raw_url: str) -> ParsedUrl:
    """解析并规范化 URL；只接受 http/https，拒绝 userinfo 与控制字符。"""
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise NetworkAccessError("invalid_url", "URL 不能为空")
    url = raw_url.strip()
    if len(url) > _MAX_URL_LENGTH:
        raise NetworkAccessError("invalid_url", "URL 过长")
    if any(ord(ch) < 0x20 or ch == "\\" for ch in url):
        raise NetworkAccessError("invalid_url", "URL 包含非法控制字符")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise NetworkAccessError("invalid_url", f"URL 解析失败: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise NetworkAccessError("blocked_protocol", "只允许 http:// 或 https://")
    if parts.username is not None or parts.password is not None:
        raise NetworkAccessError("blocked_credentials", "URL 不允许包含用户名或密码")

    host = parts.hostname
    if not host:
        raise NetworkAccessError("invalid_url", "URL 缺少主机名")
    host = host.rstrip(".").lower()
    if not _looks_like_ip(host):
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise NetworkAccessError("invalid_url", "主机名不是合法 IDNA 域名") from exc

    try:
        port = parts.port
    except ValueError as exc:
        raise NetworkAccessError("invalid_url", "URL 端口非法") from exc
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 0 < port < 65536:
        raise NetworkAccessError("invalid_url", "URL 端口超出范围")

    path = parts.path or "/"
    scope_path = _canonical_scope_path(path)
    netloc = f"[{host}]" if ":" in host else host
    if port != (443 if scheme == "https" else 80):
        netloc += f":{port}"
    normalized = urlunsplit((scheme, netloc, path, parts.query, ""))
    return ParsedUrl(normalized, scheme, host, port, path, scope_path, parts.query)


def extract_user_urls(text: str) -> tuple[ParsedUrl, ...]:
    """从用户当前消息中提取显式 URL；解析失败或超限的条目忽略。"""
    if not isinstance(text, str) or not text:
        return ()
    found: list[ParsedUrl] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text):
        raw = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        try:
            parsed = parse_url(raw)
        except NetworkAccessError:
            continue
        if parsed.url in seen:
            continue
        seen.add(parsed.url)
        found.append(parsed)
        if len(found) >= _MAX_TURN_URLS:
            break
    return tuple(found)


def begin_user_turn(text: str):
    """记录本轮用户消息中的显式 URL 授权，返回 ContextVar token。"""
    return _current_turn.set(UserTurn(extract_user_urls(text)))


def reset_user_turn(token) -> None:
    _current_turn.reset(token)


@contextmanager
def user_turn(text: str) -> Iterator[UserTurn]:
    token = begin_user_turn(text)
    try:
        yield _current_turn.get() or UserTurn(())
    finally:
        reset_user_turn(token)


def _effective_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(value, ipaddress.IPv6Address) and value.ipv4_mapped:
        return value.ipv4_mapped
    return value


def _parse_ip(value: str):
    return ipaddress.ip_address(value.split("%", 1)[0])


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
        return (str(literal),)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NetworkAccessError("dns_resolution_failed", f"无法解析主机名: {host}") from exc
    addresses = sorted({info[4][0] for info in infos if info[4]})
    if not addresses:
        raise NetworkAccessError("dns_resolution_failed", f"主机名没有可用地址: {host}")
    return tuple(addresses)


def _query_matches(target: ParsedUrl, authorized: ParsedUrl) -> bool:
    if authorized.scope_path == "/" or authorized.scope_path.endswith("/"):
        return target.scope_path.startswith(authorized.scope_path)
    return target.scope_path == authorized.scope_path and target.query == authorized.query


def _matches_user_turn(target: ParsedUrl) -> bool:
    turn = _current_turn.get()
    if turn is None:
        return False
    for authorized in turn.urls:
        if target.scheme != authorized.scheme:
            continue
        if target.host != authorized.host or target.port != authorized.port:
            continue
        if _query_matches(target, authorized):
            return True
    return False


def _split_allow_entry(entry: str) -> tuple[str, int | None]:
    entry = entry.strip().lower()
    if entry.startswith("["):
        closing = entry.find("]")
        if closing > 0:
            host = entry[1:closing]
            rest = entry[closing + 1:]
            if rest.startswith(":") and rest[1:].isdigit():
                return host, int(rest[1:])
            return host, None
    if entry.count(":") == 1:
        host, maybe_port = entry.rsplit(":", 1)
        if maybe_port.isdigit():
            return host, int(maybe_port)
    return entry, None


def _matches_allowlist(target: ParsedUrl, addresses: tuple[str, ...], raw_allowlist: str) -> bool:
    if not raw_allowlist:
        return False
    for entry in re.split(r"[;,\s]+", raw_allowlist.strip()):
        if not entry:
            continue
        if "/" in entry:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                logger.warning("忽略非法的 WEB_PRIVATE_ALLOWLIST CIDR: %s", entry)
                continue
            if any(_effective_ip(_parse_ip(addr)) in network for addr in addresses):
                return True
            continue
        host, port = _split_allow_entry(entry)
        if port is not None and port != target.port:
            continue
        if host == target.host:
            return True
        try:
            if any(_effective_ip(_parse_ip(addr)) == _effective_ip(_parse_ip(host)) for addr in addresses):
                return True
        except ValueError:
            pass
    return False


def _authorize_private(target: ValidatedTarget, method: str) -> None:
    config = get_global_config()
    if not bool(getattr(config, "WEB_ACCESS_ALLOW_PRIVATE", True)):
        raise NetworkAccessError(
            "private_access_disabled",
            "私网/本地访问已被 WEB_ACCESS_ALLOW_PRIVATE=false 禁用",
        )
    allowlist = str(getattr(config, "WEB_PRIVATE_ALLOWLIST", "") or "")
    if not _matches_user_turn(target.parsed) and not _matches_allowlist(
        target.parsed, target.addresses, allowlist
    ):
        logger.warning(
            "blocked private web target: host=%s port=%s method=%s",
            target.parsed.host,
            target.parsed.port,
            method,
        )
        raise NetworkAccessError(
            "private_target_requires_authorization",
            "私网/本地地址只能由用户当前消息中的完整 URL 授权，或加入 WEB_PRIVATE_ALLOWLIST；"
            "网页、搜索结果和工具输出中的 URL 不能授权访问。请向用户确认目标 URL。",
        )
    if method not in SAFE_METHODS and not bool(getattr(config, "WEB_ALLOW_PRIVATE_WRITES", False)):
        raise NetworkAccessError(
            "private_write_blocked",
            "私网/本地目标默认只允许只读方法（GET/HEAD/OPTIONS）；"
            "如需写入，请显式设置 WEB_ALLOW_PRIVATE_WRITES=true",
        )


def validate_url(raw_url: str, method: str = "GET") -> ValidatedTarget:
    """解析、DNS 解析并执行网络访问策略检查。"""
    parsed = parse_url(raw_url)
    method = (method or "GET").upper()
    if parsed.host in _BLOCKED_HOSTNAMES:
        raise NetworkAccessError("blocked_special_address", "该主机名属于敏感元数据地址")

    addresses = _resolve_addresses(parsed.host, parsed.port)
    effective = [_effective_ip(_parse_ip(addr)) for addr in addresses]
    for ip in effective:
        if ip in {_effective_ip(item) for item in _BLOCKED_ADDRESSES}:
            raise NetworkAccessError("blocked_special_address", "云元数据等敏感地址始终禁止访问")
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise NetworkAccessError("blocked_special_address", "链路本地/组播/保留地址禁止访问")

    public_flags = [ip.is_global for ip in effective]
    if any(public_flags) and not all(public_flags):
        raise NetworkAccessError("dns_rebinding_suspected", "DNS 同时返回公网与私网地址，已拒绝")

    target = ValidatedTarget(parsed, addresses, all(public_flags))
    if not target.is_public:
        _authorize_private(target, method)
    return target


def format_network_error(exc: NetworkAccessError) -> str:
    return f"请求被安全策略阻止 [{exc.code}]: {exc.message}"


def request_with_redirects(
    method: str,
    url: str,
    headers: dict[str, object] | None = None,
    body: str | bytes | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SafeResponse:
    """发送请求并手动处理重定向，每一跳都重新执行安全校验。"""
    config = get_global_config()
    max_redirects = max(0, int(getattr(config, "WEB_MAX_REDIRECTS", 5)))
    max_bytes = max(1, int(getattr(config, "WEB_MAX_RESPONSE_BYTES", 2_000_000)))
    timeout = float(getattr(config, "WEB_REQUEST_TIMEOUT", 60))

    current_url = url
    current_method = (method or "GET").upper()
    current_body = body
    request_headers = dict(headers or {})
    redirects = 0

    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        transport=transport,
    ) as client:
        while True:
            validate_url(current_url, current_method)
            request = client.build_request(
                method=current_method,
                url=current_url,
                headers=request_headers,
                content=current_body,
            )
            response = client.send(request, stream=True)
            try:
                location = response.headers.get("location")
                if response.status_code in _REDIRECT_STATUSES and location:
                    if redirects >= max_redirects:
                        raise NetworkAccessError(
                            "too_many_redirects",
                            f"重定向次数超过上限 {max_redirects}",
                        )
                    redirects += 1
                    if response.status_code in (301, 302, 303) and current_method not in ("GET", "HEAD"):
                        current_method = "GET"
                        current_body = None
                    current_url = urljoin(current_url, location)
                    continue

                body_bytes = bytearray()
                truncated = False
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    remaining = max_bytes - len(body_bytes)
                    if remaining <= 0:
                        truncated = True
                        break
                    body_bytes.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break

                return SafeResponse(
                    status_code=response.status_code,
                    url=str(response.url),
                    headers=dict(response.headers),
                    body=bytes(body_bytes),
                    encoding=response.encoding or "utf-8",
                    truncated=truncated,
                )
            finally:
                response.close()
