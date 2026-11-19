# -*- coding: utf-8 -*-
"""Render the course report markdown to DOCX and PDF, with a two-pass table of contents.

Usage:  python build_v11.py [body.md] [out_stem]
The markdown is the single editing entry; the DOCX is produced from it and the PDF
is exported from the same DOCX by LibreOffice, so the two deliverables stay in sync.
"""
import json
import os
import re
import subprocess
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BODY = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'body.md')
STEM = sys.argv[2] if len(sys.argv) > 2 else '潘道熙25361130课程设计报告题目二'

TITLE = '一条通道上的两支队伍'
SUBTITLE = '题目二　空地协同无人系统对抗靶场设计'
COURSE = '《无人系统导论》课程设计'

BODY_FONT = '宋体'
HEAD_FONT = 'Noto Sans CJK SC'
LATIN = 'Times New Roman'


# ---------------------------------------------------------------- docx helpers
def _fonts(run, eastasia):
    run.font.name = LATIN
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rpr.insert(0, rf)
    rf.set(qn('w:eastAsia'), eastasia)
    rf.set(qn('w:ascii'), LATIN)
    rf.set(qn('w:hAnsi'), LATIN)


def para(doc, text, size=11, bold=False, align=None, first_indent=True,
         font=BODY_FONT, space_before=0, space_after=5, line=1.30):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line
    if first_indent and align is None:
        p.paragraph_format.first_line_indent = Cm(0.74)
    if align is not None:
        p.alignment = align
    for i, chunk in enumerate(re.split(r'(\*\*.+?\*\*)', text)):
        if not chunk:
            continue
        strong = chunk.startswith('**') and chunk.endswith('**') and len(chunk) > 4
        run = p.add_run(chunk[2:-2] if strong else chunk)
        run.font.size = Pt(size)
        run.bold = bold or strong
        _fonts(run, font)
    return p


def heading(doc, text, level):
    sizes = {1: 15, 2: 12, 3: 11}
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(14 if level == 1 else 10)
    pf.space_after = Pt(6 if level == 1 else 4)
    pf.keep_with_next = True
    if text.startswith("7.4 "):
        p.paragraph_format.page_break_before = True
    run = p.add_run(text)
    run.font.size = Pt(sizes.get(level, 11))
    run.bold = True
    run.font.color.rgb = RGBColor(0x1a, 0x1a, 0x1a)
    _fonts(run, HEAD_FONT)
    # outline level so Word's navigation pane and bookmarks work
    ppr = p._p.get_or_add_pPr()
    ol = OxmlElement('w:outlineLvl')
    ol.set(qn('w:val'), str(level - 1))
    ppr.append(ol)
    return p


def shade(cell, fill):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    tcpr.append(shd)


def repeat_header(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement('w:tblHeader')
    el.set(qn('w:val'), 'true')
    trpr.append(el)


def table(doc, rows, caption=None):
    if caption:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(caption)
        run.font.size = Pt(9)
        run.bold = True
        _fonts(run, BODY_FONT)
    ncol = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=ncol)
    t.style = 'Table Grid'
    t.alignment = 1
    scoring = caption and '百分制自评' in caption
    if scoring:
        t.autofit = False
        for column, width in zip(t.columns, (3.7, 1.4, 1.4, 9.3)):
            column.width = Cm(width)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        if scoring:
            for cell, column in zip(cells, t.columns):
                cell.width = column.width
        for ci in range(ncol):
            text = row[ci] if ci < len(row) else ''
            cell = cells[ci]
            cell.text = ''
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.keep_with_next = ri == 0 or (len(rows) <= 7 and ri < len(rows) - 1)
            for chunk in re.split(r'(\*\*.+?\*\*)', text):
                if not chunk:
                    continue
                strong = chunk.startswith('**') and chunk.endswith('**') and len(chunk) > 4
                run = p.add_run(chunk[2:-2] if strong else chunk)
                run.font.size = Pt(9.2)
                run.bold = strong or ri == 0
                _fonts(run, BODY_FONT)
            if ri == 0:
                shade(cell, 'EDF1F5')
    repeat_header(t.rows[0])
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(4)
    sp.paragraph_format.line_spacing = 1.0
    return t


def figure(doc, path, caption):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    if os.path.exists(path):
        p.add_run().add_picture(path, width=Cm(14.8))
    else:
        run = p.add_run('[missing figure: %s]' % os.path.basename(path))
        run.font.size = Pt(9)
        _fonts(run, BODY_FONT)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(8)
    run = cap.add_run(caption)
    run.font.size = Pt(9)
    _fonts(run, BODY_FONT)


