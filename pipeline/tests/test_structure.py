"""Arithmetic checks of the validate_json tool (steps/structure.py)."""
import json

from phunter.steps.structure import _validate_candidate


def _cand(**over) -> str:
    base = {
        "store_name": "Brew Masters",
        "items": [
            {"name": "Тулун", "qty": 3.0, "price": 324.0, "sum": 972.0,
             "discount": 108.0},
            {"name": "Сыр", "qty": 2.0, "price": 225.0, "sum": 450.0,
             "discount": 50.0},
        ],
        "subtotal": 1422.0,
        "discount_total": 158.0,
        "total": 1264.0,
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


def test_discount_receipt_valid():
    assert _validate_candidate(_cand()) == {"valid": True}


def test_no_discounts_still_valid():
    cand = _cand(subtotal=1422.0, total=1422.0)
    cand = json.loads(cand)
    for it in cand["items"]:
        it.pop("discount")
    cand.pop("discount_total")
    assert _validate_candidate(json.dumps(cand)) == {"valid": True}


def test_rkeeper_total_equals_item_sums():
    # the receipt-20 lesson: line amounts are already post-discount and
    # ИТОГ == sum(items); subtracting discount_total from it is the BUG
    cand = json.loads(_cand(total=1422.0, subtotal=None))
    assert _validate_candidate(json.dumps(cand, ensure_ascii=False)) == {
        "valid": True
    }


def test_unreconcilable_total_rejected_with_computed_values():
    res = _validate_candidate(_cand(total=1500.0))
    assert res["valid"] is False
    assert "1422.00" in res["errors"]  # computed sum of item sums
    assert "1264.00" in res["errors"]  # computed sum - discount_total


def test_discount_total_mismatch_rejected():
    res = _validate_candidate(_cand(discount_total=200.0))
    assert res["valid"] is False
    assert "158.00" in res["errors"]  # computed sum of item discounts


def test_line_sum_post_discount_accepted_when_discount_given():
    # Perekriostok-style lines: printed sum is already post-discount
    cand = json.loads(_cand())
    cand["items"][0].update({"sum": 864.0})  # 3 x 324 - 108
    cand["items"][1].update({"sum": 400.0})  # 2 x 225 - 50
    assert _validate_candidate(json.dumps(cand, ensure_ascii=False)) == {
        "valid": True
    }


def test_line_math_broken_rejected():
    cand = json.loads(_cand())
    cand["items"][0]["sum"] = 900.0  # neither 3x324 nor 3x324-108
    res = _validate_candidate(json.dumps(cand, ensure_ascii=False))
    assert res["valid"] is False
    assert "972.00" in res["errors"]


def test_run_structure_uses_yaml_prompts():
    # regression: prod requests 26-29 died with NameError — the LLM call kept
    # referencing the removed SYSTEM_PROMPT constant instead of the YAML prompt
    from phunter.config import LLMEndpoint, PromptsConfig
    from phunter.steps.structure import run_structure

    class FakeClient:
        def __init__(self):
            self.system = None

        def call_structured(self, system, user, adapter, **kw):
            self.system = system
            return adapter.validate_python(json.loads(_cand())), []

    class FakeLog:
        def write_input(self, text): pass
        def append_raw(self, label, raw): pass
        def write_output(self, obj): pass

    prompts = PromptsConfig(
        ocr_system="ocr-sys",
        ocr_user="ocr-user",
        structure_system="STRUCTURE-SYSTEM-FROM-YAML",
        structure_user="ocr was: {ocr_text}",
    )
    client = FakeClient()
    out = run_structure(
        {"ocr": {"text": "RAW OCR TEXT"}},
        LLMEndpoint(use_tools=True),
        prompts,
        client,
        FakeLog(),
    )
    assert client.system == "STRUCTURE-SYSTEM-FROM-YAML"
    assert out["structured"]["total"] == 1264.0
