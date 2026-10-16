"""Step 1: resize the photo below `max_pixels` using an INTEGER scale factor."""
from __future__ import annotations

import io

from PIL import Image, ImageOps

from ..artifacts import StepLog
from ..config import ResizeConfig


def compute_scale(w: int, h: int, max_pixels: int) -> int:
    """Smallest integer k such that (w//k)*(h//k) <= max_pixels."""
    k = 1
    while (w // k) * (h // k) > max_pixels:
        k += 1
    return k


def run_resize(state: dict, cfg: ResizeConfig, slog: StepLog) -> dict:
    src = state["original_path"]
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)  # phone photos carry orientation EXIF
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    k = compute_scale(w, h, cfg.max_pixels)
    nw, nh = w // k, h // k
    if k > 1:
        img = img.resize((nw, nh), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=cfg.jpeg_quality)
    out_path = slog.write_bytes("resized.jpg", buf.getvalue())

    info = {
        "original_size": [w, h],
        "original_megapixels": round(w * h / 1e6, 2),
        "scale_factor": k,
        "resized_size": [nw, nh],
        "resized_megapixels": round(nw * nh / 1e6, 2),
        "output": out_path,
    }
    slog.write_input(
        f"# resize\n\nsource: {src}\nmax_pixels: {cfg.max_pixels}\n"
        f"jpeg_quality: {cfg.jpeg_quality}\n"
    )
    slog.write_output(info)
    return {"resized_path": out_path, "resize_info": info}