def field(par, instr):
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), instr)
    r = OxmlElement('w:r')
    t = OxmlElement('w:t')
    t.text = '1'
    r.append(t)
    fld.append(r)
    par._p.append(fld)


# ---------------------------------------------------------------- md parsing
IMG = re.compile(r'^!\[(.*?)\]\((.*?)\)\s*$')
CAP = re.compile(r'^\*\*(表\s*(?:[A-Z]\.\d+|\d+)[^*]*)\*\*\s*$')


def parse(md_path):
    lines = open(md_path, encoding='utf-8').read().split('\n')
    blocks = []
    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        if not s.strip():
            i += 1
            continue
        m = IMG.match(s.strip())
        if m:
            blocks.append(('fig', m.group(1).strip(), m.group(2).strip()))
            i += 1
            continue
        if s.lstrip().startswith('|'):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                raw = lines[i].strip().strip('|')
                cells = [c.strip() for c in raw.split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(('table', rows))
            continue
        if s.startswith('#### '):
            blocks.append(('h', s[5:].strip(), 4))
        elif s.startswith('### '):
            blocks.append(('h', s[4:].strip(), 3))
        elif s.startswith('## '):
            blocks.append(('h', s[3:].strip(), 2))
        elif s.startswith('# '):
            blocks.append(('h', s[2:].strip(), 1))
        else:
            m = CAP.match(s.strip())
            if m:
                blocks.append(('cap', m.group(1).strip()))
            else:
                blocks.append(('p', s.strip()))
        i += 1
    return blocks


# ---------------------------------------------------------------- document
def build(blocks, pages=None):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(2.4), Cm(2.2)
    sec.left_margin, sec.right_margin = Cm(2.6), Cm(2.4)
    sec.different_first_page_header_footer = True

    normal = doc.styles['Normal']
    normal.font.name = LATIN
    normal.font.size = Pt(10.5)
    rf = normal._element.get_or_add_rPr().find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        normal._element.get_or_add_rPr().insert(0, rf)
    rf.set(qn('w:eastAsia'), BODY_FONT)

    # footer page number
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run()
    run.font.size = Pt(9)
    _fonts(run, BODY_FONT)
    field(fp, 'PAGE')

    # Anchor the cover art to the first page while leaving its text editable.
    header = sec.first_page_header.paragraphs[0]
    picture = header.add_run().add_picture(
        os.path.join(ROOT, 'figures', 'cover-bg.png'),
        width=sec.page_width, height=sec.page_height,
    )
    inline = picture._inline
    anchor = OxmlElement('wp:anchor')
    for attr, value in (
        ('distT', '0'), ('distB', '0'), ('distL', '0'), ('distR', '0'),
        ('simplePos', '0'), ('relativeHeight', '0'), ('behindDoc', '1'),
        ('locked', '0'), ('layoutInCell', '1'), ('allowOverlap', '1'),
    ):
        anchor.set(attr, value)
    pos = OxmlElement('wp:simplePos')
    pos.set('x', '0')
    pos.set('y', '0')
    anchor.append(pos)
    for axis in ('H', 'V'):
        position = OxmlElement('wp:position' + axis)
        position.set('relativeFrom', 'page')
        offset = OxmlElement('wp:posOffset')
        offset.text = '0'
        position.append(offset)
        anchor.append(position)
    for tag in ('wp:extent', 'wp:effectExtent'):
        child = inline.find(qn(tag))
        if child is not None:
            anchor.append(child)
    anchor.append(OxmlElement('wp:wrapNone'))
    for child in list(inline):
        anchor.append(child)
    inline.getparent().replace(inline, anchor)

    for label, size, before, bold in (
        ('中山大学　智能工程学院', 16, 61, True),
        (COURSE, 11, 16, False),
        (TITLE, 25, 58, True),
        (SUBTITLE, 15, 14, False),
    ):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(size + 5)
        run = p.add_run(label)
        run.font.size = Pt(size)
        run.bold = bold
        _fonts(run, HEAD_FONT)

    for i, (key, value) in enumerate((
        ('课程名称', '无人系统导论'),
        ('学生姓名', '潘道熙'),
        ('学号', '25361130'),
        ('学院', '智能工程学院'),
        ('专业', '智能科学与技术'),
        ('年级', '2025 级'),
        ('提交日期', '2026 年 11 月'),
    )):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(2.95)
        p.paragraph_format.space_before = Pt(229 if i == 0 else 0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(30)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(6.45))
        for label, bold in ((key + '\t', True), (value, False)):
            run = p.add_run(label)
            run.font.size = Pt(12)
            run.bold = bold
            _fonts(run, BODY_FONT)

    p = sec.first_page_footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sec.footer_distance = Cm(1.65)
    run = p.add_run('中山大学')
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string('59655E')
    _fonts(run, BODY_FONT)

    # ---- table of contents
    doc.add_page_break()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('目　录')
    run.font.size = Pt(16)
    run.bold = True
    _fonts(run, HEAD_FONT)
    doc.add_paragraph()
    for text, level in [(b[1], b[2]) for b in blocks if b[0] == 'h' and b[2] <= 2]:
        line = doc.add_paragraph()
        line.paragraph_format.space_after = Pt(2)
        line.paragraph_format.line_spacing = 1.05
        indent = Cm(0.0) if level == 1 else Cm(0.75)
        line.paragraph_format.left_indent = indent
        tab_stops = line.paragraph_format.tab_stops
        tab_stops.add_tab_stop(Cm(15.4), 2, 1)  # right aligned, dot leader
        run = line.add_run(text)
        run.font.size = Pt(10.5 if level == 1 else 10)
        run.bold = level == 1
        _fonts(run, BODY_FONT)
        no = str((pages or {}).get(text, ''))
        run = line.add_run('\t' + no)
        run.font.size = Pt(10)
        _fonts(run, BODY_FONT)

    # ---- body
    doc.add_page_break()
    pending_cap = None
    for b in blocks:
        kind = b[0]
        if kind == 'h':
            if b[2] == 1 and b[1] not in ('摘要', '3 多体协同与仿生启发'):
                doc.add_page_break()
            heading(doc, b[1], b[2])
        elif kind == 'p':
            para(doc, b[1])
        elif kind == 'cap':
            pending_cap = b[1]
            continue
        elif kind == 'fig':
            figure(doc, os.path.join(ROOT, b[2]), b[1])
        elif kind == 'table':
            table(doc, b[1], caption=pending_cap)
            pending_cap = None
            continue
        if pending_cap:
            para(doc, pending_cap, size=9, bold=True,
                 align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False)
            pending_cap = None
    return doc


def to_pdf(docx_path, outdir):
    subprocess.run(['soffice', '-env:UserInstallation=file://' + outdir + '/.lo-profile', '--headless', '--convert-to', 'pdf',
                    '--outdir', outdir, docx_path],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + '.pdf')


def page_map(pdf, blocks):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'],
                         check=True, stdout=subprocess.PIPE).stdout.decode('utf-8')
    pages = txt.split('\f')
    norm = lambda s: re.sub(r'\s+', '', s)
    # the table of contents repeats every heading, so the scan has to start at the
    # first page whose leading line is the abstract heading, not at page 1
    start = 1
    for idx, page in enumerate(pages, start=1):
        lines = [l.strip() for l in page.split('\n') if l.strip()]
        if lines and norm(lines[0]).startswith('摘要'):
            start = idx
            break
    out = {}
    for b in blocks:
        if b[0] != 'h' or b[2] > 2:
            continue
        key = norm(b[1])[:18]
        if not key:
            continue
        for idx in range(start, len(pages) + 1):
            heads = [norm(l) for l in pages[idx - 1].split('\n') if l.strip()]
            if any(h.startswith(key) for h in heads):
                out[b[1]] = idx
                break
    return out


def main():
    blocks = parse(BODY)
    docx1 = os.path.join(ROOT, '_pass1.docx')
    build(blocks).save(docx1)
    pdf1 = to_pdf(docx1, ROOT)
    pages = page_map(pdf1, blocks)
    docx2 = os.path.join(ROOT, STEM + '.docx')
    build(blocks, pages).save(docx2)
    pdf2 = to_pdf(docx2, ROOT)
    info = subprocess.run(['pdfinfo', pdf2], stdout=subprocess.PIPE).stdout.decode()
    npages = [l for l in info.split('\n') if l.startswith('Pages')]
    print('cjk chars:', len(re.findall(r'[\u4e00-\u9fff]', open(BODY, encoding='utf-8').read())))
    print('parsed blocks:', len(blocks),
          'tables:', sum(1 for b in blocks if b[0] == 'table'),
          'figures:', sum(1 for b in blocks if b[0] == 'fig'))
    print('toc entries resolved:', len(pages))
    print(npages[0] if npages else 'pages unknown')
    print('docx:', docx2, os.path.getsize(docx2), 'bytes')
    print('pdf :', pdf2, os.path.getsize(pdf2), 'bytes')


if __name__ == '__main__':
    main()
