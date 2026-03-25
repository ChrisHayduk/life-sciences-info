from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def render_html_to_pdf(
    html_bytes: bytes,
    *,
    source_url: str | None = None,
    timeout_seconds: float = 45.0,
) -> bytes:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    html_text = html_bytes.decode("utf-8", errors="ignore")
    html_text = _inject_base_href(html_text, source_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu", "--font-render-hinting=medium"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1024})
        try:
            page.emulate_media(media="screen")
            page.set_content(html_text, wait_until="load", timeout=int(timeout_seconds * 1000))
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout_seconds * 1000))
            except PlaywrightTimeoutError:
                pass
            page.add_style_tag(
                content="""
                    @page { size: Letter; margin: 0.45in; }
                    html, body { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
                """
            )
            return page.pdf(
                format="Letter",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0.45in", "right": "0.45in", "bottom": "0.55in", "left": "0.45in"},
            )
        finally:
            browser.close()


def _inject_base_href(html_text: str, source_url: str | None) -> str:
    if not source_url or "<base" in html_text.lower():
        return html_text

    parsed = urlsplit(source_url)
    base_path = parsed.path.rsplit("/", 1)[0] + "/" if "/" in parsed.path else "/"
    base_href = urlunsplit((parsed.scheme, parsed.netloc, base_path, "", ""))
    base_tag = f'<base href="{base_href}">'

    lower_html = html_text.lower()
    if "<head" in lower_html and "</head>" in lower_html:
        head_end = lower_html.index("</head>")
        return html_text[:head_end] + base_tag + html_text[head_end:]
    if "<html" in lower_html:
        html_end = html_text.find(">")
        if html_end != -1:
            return html_text[: html_end + 1] + "<head>" + base_tag + "</head>" + html_text[html_end + 1 :]
    return "<head>" + base_tag + "</head>" + html_text
