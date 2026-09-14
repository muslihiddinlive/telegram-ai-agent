"""
python-pptx yordamida slaydlarga matn, native grafiklar (pie/bar/line/donut) va
qo'lda chiziladigan diagrammalar (flowchart, orgchart, venn, timeline) qo'shadigan
funksiyalar to'plami.

Dizayn qoidalari (barcha funksiyalarda amal qilinadi):
- Oq fon, iliq/krem foнлardan qochamiz.
- Sarlavhalar katta va qalin (32-40pt), asosiy matn 16-20pt.
- Accent chiziq/bar ishlatilmaydi — bo'shliq va rang bilan ажратамиз.
- Bitta izchil rang palitrasi.
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION

# ---------------------------------------------------------------------------
# RANG PALITRASI (professional, ko'k-yashil ohangda)
# ---------------------------------------------------------------------------
COLOR_BG = RGBColor(0xFF, 0xFF, 0xFF)
COLOR_TITLE = RGBColor(0x1A, 0x1A, 0x2E)          # deyarli qora-ko'k
COLOR_TEXT = RGBColor(0x3A, 0x3A, 0x4A)
COLOR_ACCENT = RGBColor(0x16, 0x6D, 0x7C)          # teal
COLOR_ACCENT_LIGHT = RGBColor(0xE3, 0xF2, 0xF3)    # och teal (fon uchun)
COLOR_ACCENT2 = RGBColor(0xE8, 0x7B, 0x3E)         # to'q sariq (kontrast uchun)
COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CHART_PALETTE = [0x16_6D_7C, 0xE8_7B_3E, 0x4C_A6_A8, 0xF2_C1_4E, 0x8E_44_AD, 0x2E_86_AB]

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def new_presentation() -> Presentation:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def _blank_slide(prs: Presentation):
    layout = prs.slide_layouts[6]  # to'liq bo'sh layout
    slide = prs.slides.add_slide(layout)
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = COLOR_BG
    return slide


def _add_title(slide, text: str, top=Inches(0.5)):
    box = slide.shapes.add_textbox(Inches(0.7), top, Inches(11.9), Inches(1.0))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(34)
    p.font.bold = True
    p.font.color.rgb = COLOR_TITLE
    p.font.name = "Calibri"
    return box


def _set_run(run, size=18, color=COLOR_TEXT, bold=False, name="Calibri"):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = name


def add_footer(slide, page_num: int, total: int, brand: str = ""):
    """Har bir slaydning pastki qismiga sahifa raqamini (va ixtiyoriy brend
    matnini) qo'shadi — professional taqdimotlarga xos yakuniy detal."""
    box = slide.shapes.add_textbox(Inches(0.5), Inches(7.08), Inches(3.5), Inches(0.35))
    tf = box.text_frame
    p = tf.paragraphs[0]
    p.text = brand
    p.font.size = Pt(10)
    p.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)
    p.font.name = "Calibri"

    num_box = slide.shapes.add_textbox(Inches(12.4), Inches(7.08), Inches(0.7), Inches(0.35))
    ntf = num_box.text_frame
    np = ntf.paragraphs[0]
    np.alignment = PP_ALIGN.RIGHT
    np.text = f"{page_num}/{total}"
    np.font.size = Pt(10)
    np.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)
    np.font.name = "Calibri"


# ---------------------------------------------------------------------------
# 1) TITLE SLIDE
# ---------------------------------------------------------------------------

