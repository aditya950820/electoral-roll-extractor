"""Flag-report PDF builders — framework-free (extracted from the old
ui_helpers so nothing here depends on the UI layer).

Three exports, all returning PDF/ZIP bytes:
  * build_flags_pdf     — every flag as a side-by-side A vs B comparison with
                          both photos, 5 comparisons per A4 page.
  * build_compare_pdf   — the model rules (fuzzy_new / cosine_new): each flag
                          prints the two voters AND the full per-attribute
                          comparison logic that produced it.
  * build_flags_pdf_zip — one PDF per constituency, bundled into a ZIP.
"""
from __future__ import annotations

from fraud_rules import (all_flags_for_export, flagged_constituencies,
                         get_photos)

_PDF_PER_PAGE = 5           # comparison blocks per A4 page
_A4 = (595.28, 841.89)      # points


def _pdf_voter_lines(f, side: str) -> list[str]:
    """The same fields the review card shows, one voter, as text lines."""
    g = lambda k: f.get(f"{k}_{side}")
    serial = g("serial")
    rel = f"{g('relation_type') or ''} {g('relation_name') or ''}".strip()
    return [
        (g("name") or "—"),
        f"EPIC: {g('epic') or 'no EPIC'}",
        f"AC {g('const') or '?'} · Part {g('part') or '?'} · "
        f"Serial {serial if serial is not None else '?'}",
        f"House {g('house') or '?'} · Age "
        f"{g('age') if g('age') is not None else '?'} · {g('gender') or '?'}",
        f"Relation: {rel or '—'}",
    ]


def _pdf_draw_voter(page, x: float, y: float, w: float, h: float,
                    lines: list[str], photo: bytes | None) -> None:
    """One voter panel: photo on the left, detail lines to its right."""
    import fitz
    pw, ph = 46, 56
    prect = fitz.Rect(x + 3, y + 3, x + 3 + pw, y + 3 + ph)
    if photo:
        try:
            page.insert_image(prect, stream=photo, keep_proportion=True)
        except Exception:
            page.draw_rect(prect, color=(.7, .7, .7), width=.5)
    else:
        page.draw_rect(prect, color=(.8, .8, .8), width=.5)
        page.insert_textbox(prect, "no\nphoto", fontsize=6,
                            color=(.5, .5, .5), align=fitz.TEXT_ALIGN_CENTER)
    trect = fitz.Rect(x + 3 + pw + 5, y + 1, x + w - 3, y + h - 1)
    page.insert_textbox(trect, lines[0] + "\n", fontsize=8, fontname="hebo")
    body = fitz.Rect(trect.x0, trect.y0 + 11, trect.x1, trect.y1)
    page.insert_textbox(body, "\n".join(lines[1:]), fontsize=7, fontname="helv")


