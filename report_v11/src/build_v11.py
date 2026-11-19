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

ROOT = '/home/liujingzhi/pandaoxi/gongyu-ros2-gazebo/report_v11'
BODY = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'body.md')
STEM = sys.argv[2] if len(sys.argv) > 2 else '潘道熙25361130课程设计报告题目二_v11'

TITLE = '无人系统对抗靶场的设计与整机验证'
SUBTITLE = '题目二：空地协同靶场（6 台 UGV + 2 架 UAV）'
AUTHOR = '潘道熙　25361130'
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


def para(doc, text, size=10.5, bold=False, align=None, first_indent=True,
         font=BODY_FONT, space_before=0, space_after=4, line=1.23):
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
    if level == 1:
        p.paragraph_format.page_break_before = False
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
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci in range(ncol):
            text = row[ci] if ci < len(row) else ''
            cell = cells[ci]
            cell.text = ''
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.line_spacing = 1.0
            for chunk in re.split(r'(\*\*.+?\*\*)', text):
                if not chunk:
                    continue
                strong = chunk.startswith('**') and chunk.endswith('**') and len(chunk) > 4
                run = p.add_run(chunk[2:-2] if strong else chunk)
                run.font.size = Pt(8.5)
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
CAP = re.compile(r'^\*\*(表\s*\d+[^*]*)\*\*\s*$')


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

    # ---- cover
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(COURSE)
    run.font.size = Pt(14)
    _fonts(run, HEAD_FONT)
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(TITLE)
    run.font.size = Pt(26)
    run.bold = True
    _fonts(run, HEAD_FONT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(SUBTITLE)
    run.font.size = Pt(13)
    _fonts(run, HEAD_FONT)
    for _ in range(6):
        doc.add_paragraph()
    for line in (AUTHOR, '2026 年 11 月'):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(line)
        run.font.size = Pt(12)
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
            if b[2] == 1 and b[1] != '摘要':
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
    subprocess.run(['soffice', '--headless', '--convert-to', 'pdf',
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
