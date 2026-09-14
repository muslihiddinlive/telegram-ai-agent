"""
ms-file-toolkit ulanishi uchun wrapper.

Eng oson yo'l: ms-file-toolkit'ni PyPI'dan o'rnating (siz uni allaqachon
paketlab qo'ygansiz):
    pip install ms-file-toolkit     # yoki repo'ni git submodule sifatida qo'shing

Keyin shu yerda uning TOOLS va dispatch'ini core/ai_tools.py'dagi asosiy
TOOLS/DISPATCH ro'yxatiga qo'shib qo'yasiz (birlashtirilgan bitta ro'yxat
AI'ga tools= sifatida uzatiladi).
"""
# from ms_toolkit import TOOLS as FILE_TOOLS, dispatch as file_dispatch

FILE_TOOLS: list[dict] = []  # TODO: ms_toolkit o'rnatilgach yuqoridagi import bilan almashtiring


async def file_dispatch(name: str, args: dict) -> dict:
    raise NotImplementedError("ms-file-toolkit hali ulanmagan — README'ga qarang")
