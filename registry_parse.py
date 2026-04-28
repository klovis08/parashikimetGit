#!/usr/bin/env python3
"""HTML parsing for APP Regjistri i Parashikimeve (no I/O)."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from bs4 import BeautifulSoup

BASE = "https://www.app.gov.al"
URL = f"{BASE}/regjistri-i-parashikimeve/"

_WS = re.compile(r"\s+")

COLUMNS = [
    "objekti_procedurave",
    "autoriteti_kontraktues",
    "burimi_financimit",
    "fondi_limit_raw",
    "fondi_limit_lek",
    "data_publikimit",
    "ora_publikimit",
    "data_iso",
    "viti",
    "koha_zhvillimit",
    "kodi_cpv_raw",
    "cpv_spans",
    "tipi_procedures",
    "anulluar",
    "page_fetched",
    "row_index_on_page",
]


def normalize_text(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def parse_page_info(html: str) -> tuple[int | None, int | None]:
    t = _WS.sub(" ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    m = re.search(r"Faqe\s*(\d+)\s*nga\s*(\d+)", t, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _fondi_numeric_to_lek_str(token: str) -> str:
    """Parse a digits/., token into a two-decimal string; raise on failure."""
    t = normalize_text(token)
    if not t or not re.fullmatch(r"[\d.,]+", t):
        raise ValueError("not a numeric fondi token")

    has_commas = "," in t
    has_dots = "." in t

    if has_commas and has_dots:
        if t.rfind(",") > t.rfind("."):
            # e.g. 1.000.000,00 — thousands with dot, decimal comma
            normalized = t.replace(".", "").replace(",", ".")
        else:
            # e.g. 600,000.00 — thousands with comma, decimal point
            normalized = t.replace(",", "")
    elif has_commas:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            # e.g. 600,00 — decimal comma
            normalized = f"{parts[0]}.{parts[1]}"
        else:
            # e.g. 600,000 or 1,234,567 — comma as thousands separator
            normalized = t.replace(",", "")
    elif has_dots:
        if t.count(".") >= 2:
            # e.g. 1.000.000 — dot as thousands separator
            normalized = t.replace(".", "")
        else:
            intp, fracp = t.split(".")
            if (
                intp.isdigit()
                and fracp.isdigit()
                and len(fracp) == 3
            ):
                # e.g. 600.000 — single dot, three fractional digits => Albanian/EU grouping
                normalized = f"{intp}{fracp}"
            else:
                normalized = t
    else:
        normalized = t

    d = Decimal(normalized)
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(q, "f")


def parse_fondi(s: str) -> tuple[str, str]:
    """Return (raw_display_text, fondi_limit_lek) with lek as '#######.##' or ''."""
    raw = normalize_text(s)
    if not raw:
        return "", ""
    m = re.match(
        r"^([\d.,]+)\s*Lek",
        raw.replace("ë", "e").replace("Lekë", "Lek"),
        re.I,
    )
    if m:
        try:
            return raw, _fondi_numeric_to_lek_str(m.group(1))
        except (InvalidOperation, ValueError):
            return raw, ""
    return raw, ""


def parse_date_al(s: str) -> tuple[str, str]:
    s = normalize_text(s)
    if not s:
        return "", ""
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s)
    if not m:
        return s, ""
    d, mth, y = m.groups()
    try:
        dt = datetime(int(y), int(mth), int(d))
        return s, dt.date().isoformat()
    except ValueError:
        return s, ""


def extract_row_from_block(div: Any, page_num: int, idx: int) -> dict[str, str]:
    out: dict[str, str] = {k: "" for k in COLUMNS}
    out["page_fetched"] = str(page_num)
    out["row_index_on_page"] = str(idx)

    header = div.select_one("div.list-group-item-header .col-lg-12")
    if not header:
        header = div.select_one("div.list-group-item-header .col-md-12")
    if header:
        raw = header.get_text(" ", strip=True)
        for sep in (
            "Objekti i procedurës së prokurimit:",
            "Objekti i procedurës së prokurimit :",
        ):
            if sep in raw:
                out["objekti_procedurave"] = normalize_text(raw.split(sep, 1)[1])
                break
        if not out["objekti_procedurave"]:
            out["objekti_procedurave"] = normalize_text(raw)

    for li in div.select("ul.list-inline li"):
        b = li.find("b")
        if not b:
            continue
        label_raw = normalize_text(b.get_text()).lower().rstrip(" :")

        if "data e publikimit" in label_raw:
            for sp in li.find_all("span"):
                txt = normalize_text(sp.get_text())
                if re.match(r"^\d{1,2}-\d{1,2}-\d{4}$", txt):
                    out["data_publikimit"] = txt
                    _, diso = parse_date_al(txt)
                    out["data_iso"] = diso
                    break
            sm = li.find("small")
            if sm:
                out["ora_publikimit"] = normalize_text(sm.get_text())
            continue

        if "kodi cpv" in label_raw:
            block = li.find("span", style=lambda x: x and "607D8B" in str(x))
            parts: list[str] = []
            if block:
                for child in block.find_all("span", recursive=False):
                    t = normalize_text(child.get_text())
                    if t:
                        parts.append(t)
                if not parts and block:
                    parts = [normalize_text(block.get_text())]
            out["kodi_cpv_raw"] = " | ".join(parts)
            out["cpv_spans"] = out["kodi_cpv_raw"]
            continue

        val = ""
        for sp in li.find_all("span", style=lambda x: x and "607D8B" in str(x)):
            val = normalize_text(sp.get_text())
            if val:
                break
        if not val and li.find("i"):
            val = normalize_text(li.find("i").get_text())

        if "autoriteti" in label_raw and "kontraktues" in label_raw:
            out["autoriteti_kontraktues"] = val
        elif "burimi" in label_raw and "financimit" in label_raw:
            out["burimi_financimit"] = val
        elif "fondi limit" in label_raw or label_raw.startswith("fondi"):
            rraw, rnum = parse_fondi(val)
            out["fondi_limit_raw"] = rraw
            out["fondi_limit_lek"] = rnum
        elif label_raw.startswith("viti"):
            out["viti"] = val
        elif "koha" in label_raw and "zhvillimit" in label_raw:
            out["koha_zhvillimit"] = val
        elif "tipi" in label_raw and "procedur" in label_raw:
            out["tipi_procedures"] = val
        elif "anulluar" in label_raw:
            out["anulluar"] = val

    return out


def find_next_form(soup: BeautifulSoup) -> Any:
    for form in soup.select("div.pagination-form form"):
        for icon in form.find_all("i", class_=True):
            cls = " ".join(icon.get("class", []))
            if "fa-angle-right" in cls and "fa-angle-double" not in cls:
                return form
    return None


def _required_input_value(form: Any, name: str) -> str:
    field = form.find("input", {"name": name}) if form else None
    if not field:
        raise ValueError(f"missing pagination form field: {name}")
    value = normalize_text(field.get("value", ""))
    if not value:
        raise ValueError(f"empty pagination form field: {name}")
    return value


def next_page_payload(form: Any) -> dict[str, str]:
    if form is None:
        raise ValueError("pagination form not found")
    return {
        "__RequestVerificationToken": _required_input_value(
            form, "__RequestVerificationToken"
        ),
        "ufprt": _required_input_value(form, "ufprt"),
    }


def parse_page_rows(html: str, page_num: int) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    cont = soup.select_one("#simple-search.search-result-container")
    if not cont:
        return []
    divs = cont.select("div.list-group-item.list-group-item-result")
    return [extract_row_from_block(d, page_num, i) for i, d in enumerate(divs)]