def add_title_slide(prs: Presentation, title: str, subtitle: str = ""):
    slide = _blank_slide(prs)

    # Fon uchun subtle accent panel (chiziq emas, katta shakl)
    panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), SLIDE_W, Inches(7.5))
    panel.fill.solid()
    panel.fill.fore_color.rgb = COLOR_BG
    panel.line.fill.background()
    panel.shadow.inherit = False

    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(9.5), Inches(-2.5), Inches(7), Inches(7))
    circle.fill.solid()
    circle.fill.fore_color.rgb = COLOR_ACCENT_LIGHT
    circle.line.fill.background()
    circle.shadow.inherit = False

    box = slide.shapes.add_textbox(Inches(0.9), Inches(2.7), Inches(9.5), Inches(1.6))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = COLOR_TITLE
    p.font.name = "Calibri"

    if subtitle:
        sbox = slide.shapes.add_textbox(Inches(0.95), Inches(3.9), Inches(9.5), Inches(0.8))
        stf = sbox.text_frame
        stf.word_wrap = True
        sp = stf.paragraphs[0]
        sp.text = subtitle
        sp.font.size = Pt(20)
        sp.font.color.rgb = COLOR_ACCENT
        sp.font.name = "Calibri"

    return slide


# ---------------------------------------------------------------------------
# 2) CONTENT (BULLET) SLIDE
# ---------------------------------------------------------------------------

