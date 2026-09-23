"""
AI ko'pincha oddiy Markdown formatida javob beradi (**qalin**, `kod`,
```kod bloki```, [link](url), # Sarlavha), lekin bizning bot HTML
parse_mode'da ishlaydi — bular mos kelmaydi (natijada "**so'z**" literal
yulduzchalar bilan ko'rinadi). Bu — deyarli barcha Telegram AI-botlarida
ishlatiladigan standart yechim: AI matnini yuborishdan OLDIN Markdown'dan
Telegram HTML'ga konvertatsiya qilamiz.
"""
import html as html_lib
import re


def markdown_to_telegram_html(text: str) -> str:
    if not text:
        return text

    # 1) Avval HTML maxsus belgilarini escape qilamiz (xavfsizlik + <b> kabi
    #    o'z teglarimiz bilan aralashib ketmasligi uchun)
    text = html_lib.escape(text, quote=False)

    # 2) Kod bloklari/inline kodni vaqtincha ajratib olamiz — ichida boshqa
    #    formatlash (masalan kod ichidagi **belgisi) qo'llanmasligi uchun
    code_blocks: list[str] = []

    def _stash_block(m):
        code_blocks.append(m.group(1).strip("\n"))
        return f"\x00BLOCK{len(code_blocks)-1}\x00"

    text = re.sub(r"```(?:\w+\n)?(.*?)```", _stash_block, text, flags=re.DOTALL)

    inline_codes: list[str] = []

    def _stash_inline(m):
        inline_codes.append(m.group(1))
        return f"\x00INLINE{len(inline_codes)-1}\x00"

    text = re.sub(r"`([^`\n]+?)`", _stash_inline, text)

    # 3) Qalin: **matn** yoki __matn__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # 4) Kursiv: *matn* yoki _matn_ (qalin'dan KEYIN, aks holda **ni buzadi)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", text)

    # 5) Linklar: [matn](url)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)

    # 6) Sarlavhalar (# ## ### ...) -> qalin qator (Telegram'da <h1> yo'q)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 7) Kod bloklarini qaytarib qo'yamiz
    for i, code in enumerate(code_blocks):
        text = text.replace(f"\x00BLOCK{i}\x00", f"<pre>{code}</pre>")
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", f"<code>{code}</code>")

    return text
