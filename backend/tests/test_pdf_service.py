"""Unit tests for the ReportLab invoice renderer.

The pagination branch (``if y < 30 * mm``) was previously untested, which is
exactly the branch a customer hits the moment they print an invoice with more
than ~40 line items. Two tests still render through the real ReportLab canvas so
the output is proven to be a genuine PDF document.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.services import pdf_service

PDF_MAGIC = b"%PDF"

# A recorded draw operation: ("text", payload), ("font", name, size) or ("line",).
_Op = tuple


class RecordingCanvas:
    """A ReportLab canvas stand-in that records draw calls per page.

    ``pdf_service`` draws straight onto a canvas and returns the rendered bytes,
    so which text lands on which page - and whether a long line-item list
    overflows - is invisible to a caller that only gets bytes back. Recording
    the draw calls makes the layout contract assertable without adding a PDF
    parser to the runtime dependency set.
    """

    def __init__(self) -> None:
        self.pages: list[list[_Op]] = [[]]
        self.fonts: list[tuple[str, float]] = []

    @property
    def current(self) -> list[_Op]:
        return self.pages[-1]

    def setFont(self, name: str, size: float) -> None:
        self.fonts.append((name, size))
        self.current.append(("font", name, size))

    def drawString(self, x: float, y: float, text: str) -> None:
        self.current.append(("text", text))

    def drawRightString(self, x: float, y: float, text: str) -> None:
        self.current.append(("text", text))

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.current.append(("line",))

    def showPage(self) -> None:
        self.pages.append([])

    def save(self) -> None:
        """Finish the document.

        ReportLab discards the page opened by a trailing ``showPage()`` when the
        file is closed, so a render that ends with ``showPage(); save()`` yields
        one page, not two. Dropping a trailing empty page keeps the page count
        (and therefore ``pages[-1]``) identical to the real canvas.
        """
        if len(self.pages) > 1 and not self.pages[-1]:
            self.pages.pop()


def page_text(page: list[_Op]) -> str:
    """Flatten one recorded page to the text ReportLab was asked to draw."""
    return "\n".join(op[1] for op in page if op[0] == "text")


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict], RecordingCanvas]:
    """Render an invoice through the recording canvas and return the recording."""

    def _render(payload: dict) -> RecordingCanvas:
        recording = RecordingCanvas()
        monkeypatch.setattr(pdf_service.canvas, "Canvas", lambda *a, **kw: recording)
        pdf_service.build_invoice_pdf(payload)
        return recording

    return _render


def _invoice(**overrides) -> dict:
    """A minimal but complete invoice payload."""
    data = {
        "invoice_no": "INV-2026-0001",
        "created_at": "2026-10-10",
        "business": {
            "name": "StockPilot Demo",
            "address": "Dhaka, BD",
            "phone": "+8801700000000",
            "email": "sales@example.com",
        },
        "customer": {"name": "Acme Retail", "phone": "+8801800000000"},
        "items": [
            {"product_name": "Widget", "quantity": 2, "unit_price": 250.0, "line_total": 500.0}
        ],
        "subtotal": 500.0,
        "discount_amount": 50.0,
        "tax_percent": 5,
        "tax_amount": 22.5,
        "total_amount": 472.5,
        "paid_amount": 472.5,
        "payment_method": "cash",
        "payment_status": "paid",
    }
    data.update(overrides)
    return data


def _many_items(count: int) -> list[dict]:
    """``count`` line items, enough to exhaust the first page when ``count`` > ~40."""
    return [
        {"product_name": f"Item {i:03d}", "quantity": 1, "unit_price": 10.0, "line_total": 10.0}
        for i in range(count)
    ]


class TestOutputIsAPdf:
    """Rendered through the real canvas, so these prove the bytes are a PDF."""

    def test_produces_a_real_pdf_document(self) -> None:
        blob = pdf_service.build_invoice_pdf(_invoice())

        assert blob.startswith(PDF_MAGIC)
        assert b"%%EOF" in blob[-1024:]

    def test_an_empty_invoice_still_renders(self) -> None:
        """A sale with no items must not raise - it is a legal (if odd) invoice."""
        assert pdf_service.build_invoice_pdf(_invoice(items=[])).startswith(PDF_MAGIC)


class TestHeader:
    def test_business_identity_and_contact_details_are_drawn(self, render) -> None:
        text = page_text(render(_invoice()).pages[0])

        assert "StockPilot Demo" in text
        assert "Dhaka, BD" in text
        assert "sales@example.com" in text

    def test_header_falls_back_to_a_generic_title_without_a_business(self, render) -> None:
        """A deleted/nameless business must not crash the render or print "None"."""
        text = page_text(render(_invoice(business={})).pages[0])

        assert "Invoice" in text
        assert "None" not in text

    def test_blank_business_details_are_skipped(self, render) -> None:
        """Only truthy address/phone/email lines are drawn."""
        payload = _invoice(
            business={"name": "StockPilot Demo", "address": None, "phone": "", "email": "x@y.z"}
        )
        text = page_text(render(payload).pages[0])

        assert "x@y.z" in text
        assert "Invoice INV-2026-0001" in text

    def test_invoice_number_and_date_are_drawn(self, render) -> None:
        text = page_text(render(_invoice()).pages[0])

        assert "Invoice INV-2026-0001" in text
        assert "2026-10-10" in text


class TestBody:
    def test_item_rows_and_totals_are_rendered(self, render) -> None:
        text = page_text(render(_invoice()).pages[0])

        assert "Widget" in text
        for label in ("Subtotal", "Discount", "Tax", "Total", "Paid"):
            assert label in text

    def test_tax_label_reports_the_configured_percent(self, render) -> None:
        assert "Tax (5%)" in page_text(render(_invoice()).pages[0])

    def test_missing_totals_render_as_zero_not_as_none(self, render) -> None:
        payload = _invoice(subtotal=None, total_amount=None, paid_amount=None, tax_percent=None)
        text = page_text(render(payload).pages[0])

        assert "0.00" in text
        assert "None" not in text

    def test_non_numeric_quantity_or_price_falls_back_to_zero(self, render) -> None:
        """Legacy rows can hold NULL/blank numerics; the render must not raise."""
        payload = _invoice(
            items=[{"product_name": "Odd", "quantity": None, "unit_price": "", "line_total": None}]
        )
        text = page_text(render(payload).pages[0])

        assert "Odd" in text
        assert "0.00" in text

    def test_long_product_names_are_truncated(self, render) -> None:
        name = "X" * 60
        text = page_text(render(_invoice(items=[{"product_name": name}])).pages[0])

        assert name not in text, "a 60-char name must be truncated to 45 characters"
        assert name[:45] in text

    def test_customer_block_is_drawn_for_a_named_customer(self, render) -> None:
        assert "Bill to: Acme Retail" in page_text(render(_invoice()).pages[0])

    def test_customer_block_is_omitted_for_walk_in_sales(self, render) -> None:
        """A walk-in (unnamed customer) must not print a "Bill to:" block."""
        assert "Bill to" not in page_text(render(_invoice(customer={})).pages[0])

    def test_payment_footer_records_method_and_status(self, render) -> None:
        text = page_text(render(_invoice()).pages[-1])

        assert "Payment: cash (paid)" in text
        assert "Thank you for your business!" in text


class TestPagination:
    def test_a_single_page_invoice_stays_one_page(self, render) -> None:
        recording = render(_invoice())

        assert len(recording.pages) == 1

    def test_a_boundary_length_invoice_still_fits_one_page(self, render) -> None:
        """One row under the overflow threshold must not paginate."""
        recording = render(_invoice(items=_many_items(40)))

        assert len(recording.pages) == 1

    def test_a_long_invoice_overflows_onto_additional_pages(self, render) -> None:
        """Enough lines to exhaust the first page must start a new one.

        A4 leaves roughly 40 item rows before ``y`` drops below the 30mm margin,
        so 60 rows must paginate.
        """
        recording = render(_invoice(items=_many_items(60)))

        assert len(recording.pages) > 1, "a 60-line invoice must not be crammed onto one page"

    def test_no_row_is_dropped_by_pagination(self, render) -> None:
        """Pagination must not silently lose line items."""
        pages = render(_invoice(items=_many_items(60))).pages

        assert "Item 000" in page_text(pages[0])
        assert "Item 059" in page_text(pages[-1])

    def test_every_item_is_drawn_exactly_once(self, render) -> None:
        pages = render(_invoice(items=_many_items(60))).pages
        drawn = [op[1] for page in pages for op in page if op[0] == "text"]

        for i in range(60):
            assert drawn.count(f"Item {i:03d}") == 1

    def test_the_footer_survives_pagination(self, render) -> None:
        """The footer is drawn at a fixed y, so it must appear on the last page."""
        pages = render(_invoice(items=_many_items(60))).pages

        assert "Thank you for your business!" in page_text(pages[-1])

    def test_continuation_pages_redraw_the_separator_rule(self, render) -> None:
        """A page with no rule would print an unexplained column."""
        second = render(_invoice(items=_many_items(60))).pages[1]

        assert ("line",) in second, "the second page must redraw the separator rule"

    def test_the_recording_canvas_matches_the_real_canvas(self, render) -> None:
        """Guard the guard: the double must not invent its own layout contract.

        Every assertion above is only meaningful if the recording splits pages
        where ReportLab itself does. Rendering the same payload through the real
        canvas and counting the pages in the bytes it emits proves that, so a
        future refactor of either the renderer or this double fails loudly
        instead of quietly agreeing with itself.
        """
        payload = _invoice(items=_many_items(60))

        pdf = pdf_service.build_invoice_pdf(payload)
        real_pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")

        assert real_pages == len(render(payload).pages)
        assert real_pages > 1, "the real canvas must paginate this invoice too"
