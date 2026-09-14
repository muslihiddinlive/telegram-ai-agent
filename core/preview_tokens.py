"""
Inline tugmalar uchun callback_data 64 baytdan oshmasligi kerak, shuning
uchun to'liq fayl yo'lini emas, qisqa tokenni yuboramiz — bu yerda
token -> fayl_yo'li moslashtirilib turiladi (xotirada, vaqtinchalik).
"""
import uuid

_tokens: dict[str, str] = {}


def store(file_path: str) -> str:
    token = uuid.uuid4().hex[:12]
    _tokens[token] = file_path
    return token


def resolve(token: str) -> str | None:
    return _tokens.get(token)