def add_bullet_slide(prs: Presentation, title: str, bullets: list[str]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    box = slide.shapes.add_textbox(Inches(0.9), Inches(1.8), Inches(11.3), Inches(5.0))
    tf = box.text_frame
    tf.word_wrap = True

    for i, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"●  {bullet}"
        p.font.size = Pt(20)
        p.font.color.rgb = COLOR_TEXT
        p.font.name = "Calibri"
        p.space_after = Pt(18)

    return slide


# ---------------------------------------------------------------------------
# 3) NATIVE CHART SLIDE (pie / bar / line / donut)
# ---------------------------------------------------------------------------

_CHART_TYPE_MAP = {
    "pie": XL_CHART_TYPE.PIE,
    "donut": XL_CHART_TYPE.DOUGHNUT,
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
}


def add_chart_slide(prs: Presentation, title: str, chart_type: str,
                     categories: list[str], series_name: str, values: list[float]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    chart_data = CategoryChartData()
    chart_data.categories = categories
    chart_data.add_series(series_name, values)

    xl_type = _CHART_TYPE_MAP.get(chart_type, XL_CHART_TYPE.PIE)

    x, y, cx, cy = Inches(1.8), Inches(1.7), Inches(9.7), Inches(5.3)
    graphic_frame = slide.shapes.add_chart(xl_type, x, y, cx, cy, chart_data)
    chart = graphic_frame.chart

    chart.has_title = False

    is_pie_like = chart_type in ("pie", "donut")
    chart.has_legend = is_pie_like
    if is_pie_like:
        chart.legend.position = XL_LEGEND_POSITION.RIGHT
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(14)

    plot = chart.plots[0]
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size = Pt(13)
    dl.font.color.rgb = COLOR_WHITE if is_pie_like else COLOR_TEXT
    if is_pie_like:
        dl.number_format = '0%'
        dl.number_format_is_linked = False
        dl.show_percentage = True
        dl.show_value = False
    else:
        dl.show_value = True
        dl.position = XL_LABEL_POSITION.OUTSIDE_END if chart_type == "bar" else XL_LABEL_POSITION.ABOVE

    # Ranglarni palette bo'yicha qo'lda belgilash
    for i, point in enumerate(plot.series[0].points if is_pie_like else []):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = RGBColor.from_string(f"{CHART_PALETTE[i % len(CHART_PALETTE)]:06X}")

    if not is_pie_like:
        series = plot.series[0]
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = COLOR_ACCENT
        if chart_type == "line":
            series.format.line.color.rgb = COLOR_ACCENT
            series.format.line.width = Pt(3)
        chart.category_axis.tick_labels.font.size = Pt(13)
        chart.value_axis.tick_labels.font.size = Pt(13)
        chart.category_axis.format.line.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xEE, 0xEE, 0xEE)

    return slide


# ---------------------------------------------------------------------------
# 4) FLOWCHART (jarayon bosqichlari — qutichalar + strelkalar)
# ---------------------------------------------------------------------------

def add_flowchart_slide(prs: Presentation, title: str, steps: list[str]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    n = len(steps)
    max_per_row = 4
    rows = [steps[i:i + max_per_row] for i in range(0, n, max_per_row)]

    top = Inches(2.2)
    row_h = Inches(2.0)
    margin = Inches(0.8)
    available_w = SLIDE_W - 2 * margin

    for r, row_steps in enumerate(rows):
        count = len(row_steps)
        box_w = Inches(2.3)
        gap = Emu(int((available_w - box_w * count) / max(count, 1))) if count > 1 else Emu(0)
        # markazlashtirish uchun boshlanish x sini hisoblash
        total_w = box_w * count + gap * max(count - 1, 0)
        start_x = Emu(int((SLIDE_W - total_w) / 2))
        y = Emu(int(top) + r * int(row_h))

        prev_shape = None
        for i, step_text in enumerate(row_steps):
            x = Emu(int(start_x) + i * (int(box_w) + int(gap)))
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, box_w, Inches(1.1))
            shape.fill.solid()
            shape.fill.fore_color.rgb = COLOR_ACCENT if (r * max_per_row + i) % 2 == 0 else COLOR_ACCENT2
            shape.line.fill.background()
            shape.shadow.inherit = False
            tf = shape.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            p.text = f"{r * max_per_row + i + 1}. {step_text}"
            p.font.size = Pt(15)
            p.font.bold = True
            p.font.color.rgb = COLOR_WHITE
            p.font.name = "Calibri"

            if prev_shape is not None:
                connector = slide.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT,
                    Emu(int(prev_shape.left) + int(prev_shape.width)), Emu(int(prev_shape.top) + int(prev_shape.height) // 2),
                    x, Emu(int(y) + int(Inches(1.1)) // 2),
                )
                connector.line.color.rgb = COLOR_TEXT
                connector.line.width = Pt(2.25)
                _set_arrowhead(connector)

            prev_shape = shape

    return slide


def _set_arrowhead(connector_shape):
    """Connector oxiriga o'q belgisi (arrowhead) qo'shadi — python-pptx buni to'g'ridan-to'g'ri
    qo'llab-quvvatlamaydi, shu sabab XML orqali qo'shamiz."""
    from pptx.oxml.ns import qn
    ln = connector_shape.line._get_or_add_ln()
    tail_end = ln.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'})
    ln.append(tail_end)


# ---------------------------------------------------------------------------
# 5) ORGCHART / HIERARCHY (bosh element -> bir nechta pastki elementlar)
# ---------------------------------------------------------------------------

def add_orgchart_slide(prs: Presentation, title: str, root: str, children: list[str]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    # ROOT box
    root_w, root_h = Inches(3.2), Inches(0.9)
    root_x = Emu(int((SLIDE_W - root_w) / 2))
    root_y = Inches(1.9)
    root_shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, root_x, root_y, root_w, root_h)
    root_shape.fill.solid()
    root_shape.fill.fore_color.rgb = COLOR_TITLE
    root_shape.line.fill.background()
    root_shape.shadow.inherit = False
    tf = root_shape.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    p.text = root
    p.font.size = Pt(18)
    p.font.bold = True
    p.font.color.rgb = COLOR_WHITE

    n = len(children)
    child_w, child_h = Inches(2.6), Inches(1.0)
    gap = Inches(0.35)
    total_w = child_w * n + gap * max(n - 1, 0)
    start_x = Emu(int((SLIDE_W - total_w) / 2))
    child_y = Inches(4.0)

    root_center_x = Emu(int(root_x) + int(root_w) // 2)
    root_bottom_y = Emu(int(root_y) + int(root_h))

    for i in range(n):
        x = Emu(int(start_x) + i * (int(child_w) + int(gap)))
        # vertikal chiziq: root pastidan pastga, keyin gorizontal, keyin child yuqorisiga
        child_center_x = Emu(int(x) + int(child_w) // 2)

        connector = slide.shapes.add_connector(
            MSO_CONNECTOR.ELBOW, root_center_x, root_bottom_y, child_center_x, child_y
        )
        connector.line.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)
        connector.line.width = Pt(1.75)

        child_shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, child_y, child_w, child_h)
        child_shape.fill.solid()
        child_shape.fill.fore_color.rgb = CHART_PALETTE_COLOR(i)
        child_shape.line.fill.background()
        child_shape.shadow.inherit = False
        ctf = child_shape.text_frame
        ctf.word_wrap = True
        ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
        cp = ctf.paragraphs[0]
        cp.alignment = PP_ALIGN.CENTER
        cp.text = children[i]
        cp.font.size = Pt(15)
        cp.font.bold = True
        cp.font.color.rgb = COLOR_WHITE

    return slide


def CHART_PALETTE_COLOR(i: int) -> RGBColor:
    return RGBColor.from_string(f"{CHART_PALETTE[i % len(CHART_PALETTE)]:06X}")


# ---------------------------------------------------------------------------
# 6) VENN DIAGRAM (ikkita to'plamning kesishishi)
# ---------------------------------------------------------------------------

def add_venn_slide(prs: Presentation, title: str, set_a: str, set_b: str, overlap: str):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    circle_w = Inches(5.2)
    circle_h = Inches(5.2)
    y = Inches(1.9)
    overlap_gap = Inches(1.9)  # qancha bir-biriga kirib borishi

    left_x = Inches(2.3)
    right_x = Emu(int(left_x) + int(circle_w) - int(overlap_gap))

    circle_a = slide.shapes.add_shape(MSO_SHAPE.OVAL, left_x, y, circle_w, circle_h)
    circle_a.fill.solid()
    circle_a.fill.fore_color.rgb = COLOR_ACCENT
    circle_a.fill.transparency = 0
    circle_a.line.color.rgb = COLOR_WHITE
    circle_a.line.width = Pt(2)
    circle_a.shadow.inherit = False
    _set_transparency(circle_a, 35)

    circle_b = slide.shapes.add_shape(MSO_SHAPE.OVAL, right_x, y, circle_w, circle_h)
    circle_b.fill.solid()
    circle_b.fill.fore_color.rgb = COLOR_ACCENT2
    circle_b.line.color.rgb = COLOR_WHITE
    circle_b.line.width = Pt(2)
    circle_b.shadow.inherit = False
    _set_transparency(circle_b, 35)

    # Label matnlari (doiralar ustidan alohida textbox bilan, aniq joylashuv uchun)
    label_a = slide.shapes.add_textbox(Emu(int(left_x)), Emu(int(y) + int(circle_h) // 2 - int(Inches(0.9))), Inches(2.6), Inches(1.2))
    _center_text(label_a, set_a, size=18, bold=True, color=COLOR_WHITE)

    label_b = slide.shapes.add_textbox(Emu(int(right_x) + int(circle_w) - int(Inches(2.6))), Emu(int(y) + int(circle_h) // 2 - int(Inches(0.9))), Inches(2.6), Inches(1.2))
    _center_text(label_b, set_b, size=18, bold=True, color=COLOR_WHITE)

    overlap_x = Emu(int(right_x))
    overlap_box = slide.shapes.add_textbox(overlap_x, Emu(int(y) + int(circle_h) // 2 - int(Inches(0.7))), overlap_gap, Inches(1.4))
    _center_text(overlap_box, overlap, size=13, bold=True, color=COLOR_TITLE)

    return slide


def _set_transparency(shape, pct: int):
    """Shape fill uchun transparency foizini (0-100) belgilaydi (python-pptx to'g'ridan-to'g'ri
    qo'llamaydi, XML orqali)."""
    from pptx.oxml.ns import qn
    sp = shape.fill.fore_color._xFill
    alpha = str(int((100 - pct) * 1000))
    srgbClr = sp.find(qn('a:srgbClr'))
    if srgbClr is not None:
        a = srgbClr.makeelement(qn('a:alpha'), {'val': alpha})
        srgbClr.append(a)


def _center_text(textbox, text, size=16, bold=False, color=COLOR_TEXT):
    tf = textbox.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color


# ---------------------------------------------------------------------------
# 7) TIMELINE (vaqt bo'yicha voqealar)
# ---------------------------------------------------------------------------

def add_timeline_slide(prs: Presentation, title: str, events: list[dict]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    n = len(events)
    margin = Inches(1.0)
    line_y = Inches(4.0)
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, margin, line_y, Emu(int(SLIDE_W) - int(margin)), line_y)
    line.line.color.rgb = COLOR_ACCENT
    line.line.width = Pt(3)

    usable_w = int(SLIDE_W) - 2 * int(margin)
    step = usable_w // max(n - 1, 1) if n > 1 else 0

    for i, ev in enumerate(events):
        cx = int(margin) + i * step if n > 1 else int(SLIDE_W) // 2
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(cx - int(Inches(0.15))), Emu(int(line_y) - int(Inches(0.15))), Inches(0.3), Inches(0.3))
        dot.fill.solid()
        dot.fill.fore_color.rgb = CHART_PALETTE_COLOR(i)
        dot.line.color.rgb = COLOR_WHITE
        dot.line.width = Pt(2)
        dot.shadow.inherit = False

        above = i % 2 == 0
        date_y = Emu(int(line_y) - int(Inches(1.3))) if above else Emu(int(line_y) + int(Inches(0.35)))
        label_y = Emu(int(line_y) - int(Inches(0.85))) if above else Emu(int(line_y) + int(Inches(0.85)))

        connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(cx), Emu(int(line_y)), Emu(cx), Emu(int(line_y) + (-int(Inches(0.45)) if above else int(Inches(0.45)))))
        connector.line.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
        connector.line.width = Pt(1.5)

        date_box = slide.shapes.add_textbox(Emu(cx - int(Inches(1.0))), date_y, Inches(2.0), Inches(0.5))
        _center_text(date_box, ev.get("date", ""), size=15, bold=True, color=COLOR_ACCENT)

        label_box = slide.shapes.add_textbox(Emu(cx - int(Inches(1.1))), label_y, Inches(2.2), Inches(1.0))
        _center_text(label_box, ev.get("label", ""), size=13, bold=False, color=COLOR_TEXT)

    return slide


# ---------------------------------------------------------------------------
# 8) SECTION DIVIDER (uzun prezentatsiyalarda bo'limlar orasidagi ajratuvchi)
# ---------------------------------------------------------------------------

def add_section_slide(prs: Presentation, title: str, subtitle: str = ""):
    slide = _blank_slide(prs)

    panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), SLIDE_W, SLIDE_H)
    panel.fill.solid()
    panel.fill.fore_color.rgb = COLOR_TITLE
    panel.line.fill.background()
    panel.shadow.inherit = False

    accent_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(3.15), Inches(0.9), Inches(0.12))
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = COLOR_ACCENT2
    accent_bar.line.fill.background()
    accent_bar.shadow.inherit = False

    box = slide.shapes.add_textbox(Inches(0.9), Inches(3.4), Inches(11.5), Inches(1.4))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = COLOR_WHITE
    p.font.name = "Calibri"

    if subtitle:
        sbox = slide.shapes.add_textbox(Inches(0.95), Inches(4.4), Inches(10.5), Inches(0.8))
        stf = sbox.text_frame
        stf.word_wrap = True
        sp = stf.paragraphs[0]
        sp.text = subtitle
        sp.font.size = Pt(18)
        sp.font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
        sp.font.name = "Calibri"

    return slide


# ---------------------------------------------------------------------------
# 9) STAT / RAQAM SLIDE (2-4 ta katta ko'rsatkich yonma-yon)
# ---------------------------------------------------------------------------

def add_stat_slide(prs: Presentation, title: str, stats: list[dict]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    n = max(len(stats), 1)
    card_w = Inches(2.7)
    gap = Inches(0.5)
    total_w = card_w * n + gap * (n - 1)
    start_x = Emu(int((SLIDE_W - total_w) / 2))
    y = Inches(2.6)
    card_h = Inches(2.6)

    for i, stat in enumerate(stats):
        x = Emu(int(start_x) + i * (int(card_w) + int(gap)))
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, card_w, card_h)
        card.fill.solid()
        card.fill.fore_color.rgb = COLOR_ACCENT_LIGHT
        card.line.fill.background()
        card.shadow.inherit = False

        num_box = slide.shapes.add_textbox(x, Emu(int(y) + int(Inches(0.4))), card_w, Inches(1.2))
        _center_text(num_box, str(stat.get("number", "")), size=40, bold=True, color=CHART_PALETTE_COLOR(i))

        label_box = slide.shapes.add_textbox(Emu(int(x) + int(Inches(0.15))), Emu(int(y) + int(Inches(1.6))),
                                              Emu(int(card_w) - int(Inches(0.3))), Inches(0.8))
        _center_text(label_box, stat.get("label", ""), size=14, bold=False, color=COLOR_TEXT)

    return slide


# ---------------------------------------------------------------------------
# 10) QUOTE / IQTIBOS SLIDE
# ---------------------------------------------------------------------------

def add_quote_slide(prs: Presentation, quote: str, author: str = ""):
    slide = _blank_slide(prs)

    mark = slide.shapes.add_textbox(Inches(1.0), Inches(1.3), Inches(1.5), Inches(1.5))
    mtf = mark.text_frame
    mp = mtf.paragraphs[0]
    mp.text = "\u201C"
    mp.font.size = Pt(90)
    mp.font.bold = True
    mp.font.color.rgb = COLOR_ACCENT_LIGHT
    mp.font.name = "Georgia"

    box = slide.shapes.add_textbox(Inches(1.4), Inches(2.6), Inches(10.5), Inches(2.6))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = quote
    p.font.size = Pt(28)
    p.font.italic = True
    p.font.color.rgb = COLOR_TITLE
    p.font.name = "Calibri"

    if author:
        abox = slide.shapes.add_textbox(Inches(1.4), Inches(5.4), Inches(8.0), Inches(0.6))
        atf = abox.text_frame
        ap = atf.paragraphs[0]
        ap.text = f"— {author}"
        ap.font.size = Pt(18)
        ap.font.bold = True
        ap.font.color.rgb = COLOR_ACCENT
        ap.font.name = "Calibri"

    return slide


# ---------------------------------------------------------------------------
# 11) COMPARISON / TAQQOSLASH SLIDE (ikkita ustunni bir-biriga solishtirish)
# ---------------------------------------------------------------------------

def add_comparison_slide(prs: Presentation, title: str,
                          left_title: str, left_items: list[str],
                          right_title: str, right_items: list[str]):
    slide = _blank_slide(prs)
    _add_title(slide, title)

    col_w = Inches(5.6)
    col_h = Inches(4.7)
    y = Inches(1.9)
    gap = Inches(0.5)
    left_x = Inches(0.9)
    right_x = Emu(int(left_x) + int(col_w) + int(gap))

    for x, header, items, color in (
        (left_x, left_title, left_items, COLOR_ACCENT),
        (right_x, right_title, right_items, COLOR_ACCENT2),
    ):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, col_w, col_h)
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(0xF7, 0xF8, 0xF9)
        card.line.color.rgb = color
        card.line.width = Pt(1.5)
        card.shadow.inherit = False

        header_box = slide.shapes.add_textbox(Emu(int(x) + int(Inches(0.3))), Emu(int(y) + int(Inches(0.25))),
                                               Emu(int(col_w) - int(Inches(0.6))), Inches(0.6))
        htf = header_box.text_frame
        hp = htf.paragraphs[0]
        hp.text = header
        hp.font.size = Pt(20)
        hp.font.bold = True
        hp.font.color.rgb = color

        items_box = slide.shapes.add_textbox(Emu(int(x) + int(Inches(0.3))), Emu(int(y) + int(Inches(1.0))),
                                              Emu(int(col_w) - int(Inches(0.6))), Emu(int(col_h) - int(Inches(1.2))))
        itf = items_box.text_frame
        itf.word_wrap = True
        for i, item in enumerate(items):
            ip = itf.paragraphs[0] if i == 0 else itf.add_paragraph()
            ip.text = f"✓  {item}"
            ip.font.size = Pt(16)
            ip.font.color.rgb = COLOR_TEXT
            ip.space_after = Pt(14)

    return slide
