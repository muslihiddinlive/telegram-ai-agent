"""
core/site_fetch.py
------------------
Sayt nusxalagich (core/site_pack.py) uchun SSRF-XAVFSIZ HTTP(S) mijoz.

Nega bu kerak: foydalanuvchi bergan URL'ni SERVER yuklab oladi. Himoyasiz bo'lsa, hujumchi botni ichki manzillarga (127.0.0.1, Render'ning ichki
servislari, bulut metadata 169.254.169.254, router va h.k.) so'rov yuborishga majbur qila oladi va javobni o'qib oladi.

Himoyalar:
  * Faqat http/https, faqat 80/443/8080/8443 portlar; `user:pass@` va g'alati URL'lar rad etiladi.
  * Host nomi DNS orqali aniqlanadi va BARCHA manzillar GLOBAL (ommaviy) bo'lishi shart: private, loopback, link-local, CGNAT, multicast,
    reserved, IPv4-mapped/6to4/Teredo/NAT64 ichiga yashirilgan ichki manzillar — rad etiladi.
  * DNS-REBINDING himoyasi: tekshirilgan IP'ga ULANAMIZ (URL'da IP, `Host` sarlavhasi va TLS SNI/sertifikat tekshiruvi asl host bo'yicha) —
    tekshiruv va ulanish orasida DNS javobi almashib ketolmaydi.
  * Redirect'lar qo'lda kuzatiladi: HAR BIR qadam qaytadan to'liq tekshiriladi (ichkariga redirect qilish ishlamaydi). Eng ko'pi 5 ta.
  * Muhit proksilari (HTTP_PROXY ...) e'tiborsiz (trust_env=False): ular tekshiruvni chetlab o'tardi.
  * Hajm (oqim bo'yicha, siqilgan javob ham) va vaqt chegaralari; cookie/avtorizatsiya sarlavhalari yuborilmaydi.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger("site_fetch")

ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_REDIRECTS = 5
MAX_URL_LEN = 2000
CONNECT_TIMEOUT = 8.0
READ_TIMEOUT = 15.0
DNS_TIMEOUT = 5.0
USER_AGENT = "Mozilla/5.0 (compatible; SiteCopierBot/1.0; +read-only)"
_VERIFY = True          # testlarda maxsus CA bilan almashtiriladi (production'da HECH QACHON o'zgartirilmaydi)

_BLOCKED_NAMES = ("localhost", "localhost.localdomain")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".intranet", ".lan", ".home", ".corp", ".localdomain", ".home.arpa")
_EXTRA_BLOCKED_V6 = tuple(ipaddress.ip_network(n) for n in ("64:ff9b::/96", "2002::/16", "2001::/32", "fc00::/7", "fe80::/10", "::/128", "::1/128"))


class SiteError(Exception):
    """Foydalanuvchiga ko'rsatsa bo'ladigan xato (ichida ichki ma'lumot yo'q)."""


@dataclass
class Fetched:
    url: str                 # redirect'lardan keyingi yakuniy URL
    status: int
    content_type: str
    body: bytes
    truncated: bool = False


def _ip_ok(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Faqat ommaviy (global) manzillar. Testlarda lokal server uchun almashtiriladi."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _ip_ok(ip.ipv4_mapped)
        if any(ip in net for net in _EXTRA_BLOCKED_V6):
            return False
    return bool(ip.is_global) and not ip.is_multicast


def validate_url(url: str) -> tuple[str, str, int, str]:
    """-> (scheme, host, port, path_va_query). Xavfli/noto'g'ri URL'da SiteError."""
    u = (url or "").strip()
    if not u or len(u) > MAX_URL_LEN or any(c in u for c in " \t\r\n\x00\\"):
        raise SiteError("URL noto'g'ri.")
    try:
        parts = urlsplit(u)
        port = parts.port
    except ValueError:
        raise SiteError("URL noto'g'ri.")
    if parts.scheme not in ("http", "https"):
        raise SiteError("Faqat http:// va https:// havolalar qo'llab-quvvatlanadi.")
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        raise SiteError("URL ichida login/parol bo'lishi mumkin emas.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise SiteError("URL noto'g'ri (host yo'q).")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise SiteError(f"Port {port} ruxsat etilmagan (faqat 80, 443, 8080, 8443).")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not _ip_ok(ip):                  # IP-literal: darhol (resolve'da yana bir bor tekshiriladi)
        raise SiteError("Bu manzilga murojaat qilish taqiqlangan (ichki tarmoq).")
    if ip is None:
        if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
            raise SiteError("Bu manzilga murojaat qilish taqiqlangan (ichki tarmoq).")
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise SiteError("Host nomi noto'g'ri.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.scheme, host, port, path


async def resolve(host: str, port: int) -> list[str]:
    """Host'ni IP'larga aylantiradi; BIRORTA manzil ham ommaviy bo'lmasa — rad. -> tekshirilgan IP'lar."""
    try:
        lit = ipaddress.ip_address(host)
        addrs = [lit]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=DNS_TIMEOUT)
        except (asyncio.TimeoutError, socket.gaierror, OSError):
            raise SiteError("Sayt manzili topilmadi (DNS xatosi).")
        addrs = []
        for info in infos:
            try:
                a = ipaddress.ip_address(info[4][0].split("%")[0])
            except ValueError:
                continue
            if a not in addrs:
                addrs.append(a)
    if not addrs:
        raise SiteError("Sayt manzili topilmadi.")
    if not all(_ip_ok(a) for a in addrs):
        raise SiteError("Bu manzilga murojaat qilish taqiqlangan (ichki tarmoq).")
    return [str(a) for a in addrs]


def _ip_in_url(ip: str) -> str:
    return f"[{ip}]" if ":" in ip else ip


async def fetch(url: str, *, max_bytes: int = 5 * 1024 * 1024, deadline: float | None = None, accept: str = "*/*",
                allow_truncate: bool = False) -> Fetched:
    """URL'ni xavfsiz yuklaydi (redirect'lar bilan). max_bytes oshsa: allow_truncate bo'lsa kesadi, aks holda SiteError."""
    cur = url
    for hop in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = validate_url(cur)
        ips = await resolve(host, port)
        ip = ips[0]
        default_port = 443 if scheme == "https" else 80
        host_header = host if port == default_port else f"{host}:{port}"
        target = f"{scheme}://{_ip_in_url(ip)}:{port}{path}"
        left = (deadline - time.monotonic()) if deadline else None
        if left is not None and left <= 0:
            raise SiteError("Vaqt tugadi.")
        timeout = httpx.Timeout(min(READ_TIMEOUT, left) if left else READ_TIMEOUT, connect=min(CONNECT_TIMEOUT, left) if left else CONNECT_TIMEOUT)
        headers = {"Host": host_header, "User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip, deflate"}
        ext = {"sni_hostname": host} if scheme == "https" else {}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=_VERIFY, trust_env=False) as client:
                async with client.stream("GET", target, headers=headers, extensions=ext) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise SiteError("Noto'g'ri redirect.")
                        cur = urljoin(cur, loc)
                        continue
                    cl = r.headers.get("content-length")
                    if cl and cl.isdigit() and int(cl) > max_bytes and not allow_truncate:
                        raise SiteError(f"Fayl juda katta ({int(cl) // 1024} KB).")
                    buf, total, truncated = bytearray(), 0, False
                    async for chunk in r.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            if not allow_truncate:
                                raise SiteError(f"Fayl juda katta (> {max_bytes // 1024} KB).")
                            buf.extend(chunk[: max_bytes - (total - len(chunk))])
                            truncated = True
                            break
                        buf.extend(chunk)
                        if deadline and time.monotonic() > deadline:
                            raise SiteError("Vaqt tugadi.")
                    return Fetched(cur, r.status_code, (r.headers.get("content-type") or "").split(";")[0].strip().lower(), bytes(buf), truncated)
        except SiteError:
            raise
        except httpx.TimeoutException:
            raise SiteError("Sayt javob bermadi (vaqt tugadi).")
        except httpx.HTTPError as e:
            logger.info("fetch xatosi: %s", type(e).__name__)
            raise SiteError("Saytga ulanib bo'lmadi.")
    raise SiteError("Juda ko'p redirect.")
