from phunter.steps.resize import compute_scale


def test_no_resize_when_under_limit():
    assert compute_scale(1000, 1000, 3_000_000) == 1


def test_9mp_pixel5_photo():
    # 2268x4032 = 9.1 MP -> k=2 -> 1134x2016 = 2.29 MP
    assert compute_scale(2268, 4032, 3_000_000) == 2


def test_exactly_at_limit():
    # 4000x3000 = 12 MP -> k=2 -> 2000x1500 = 3.0 MP (<= limit)
    assert compute_scale(4000, 3000, 3_000_000) == 2


def test_48mp_needs_k4():
    # 8000x6000: k=3 -> 2666x2000 = 5.33 MP (still over); k=4 -> 3.0 MP
    assert compute_scale(8000, 6000, 3_000_000) == 4


def test_result_always_under_limit():
    for w, h in [(2268, 4032), (4000, 3000), (8000, 6000), (999, 10000), (1, 1)]:
        k = compute_scale(w, h, 3_000_000)
        assert (w // k) * (h // k) <= 3_000_000
