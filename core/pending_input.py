"""
Matn-kiritish orqali bosqichma-bosqich oqimlar — StokerDownloader'dagi
set_pending_input/get_pending_input/clear_pending_input patternidan.

Xotira ichida (in-memory) saqlanadi — restart bo'lsa tozalanadi, bu normal
(login/parol kabi vaqtinchalik oqimlar restart'dan keyin qayta boshlanishi kerak).

Ishlatilishi:
  pending_input.set(user_id, "apikey_wait_value", {"provider": "groq"})
  ...
  state = pending_input.get(user_id)
  if state and state["action"] == "apikey_wait_value":
      code = message.text
      ...
      pending_input.clear(user_id)
"""
_pending: dict[int, dict] = {}


def set(user_id: int, action: str, data: dict | None = None):
    _pending[user_id] = {"action": action, "data": data or {}}


def get(user_id: int) -> dict | None:
    return _pending.get(user_id)


def clear(user_id: int):
    _pending.pop(user_id, None)