def build_flags_pdf(rule_filter: str | None, year: int | None = None,
                    constituency: str | None = None) -> bytes:
    """PDF of every flag matching the filter: each flag is one side-by-side
    comparison (voter A vs voter B) with both photos and all details;
    _PDF_PER_PAGE comparisons per A4 page. `constituency` limits the report
    to one AC (attributed by voter A)."""
    import fitz
    rows = all_flags_for_export(rule_filter, year, constituency)
    ids = set()
    for f in rows:
        ids.add(f["voter_id"])
        if f["related_voter_id"]:
            ids.add(f["related_voter_id"])
    photos = get_photos(ids)

    doc = fitz.open()
    pw, phg = _A4
    M, top = 28, 52
    usable_h = phg - top - M
    row_h = usable_h / _PDF_PER_PAGE
    col_w = (pw - 2 * M) / 2
    sev_icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}

    page = None
    for i, f in enumerate(rows):
        slot = i % _PDF_PER_PAGE
        if slot == 0:
            page = doc.new_page(width=pw, height=phg)
            page.insert_textbox(
                fitz.Rect(M, 20, pw - M, 44),
                f"Fraud flags - {rule_filter or 'all rules'}"
                f"{f' - {year}' if year else ''}"
                f"{f' - AC {constituency}' if constituency else ' - all ACs'}   "
                f"(page {len(doc)},  {len(rows)} flag(s) total)",
                fontsize=11, fontname="hebo")
            page.draw_line(fitz.Point(M, 46), fitz.Point(pw - M, 46),
                           color=(.6, .6, .6), width=.7)

        y0 = top + slot * row_h
        page.draw_rect(fitz.Rect(M, y0, pw - M, y0 + row_h - 4),
                       color=(.85, .85, .85), width=.5)
        d = f.get("details") or {}
        extra = ""
        if d.get("name_sim") is not None:
            extra = f"   name_sim={d['name_sim']}"
        elif d.get("cosine") is not None:
            extra = f"   cosine={d['cosine']}"
        score = f["score"]
        verdict = f" · {f['verdict']}" if f.get("verdict") else ""
        page.insert_text(
            fitz.Point(M + 4, y0 + 10),
            f"{sev_icon.get(f['severity'], '')} {f['rule']}"
            f"   score={round(score, 3) if score is not None else '?'}{extra}{verdict}",
            fontsize=8, fontname="hebo", color=(.15, .15, .15))

        body_y = y0 + 14
        body_h = row_h - 4 - 14
        _pdf_draw_voter(page, M, body_y, col_w, body_h,
                        _pdf_voter_lines(f, "a"), photos.get(f["voter_id"]))
        page.draw_line(fitz.Point(M + col_w, body_y + 1),
                       fitz.Point(M + col_w, y0 + row_h - 6),
                       color=(.8, .8, .8), width=.5)
        if f["name_b"]:
            _pdf_draw_voter(page, M + col_w, body_y, col_w, body_h,
                            _pdf_voter_lines(f, "b"),
                            photos.get(f["related_voter_id"]))
        else:
            note = "House-overload group"
            if d.get("occupants"):
                note += f" - {d['occupants']} electors at House {d.get('house') or '?'}"
            page.insert_textbox(
                fitz.Rect(M + col_w + 6, body_y + 4, pw - M - 3, y0 + row_h - 6),
                note, fontsize=8, fontname="helv", color=(.4, .4, .4))

    if page is None:                                   # no flags at all
        page = doc.new_page(width=pw, height=phg)
        page.insert_textbox(fitz.Rect(M, 40, pw - M, 80),
                            "No flags to export.", fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------- compare PDF
COMPARE_PER_PAGE = 5


def _pdf_safe(s: str) -> str:
    """base-14 Helvetica has no em/en-dash glyph (renders as '?'); normalise."""
    return (str(s).replace("—", " - ").replace("–", "-")
            .replace("…", ".."))


def _compare_status_colour(status: str):
    return {"exact": (.11, .47, .11), "strong": (.20, .53, .20),
            "partial": (.62, .52, .04), "weak": (.68, .40, .07),
            "differ": (.78, .13, .13)}.get(status, (.45, .45, .45))


def _draw_compare_block(page, f, y: float, M: float, pw: float,
                        photos: dict) -> float:
    """Draw one flag: header, the two voter panels, the side-by-side attribute
    table, and the reason. Returns the new y cursor."""
    import fitz
    d = f.get("details") or {}
    comp = d.get("comparison") or []
    col_w = (pw - 2 * M) / 2
    sev_tag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(
        f["severity"], "")
    metric = d.get("cosine", d.get("similarity"))

    page.insert_text(
        fitz.Point(M + 2, y + 9),
        f"{sev_tag} {f['rule']}   score="
        f"{round(f['score'], 3) if f['score'] is not None else '?'}"
        + (f"   match={metric}" if metric is not None else "")
        + (f"  ·  {f['verdict']}" if f.get("verdict") else ""),
        fontsize=8, fontname="hebo", color=(.15, .15, .15))
    y += 13

    vh = 66
    _pdf_draw_voter(page, M, y, col_w, vh, _pdf_voter_lines(f, "a"),
                    photos.get(f["voter_id"]))
    page.draw_line(fitz.Point(M + col_w, y + 1), fitz.Point(M + col_w, y + vh - 2),
                   color=(.8, .8, .8), width=.5)
    if f["name_b"]:
        _pdf_draw_voter(page, M + col_w, y, col_w, vh, _pdf_voter_lines(f, "b"),
                        photos.get(f["related_voter_id"]))
    y += vh + 2

    if comp:
        total = pw - 2 * M
        c_attr, c_match = 118, 74
        c_val = (total - c_attr - c_match) / 2
        xs = [M, M + c_attr, M + c_attr + c_val, M + c_attr + c_val * 2]
        widths = [c_attr, c_val, c_val, c_match]

        def _clip(s: str, w: float) -> str:
            s = str(s)
            maxc = max(4, int((w - 4) / 3.4))
            return s if len(s) <= maxc else s[:maxc - 2] + ".."

        page.draw_rect(fitz.Rect(M, y, pw - M, y + 11), fill=(.93, .93, .95),
                       color=(.8, .8, .8), width=.3)
        for x, t in zip(xs, ("Attribute checked", "Voter A", "Voter B", "Match")):
            page.insert_text(fitz.Point(x + 2, y + 8), t, fontsize=6.5,
                             fontname="hebo")
        y += 11
        for row in comp:
            a = "—" if row.get("a") is None else str(row.get("a"))
            b = "—" if row.get("b") is None else str(row.get("b"))
            status = row.get("status", "")
            sim = row.get("similarity")
            match = status + (f" {sim}" if sim is not None else "")
            cells = [str(row.get("attribute", "")), a, b, match]
            fonts = ["helv", "helv", "helv", "hebo"]
            colours = [(0, 0, 0), (0, 0, 0), (0, 0, 0),
                       _compare_status_colour(status)]
            for x, w, txt, fnt, col in zip(xs, widths, cells, fonts, colours):
                page.insert_text(fitz.Point(x + 2, y + 7.5), _clip(txt, w),
                                 fontsize=6.5, fontname=fnt, color=col)
            page.draw_line(fitz.Point(M, y + 9.5), fitz.Point(pw - M, y + 9.5),
                           color=(.92, .92, .92), width=.25)
            y += 10

    reason = d.get("reason")
    if reason:
        rrect = fitz.Rect(M, y + 2, pw - M, y + 2 + 22)
        page.insert_textbox(rrect, _pdf_safe(f"Why: {reason}"), fontsize=7,
                            fontname="helv", color=(.25, .25, .25))
        y += 24
    page.draw_line(fitz.Point(M, y + 2), fitz.Point(pw - M, y + 2),
                   color=(.55, .55, .55), width=.5)
    return y + 8


def _compare_block_height(f) -> float:
    d = f.get("details") or {}
    comp = d.get("comparison") or []
    return 13 + 66 + 2 + (11 + len(comp) * 10.5 if comp else 0) + 24 + 10


def build_compare_pdf(rule_filter: str | None, year: int | None = None,
                      constituency: str | None = None) -> bytes:
    """Duplicate-comparison report for the model rules: every flag prints the
    two voters AND the full per-attribute logic that produced it, flowing down
    the page (≤ COMPARE_PER_PAGE per page, fewer when a block is tall)."""
    import fitz
    rows = all_flags_for_export(rule_filter, year, constituency)
    ids = set()
    for f in rows:
        ids.add(f["voter_id"])
        if f["related_voter_id"]:
            ids.add(f["related_voter_id"])
    photos = get_photos(ids)

    doc = fitz.open()
    pw, phg = _A4
    M, top = 28, 52
    bottom = phg - M
    page = None
    y = top
    on_page = 0

    def start_page():
        nonlocal page, y, on_page
        page = doc.new_page(width=pw, height=phg)
        page.insert_textbox(
            fitz.Rect(M, 18, pw - M, 44),
            _pdf_safe(
                f"Duplicate comparison — {rule_filter or 'all rules'}"
                f"{f' — {year}' if year else ''}"
                f"{f' — AC {constituency}' if constituency else ' — all ACs'}"
                f"   ({len(rows)} flag(s), page {len(doc)})"),
            fontsize=11, fontname="hebo")
        page.draw_line(fitz.Point(M, 46), fitz.Point(pw - M, 46),
                       color=(.6, .6, .6), width=.7)
        y, on_page = top, 0

    for f in rows:
        h = _compare_block_height(f)
        if page is None or on_page >= COMPARE_PER_PAGE or y + h > bottom:
            start_page()
        y = _draw_compare_block(page, f, y, M, pw, photos)
        on_page += 1

    if page is None:
        page = doc.new_page(width=pw, height=phg)
        page.insert_textbox(fitz.Rect(M, 40, pw - M, 80),
                            "No flags to export.", fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


def build_flags_pdf_zip(rule_filter: str | None, year: int | None = None,
                        progress=None, builder=None) -> bytes:
    """One PDF per constituency, bundled into a ZIP — the constituency-wise
    counterpart of the single combined report."""
    import io
    import zipfile

    builder = builder or build_flags_pdf
    acs = flagged_constituencies(year, rule_filter)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, ac in enumerate(acs, 1):
            if progress:
                progress(i, len(acs), ac)
            safe = str(ac).replace("/", "-").replace(" ", "")
            name = f"fraud_flags_{year or 'all'}_AC{safe}.pdf"
            z.writestr(name, builder(rule_filter, year, ac))
    return buf.getvalue()
