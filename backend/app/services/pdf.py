from __future__ import annotations

import textwrap

SECTION_LABELS = {
    "business": "Business",
    "risk_factors": "Risk Factors",
    "legal_proceedings": "Legal Proceedings",
    "md&a": "Management's Discussion and Analysis",
    "liquidity": "Liquidity and Capital Resources",
    "financial_statements": "Financial Statements",
    "subsequent_events": "Subsequent Events",
}


def _escape_pdf_text(value: str) -> str:
    safe = value.encode("latin-1", errors="replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_lines(title: str, body: str, sections: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = [(title.strip() or "Filing document", "title"), ("", "spacer")]
    if sections:
        for heading, section_text in sections:
            cleaned_heading = SECTION_LABELS.get(heading, heading.replace("_", " ").title())
            lines.append((cleaned_heading, "heading"))
            paragraphs = [part.strip() for part in (section_text or "").split("\n\n") if part.strip()]
            for paragraph in paragraphs or [section_text]:
                for wrapped in textwrap.wrap(paragraph, width=92, replace_whitespace=False):
                    lines.append((wrapped, "body"))
                lines.append(("", "spacer"))
    else:
        paragraphs = [part.strip() for part in (body or "").split("\n\n") if part.strip()]
        for paragraph in paragraphs or [body]:
            for wrapped in textwrap.wrap(paragraph, width=92, replace_whitespace=False):
                lines.append((wrapped, "body"))
            lines.append(("", "spacer"))
    return lines or [("Filing document", "title")]


def build_pdf_from_text(title: str, body: str, sections: list[tuple[str, str]] | None = None) -> bytes:
    wrapped_lines = _build_lines(title, body, sections=sections)
    pages: list[list[tuple[str, str]]] = []
    current_page: list[tuple[str, str]] = []
    remaining_height = 742

    line_heights = {"title": 22, "heading": 18, "body": 12, "spacer": 8}
    for line, style in wrapped_lines:
        needed = line_heights.get(style, 12)
        if current_page and remaining_height - needed < 48:
            pages.append(current_page)
            current_page = []
            remaining_height = 742
        current_page.append((line, style))
        remaining_height -= needed
    if current_page or not pages:
        pages.append(current_page or [("Filing document", "title")])

    objects: list[str] = []
    page_object_numbers: list[int] = []
    content_object_numbers: list[int] = []

    catalog_obj = 1
    pages_obj = 2
    font_obj = 3
    bold_font_obj = 4
    next_obj = 5

    for _ in pages:
        page_object_numbers.append(next_obj)
        next_obj += 1
        content_object_numbers.append(next_obj)
        next_obj += 1

    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for index, page_lines in enumerate(pages):
        page_obj = page_object_numbers[index]
        content_obj = content_object_numbers[index]
        _ = page_obj
        stream_lines = ["BT"]
        current_font: tuple[str, int] | None = None
        y = 760
        style_map = {
            "title": ("/F2", 16, 22),
            "heading": ("/F2", 12, 18),
            "body": ("/F1", 10, 12),
            "spacer": ("/F1", 10, 8),
        }
        for line, style in page_lines:
            font_name, font_size, line_height = style_map.get(style, ("/F1", 10, 12))
            if current_font != (font_name, font_size):
                stream_lines.append(f"{font_name} {font_size} Tf")
                current_font = (font_name, font_size)
            if line:
                escaped = _escape_pdf_text(line[:220])
                stream_lines.append(f"1 0 0 1 50 {y} Tm ({escaped}) Tj")
            y -= line_height
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        objects.append(
            f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R /F2 {bold_font_obj} 0 R >> >> /Contents {content_obj} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream")

    pdf_parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for object_index, object_value in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in pdf_parts))
        pdf_parts.append(f"{object_index} 0 obj\n{object_value}\nendobj\n".encode("utf-8"))

    xref_offset = sum(len(part) for part in pdf_parts)
    xref_lines = [f"0 {len(objects) + 1}", "0000000000 65535 f "]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n ")
    trailer = (
        f"xref\n{chr(10).join(xref_lines)}\n"
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_obj} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    )
    pdf_parts.append(trailer.encode("utf-8"))
    return b"".join(pdf_parts)
