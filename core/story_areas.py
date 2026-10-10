"""
core/story_areas.py
-------------------
Story ustidagi bosiladigan MAYDONLAR (Bot API `postStory.areas`): havola va tavsiya etilgan reaksiya.
Cheklovlar (Bot API): bitta storyda eng ko'pi 3 ta havola va 5 ta reaksiya maydoni; foizlar medianing kengligi/balandligiga nisbatan.

Xavfsizlik: havola faqat http/https, domen nuqtali va to'g'ri ko'rinishda bo'lishi kerak; `user@host` ko'rinishidagi
(soxta-domen) havolalar, localhost va ichki IP'lar rad etiladi.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlparse

from aiogram.types import (ReactionTypeEmoji, StoryArea, StoryAreaPosition, StoryAreaTypeLink,
                           StoryAreaTypeSuggestedReaction)

MAX_LINKS = 3
MAX_REACTIONS = 5
MAX_URL_LEN = 500
REACTIONS = ["❤", "🔥", "👍", "😍", "🎉", "🤩", "😁", "👏"]        # Telegram qo'llab-quvvatlaydigan reaksiya emojilari
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def clean_url(raw: str) -> Optional[str]:
    """Foydalanuvchi yuborgan havolani tekshiradi va tozalaydi. Yaroqsiz bo'lsa None."""
    s = (raw or "").strip()
    if not s or len(s) > MAX_URL_LEN or re.search(r"[\s\x00-\x1f\x7f]", s):
        return None
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", s):
        s = "https://" + s                                     # "example.com/x" — https qo'shamiz
    try:
        u = urlparse(s)
        host = u.hostname
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not host or "@" in u.netloc:
        return None
    try:
        ipaddress.ip_address(host)
        return None                                            # IP manzillar (ichki tarmoq ham) kerak emas
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode()
    except UnicodeError:
        return None
    if not _HOST_RE.match(ascii_host) or ascii_host.lower() in ("localhost",):
        return None
    return s


def _link_position(i: int) -> StoryAreaPosition:
    return StoryAreaPosition(x_percentage=50.0, y_percentage=90.0 - 9.0 * i, width_percentage=72.0,
                             height_percentage=7.0, rotation_angle=0.0, corner_radius_percentage=50.0)


def _reaction_position(i: int, n: int) -> StoryAreaPosition:
    x = 50.0 - (n - 1) * 8.5 + i * 17.0                       # n ta kvadrat-ga yaqin maydon, markazda qator
    return StoryAreaPosition(x_percentage=x, y_percentage=58.0, width_percentage=15.0, height_percentage=8.5,
                             rotation_angle=0.0, corner_radius_percentage=0.0)


def build(links: list[str], reactions: list[str]) -> list[StoryArea]:
    """Tekshirilgan havolalar va reaksiyalardan Bot API maydonlari ro'yxati."""
    areas: list[StoryArea] = []
    for i, url in enumerate(links[:MAX_LINKS]):
        areas.append(StoryArea(position=_link_position(i), type=StoryAreaTypeLink(url=url)))
    rs = [r for r in reactions if r in REACTIONS][:MAX_REACTIONS]
    for i, emoji in enumerate(rs):
        areas.append(StoryArea(position=_reaction_position(i, len(rs)),
                               type=StoryAreaTypeSuggestedReaction(reaction_type=ReactionTypeEmoji(emoji=emoji))))
    return areas


def summary(links: list[str], reactions: list[str]) -> str:
    parts = []
    if links:
        parts.append(f"🔗 havolalar: {len(links)}")
    if reactions:
        parts.append("reaksiyalar: " + " ".join(reactions))
    return " · ".join(parts)
