from __future__ import annotations

import argparse
from pathlib import Path

from chp_pv_sim.paths import REPORTS_DIR, ensure_dirs


def _stitch_with_pillow(img_paths: list[Path], out_png: Path, out_pdf: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    imgs = [Image.open(p).convert("RGB") for p in img_paths]

    # normalize width (use the smallest width to avoid upscaling artifacts)
    target_w = min(im.width for im in imgs)
    norm = []
    for im in imgs:
        if im.width == target_w:
            norm.append(im)
        else:
            new_h = int(round(im.height * (target_w / im.width)))
            norm.append(im.resize((target_w, new_h), resample=Image.LANCZOS))

    pad = 30          # white border
    gap = 25          # gap between panels
    total_h = pad * 2 + sum(im.height for im in norm) + gap * (len(norm) - 1)
    canvas = Image.new("RGB", (target_w + pad * 2, total_h), color="white")

    # font (try Windows Arial, else default)
    font = None
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", size=36)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", size=36)
        except Exception:
            font = ImageFont.load_default()

    draw = ImageDraw.Draw(canvas)

    labels = ["(a)", "(b)", "(c)"]
    y = pad
    for i, im in enumerate(norm):
        canvas.paste(im, (pad, y))

        # label at top-left of each panel (inside the panel area)
        x0 = pad + 15
        y0 = y + 10

        # draw outline for readability
        text = labels[i] if i < len(labels) else f"({chr(ord('a') + i)})"
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((x0 + dx, y0 + dy), text, fill="white", font=font)
        draw.text((x0, y0), text, fill="black", font=font)

        y += im.height + gap

    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png, dpi=(300, 300))
    canvas.save(out_pdf, "PDF", resolution=300)


def _stitch_with_matplotlib(img_paths: list[Path], out_png: Path, out_pdf: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg

    imgs = [mpimg.imread(str(p)) for p in img_paths]

    fig, axes = plt.subplots(nrows=len(imgs), ncols=1, figsize=(10.8, 14.0))
    if len(imgs) == 1:
        axes = [axes]

    labels = ["(a)", "(b)", "(c)"]
    for i, (ax, im) in enumerate(zip(axes, imgs)):
        ax.imshow(im)
        ax.axis("off")
        lab = labels[i] if i < len(labels) else f"({chr(ord('a') + i)})"
        ax.text(
            0.01, 0.98, lab,
            transform=ax.transAxes,
            ha="left", va="top",
            fontsize=18,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.7),
        )

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300)
    fig.savefig(out_pdf, dpi=300)
    plt.close(fig)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument(
        "--compare_dir",
        default="compare_uc_vs_mpc__eload20_dump50",
        help="subdir under reports/figures/<scenario>/ ...",
    )
    args = ap.parse_args()

    in_dir = REPORTS_DIR / "figures" / args.scenario / args.compare_dir
    if not in_dir.exists():
        raise FileNotFoundError(f"Input figure dir not found: {in_dir}")

    # default order: (a) boiler&dump, (b) demand vs H_chp, (c) export cap
    img_paths = [
        in_dir / "01_boiler_dump_uc_vs_mpc.png",
        in_dir / "02_heat_demand_vs_Hchp.png",
        in_dir / "04_grid_export_cap.png",
    ]
    for p in img_paths:
        if not p.exists():
            raise FileNotFoundError(f"Missing panel file: {p}")

    out_dir = REPORTS_DIR / "figures" / args.scenario / "paper"
    out_png = out_dir / f"{args.scenario}__UC_vs_MPC__ABC.png"
    out_pdf = out_dir / f"{args.scenario}__UC_vs_MPC__ABC.pdf"

    # try pillow first, fallback to matplotlib
    try:
        _stitch_with_pillow(img_paths, out_png, out_pdf)
        backend = "Pillow"
    except Exception as e:
        print(f"[warn] Pillow stitching failed ({type(e).__name__}: {e}). Falling back to matplotlib...")
        _stitch_with_matplotlib(img_paths, out_png, out_pdf)
        backend = "matplotlib"

    print("\nBuilt paper multi-panel figure (a)(b)(c)")
    print("Backend :", backend)
    print("Input dir:", in_dir)
    print("Wrote PNG:", out_png)
    print("Wrote PDF:", out_pdf)


if __name__ == "__main__":
    main()