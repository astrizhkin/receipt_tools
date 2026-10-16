"""verify_receipt: server-side reconciliation of stored numbers."""
from phunter.verify import verify_receipt


def _r(**over):
    base = {
        "items": [
            {"qty": 3.0, "price": 324.0, "sum": 972.0, "discount": 108.0},
            {"qty": 2.0, "price": 225.0, "sum": 450.0, "discount": 50.0},
        ],
        "subtotal": 1422.0,
        "discount_total": 158.0,
        "total": 1264.0,
    }
    base.update(over)
    return base


def test_discounted_receipt_verifies():
    assert verify_receipt(_r()) is True


def test_plain_receipt_verifies():
    assert verify_receipt({
        "items": [{"qty": 2.0, "price": 100.0, "sum": 200.0}],
        "total": 200.0,
    }) is True


def test_post_discount_lines_verify():
    # Perekriostok layout: line sums already post-discount
    assert verify_receipt({
        "items": [{"qty": 1.0, "price": 90.0, "sum": 90.0, "discount": 10.0}],
        "discount_total": 10.0,
        "total": 90.0,
    }) is True


def test_total_mismatch_fails():
    assert verify_receipt(_r(total=1500.0)) is False


def test_broken_line_math_fails():
    r = _r()
    r["items"][0]["sum"] = 900.0  # neither 3x324 nor 3x324-108
    assert verify_receipt(r) is False


def test_discount_sum_mismatch_fails():
    assert verify_receipt(_r(discount_total=200.0)) is False


def test_missing_total_or_items_fails():
    assert verify_receipt({"items": []}) is False
    assert verify_receipt({"items": [{"qty": 1, "price": 5, "sum": 5}]}) is False


def test_perekriostok_subtotal_branch():
    # receipt 14: lines post-discount with POS rounding; the printed
    # pre-discount subtotal (ПОДИТОГ) is what reconciles to the total
    assert verify_receipt({
        "items": [{"qty": 1, "price": 4920.88, "sum": 4920.88}],
        "subtotal": 5808.88,
        "discount_total": 898.00,
        "total": 4910.88,
    }) is True


def test_kopeck_rounding_within_relative_slack():
    # Pyaterochka-style: items 447.09 vs paid 447.00
    assert verify_receipt({
        "items": [{"qty": 1, "price": 447.09, "sum": 447.09}],
        "total": 447.00,
    }) is True
