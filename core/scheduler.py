"""
Fon vazifasi — har daqiqada Toshkent vaqtini tekshirib, belgilangan soatda kunlik ishlarni bajaradi:
  • 20:00 — /top_faollar_avto yoqilgan guruhlarga avtomatik yuboriladi (core/auto_top.py)
Jarayon xotirasida "bugun allaqachon yuborildimi" belgisi saqlanadi — bitta soat ichida
ikki marta yuborilib ketmasligi uchun (server qayta ishga tushsa, shu kun yana bir marta
yuborilishi mumkin — bu xavfsiz tomonga xato, takror yuborish o'rniga o'tkazib yuborish emas).
"""
import asyncio
import logging

import time

import core.auto_top as auto_top
import core.clock as clock
import core.tariffs as tariffs

logger = logging.getLogger("scheduler")

CHECK_INTERVAL = 60
TARIFF_REMINDER_EVERY = 1800  # tarif muddati eslatmalarini har 30 daqiqada tekshiramiz
_last_top_date: str | None = None
_last_tariff_check = 0.0


async def _run_top_faollar(bot):
    global _last_top_date
    import handlers.group_tools as group_tools  # dumaloq import'dan qochish uchun kech

    for chat_id in auto_top.enabled_chats():
        try:
            await group_tools.send_top_faollar(bot, chat_id, header="🏆 Bugungi eng faol a'zolar:")
        except Exception:  # noqa: BLE001
            logger.exception("Kunlik top-faollar yuborilmadi (chat=%s)", chat_id)


async def run_forever(bot):
    global _last_top_date, _last_tariff_check
    while True:
        try:
            if time.time() - _last_tariff_check >= TARIFF_REMINDER_EVERY:
                _last_tariff_check = time.time()
                await tariffs.send_reminders(bot)
            now = clock.now()
            today = now.strftime("%Y-%m-%d")
            if now.hour == 20 and _last_top_date != today:
                _last_top_date = today
                await _run_top_faollar(bot)
        except Exception:  # noqa: BLE001 — fon tsikli hech qachon to'xtamasin
            logger.exception("Scheduler tsiklida xatolik")
        await asyncio.sleep(CHECK_INTERVAL)
