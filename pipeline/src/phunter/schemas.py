"""Pydantic schemas: VL OCR output and structured receipt."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter


# ---- structure step ---------------------------------------------------------
# (the OCR step emits plain Markdown now — see steps/ocr.py; no schema)

def _to_num(v: Any) -> float | None:
    """Lenient numeric coercion: '1 234,56' / '1234.5' / '' -> float|None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    s = s.rstrip("руб.RUB₽")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s:
        s = s.replace(",", "")  # 1,234.56 grouping
    try:
        return float(s)
    except ValueError:
        return None


Num = Annotated[float | None, BeforeValidator(_to_num)]


class ReceiptItem(BaseModel):
    name: str = ""
    qty: Num = None
    unit: str | None = None
    price: Num = None
    sum: Num = None
    discount: Num = None
    tax: str | None = None


class ReceiptStructured(BaseModel):
    store_name: str | None = None
    store_address: str | None = None
    inn: str | None = None
    receipt_number: str | None = None
    date: str | None = None            # YYYY-MM-DD when determinable
    time: str | None = None            # HH:MM:SS
    items: list[ReceiptItem] = Field(default_factory=list)
    subtotal: Num = None
    discount_total: Num = None
    tax_total: Num = None
    total: Num = None
    payment_method: str | None = None
    fiscal_document_number: str | None = None
    fd_number: str | None = None


STRUCTURED_ADAPTER: TypeAdapter = TypeAdapter(ReceiptStructured)
