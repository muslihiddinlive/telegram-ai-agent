"""
groq-pptx-bot/pptx_builder.py patternidan — lekin bu yerda slide-strukturasini
alohida Groq so'rovi bilan emas, AI'ning to'g'ridan-to'g'ri function-calling
argumentlari orqali oladi (ya'ni "create_presentation" tool chaqirilganda,
AI o'zi slide'lar ro'yxatini JSON argument sifatida generatsiya qiladi).

diagrams.py (groq-pptx-bot'dan to'liq ko'chirilgan) — past darajadagi
slide-yaratish funksiyalari.
"""
import os
import re
import time

import tools.diagrams as dg
from tools.file_tools import USER_FILES_ROOT
import core.bot_identity as bot_identity


def _safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"[\s]+", "_", text)
    return text[:60] or "presentation"


def _user_dir(user_id: int) -> str:
    path = os.path.join(USER_FILES_ROOT, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _brand_suffix() -> str:
    """Fayl NOMIGA qo'shiladigan brend (slaydga emas) — masalan '_by_ParadoksAiBot'."""
    username = bot_identity.get_username()
    return f"_by_{username}" if username else ""


def build_presentation(user_id: int, data: dict) -> str:
    """
    :param data: {"title", "subtitle", "slides": [...], "dark_theme": bool}
                 (AI create_presentation tool'ini chaqirganda shu formatda beradi)
    :return: yaratilgan .pptx faylining to'liq yo'li

    dark_theme standart holatda TRUE — foydalanuvchi aniq "oddiy/light" demasa,
    "pro"/premium ko'rinish (to'q fon, ko'proq detal) standart hisoblanadi.
    """
    dg.set_theme(dark=data.get("dark_theme", True))

    prs = dg.new_presentation()
    brand = data.get("title", "")

    dg.add_title_slide(prs, data.get("title", "Prezentatsiya"), data.get("subtitle", ""))

    all_slides = data.get("slides", [])
    total = len(all_slides) + 1
    created_slides = []

    for slide_spec in all_slides:
        slide_type = slide_spec.get("type")
        title = slide_spec.get("title", "")

        try:
            if slide_type == "content":
                slide = dg.add_bullet_slide(prs, title, slide_spec.get("bullets", []))
            elif slide_type == "chart":
                slide = dg.add_chart_slide(
                    prs, title,
                    slide_spec.get("chart_type", "bar"),
                    slide_spec.get("categories", []),
                    slide_spec.get("series_name", "Ma'lumot"),
                    slide_spec.get("values", []),
                )
            elif slide_type == "flowchart":
                slide = dg.add_flowchart_slide(prs, title, slide_spec.get("steps", []))
            elif slide_type == "orgchart":
                slide = dg.add_orgchart_slide(
                    prs, title, slide_spec.get("root", ""), slide_spec.get("children", []),
                )
            elif slide_type == "venn":
                slide = dg.add_venn_slide(
                    prs, title,
                    slide_spec.get("set_a", "A"), slide_spec.get("set_b", "B"),
                    slide_spec.get("overlap", ""),
                )
            elif slide_type == "timeline":
                slide = dg.add_timeline_slide(prs, title, slide_spec.get("events", []))
            elif slide_type == "section":
                slide = dg.add_section_slide(prs, title, slide_spec.get("subtitle", ""))
            elif slide_type == "stat":
                slide = dg.add_stat_slide(prs, title, slide_spec.get("stats", []))
            elif slide_type == "quote":
                slide = dg.add_quote_slide(prs, slide_spec.get("quote", ""), slide_spec.get("author", ""))
            elif slide_type == "comparison":
                slide = dg.add_comparison_slide(
                    prs, title,
                    slide_spec.get("left_title", ""), slide_spec.get("left_items", []),
                    slide_spec.get("right_title", ""), slide_spec.get("right_items", []),
                )
            else:
                bullets = slide_spec.get("bullets") or [str(slide_spec)]
                slide = dg.add_bullet_slide(prs, title or "Slayd", bullets)

            created_slides.append(slide)

        except Exception as e:
            created_slides.append(dg.add_bullet_slide(prs, title or "Slayd", [f"(Xatolik: {e})"]))

    for i, slide in enumerate(created_slides, start=2):
        dg.add_footer(slide, i, total, brand)

    filename = f"{_safe_filename(data.get('title', 'prezentatsiya'))}{_brand_suffix()}_{int(time.time())}.pptx"
    filepath = os.path.join(_user_dir(user_id), filename)
    prs.save(filepath)
    return filepath


def build_diagram(user_id: int, data: dict) -> str:
    """:param data: {"diagram_type": ..., "dark_theme": bool, ...}"""
    dg.set_theme(dark=data.get("dark_theme", True))
    prs = dg.new_presentation()
    diagram_type = data.get("diagram_type")
    title = data.get("title", "Diagramma")

    if diagram_type == "chart":
        dg.add_chart_slide(
            prs, title, data.get("chart_type", "bar"),
            data.get("categories", []), data.get("series_name", "Ma'lumot"), data.get("values", []),
        )
    elif diagram_type == "flowchart":
        dg.add_flowchart_slide(prs, title, data.get("steps", []))
    elif diagram_type == "orgchart":
        dg.add_orgchart_slide(prs, title, data.get("root", ""), data.get("children", []))
    elif diagram_type == "venn":
        dg.add_venn_slide(prs, title, data.get("set_a", "A"), data.get("set_b", "B"), data.get("overlap", ""))
    elif diagram_type == "timeline":
        dg.add_timeline_slide(prs, title, data.get("events", []))
    else:
        raise ValueError(f"Noma'lum diagramma turi: {diagram_type}")

    filename = f"diagram_{_safe_filename(title)}{_brand_suffix()}_{int(time.time())}.pptx"
    filepath = os.path.join(_user_dir(user_id), filename)
    prs.save(filepath)
    return filepath
