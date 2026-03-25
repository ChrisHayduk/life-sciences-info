from __future__ import annotations

import textwrap


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_from_text(title: str, body: str) -> bytes:
    wrapped_lines = [title, ""] + textwrap.wrap(body or "", width=92, replace_whitespace=False)
    pages: list[list[str]] = []
    page_size = 46
    for idx in range(0, max(len(wrapped_lines), 1), page_size):
        pages.append(wrapped_lines[idx : idx + page_size] or [""])

    objects: list[str] = []
    page_object_numbers: list[int] = []
    content_object_numbers: list[int] = []

    catalog_obj = 1
    pages_obj = 2
    font_obj = 3
    next_obj = 4

    for _ in pages:
        page_object_numbers.append(next_obj)
        next_obj += 1
        content_object_numbers.append(next_obj)
        next_obj += 1

    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for index, lines in enumerate(pages):
        page_obj = page_object_numbers[index]
        content_obj = content_object_numbers[index]
        _ = page_obj
        stream_lines = [
            "BT",
            "/F1 10 Tf",
            "50 760 Td",
            "14 TL",
        ]
        first = True
        for line in lines:
            escaped = _escape_pdf_text(line[:180])
            if first:
                stream_lines.append(f"({_escape_pdf_text(line[:180])}) Tj")
                first = False
            else:
                stream_lines.append(f"T* ({escaped}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        objects.append(
            f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_obj} 0 R >>"
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

