from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def render_page(poppler_exe: Path, pdf_path: Path, page: int, output_path: Path) -> None:
    prefix = output_path.with_suffix("")
    command = [
        str(poppler_exe),
        "-f",
        str(page),
        "-l",
        str(page),
        "-singlefile",
        "-jpeg",
        "-r",
        "110",
        str(pdf_path),
        str(prefix),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_sheet(items: list[dict[str, object]], output_path: Path, title: str) -> None:
    columns = 5
    card_w, card_h = 620, 900
    title_h = 90
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * card_w, title_h + rows * card_h), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((24, 20), title, fill="black", font=font(38))
    label_font = font(22)
    small_font = font(18)

    for index, item in enumerate(items):
        col = index % columns
        row = index // columns
        left = col * card_w
        top = title_h + row * card_h
        image = Image.open(str(item["render_path"])).convert("RGB")
        image.thumbnail((580, 760), Image.Resampling.LANCZOS)
        x = left + (card_w - image.width) // 2
        y = top + 88 + (760 - image.height) // 2
        sheet.paste(image, (x, y))
        draw.rectangle((left + 6, top + 6, left + card_w - 6, top + card_h - 6), outline="#b8b8b8", width=2)
        name = str(item["filename"])
        if len(name) > 25:
            name = name[:24] + "…"
        draw.text((left + 18, top + 14), name, fill="black", font=label_font)
        draw.text(
            (left + 18, top + 50),
            f"第 {item['page']} / {item['pages']} 页",
            fill="#444444",
            font=small_font,
        )

    sheet.save(output_path, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("poppler_exe", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rendered_dir = args.output_dir / "rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    rows = json.loads(args.audit_json.read_text(encoding="utf-8"))

    position_items: dict[str, list[dict[str, object]]] = {"first": [], "middle": [], "last": []}
    for index, row in enumerate(rows, start=1):
        pages = int(row["pages"])
        positions = {"first": 1, "middle": max(1, (pages + 1) // 2), "last": pages}
        for position, page in positions.items():
            output_path = rendered_dir / f"{index:02d}-{position}-p{page}.jpg"
            render_page(args.poppler_exe, Path(row["path"]), page, output_path)
            position_items[position].append(
                {
                    "filename": row["filename"],
                    "pages": pages,
                    "page": page,
                    "render_path": output_path,
                }
            )

    for position, items in position_items.items():
        make_sheet(items, args.output_dir / f"contact-{position}.jpg", f"PDF审计抽样 - {position}")


if __name__ == "__main__":
    main()

