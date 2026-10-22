# gen_ascii_font.py — 生成 ASCII 95 字符位图字模 v2
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZES = [12, 16, 20, 24, 32, 48]
OUT_DIR = Path("esp/www/fonts")
VERSION = 0x02


def gen_font(ttf_path, size):
    font = ImageFont.truetype(ttf_path, size)
    ascent, descent = font.getmetrics()
    total_h = ascent + descent

    chars = []
    for code in range(32, 127):
        ch = chr(code)
        big = Image.new("L", (size * 4, size * 4), 0)
        draw = ImageDraw.Draw(big)
        baseline_y = size * 2
        draw.text((size, baseline_y - ascent), ch, font=font, fill=255)
        bbox = big.getbbox()
        if not bbox:
            chars.append((code, 0, b""))
            continue
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        if w == 0 or w > 250:
            chars.append((code, 0, b""))
            continue

        crop = Image.new("L", (w, total_h), 0)
        src_top = y0
        dst_top = max(0, y0 - (baseline_y - ascent))
        # 复制字形到 crop
        glyph_img = big.crop((x0, src_top, x1, min(y1, baseline_y + descent)))
        crop.paste(glyph_img, (0, dst_top))
        # 若字形顶部高于 baseline - ascent，做上裁切
        if y0 < baseline_y - ascent:
            shift = (baseline_y - ascent) - y0
            crop = crop.crop((0, shift, w, shift + total_h))
            if crop.size != (w, total_h):
                fixed = Image.new("L", (w, total_h), 0)
                fixed.paste(crop, (0, 0))
                crop = fixed

        rb = (w + 7) // 8
        data = bytearray(rb * total_h)
        px = crop.load()
        for y in range(total_h):
            base = y * rb
            for x in range(w):
                if px[x, y] > 128:
                    data[base + (x >> 3)] |= (0x80 >> (x & 7))
        chars.append((code, w, bytes(data)))

    return total_h, chars


def write_font(max_h, chars, path):
    with open(path, "wb") as f:
        # Header: [ver][count][max_h_lo][max_h_hi][reserved][reserved]
        f.write(bytes([VERSION, len(chars),
                       max_h & 0xFF, (max_h >> 8) & 0xFF, 0, 0]))
        for code, w, data in chars:
            if w == 0:
                f.write(bytes([code, 0, 0]))
            else:
                f.write(bytes([code, w, max_h]))
                f.write(data)
    return path.stat().st_size


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python gen_ascii_font.py path/to/font.ttf")
        sys.exit(1)
    ttf = sys.argv[1]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        max_h, chars = gen_font(ttf, size)
        p = OUT_DIR / f"font_{size}.bin"
        n = write_font(max_h, chars, p)
        print(f"font_{size}.bin: max_h={max_h}, {n} bytes")