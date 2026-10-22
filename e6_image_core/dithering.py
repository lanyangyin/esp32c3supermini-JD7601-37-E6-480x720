# dithering.py — 调色板、颜色匹配、抖动算法
from PIL import Image

# 统一格式：每条 = {name, color(校准色 #hex), deviceColor(设备色 #hex), index(设备索引)}
PALETTES = {
    "设备实测": [
        {"name": "黑", "color": "#000000", "deviceColor": "#000000", "index": 0x0},
        {"name": "白", "color": "#FFFFFF", "deviceColor": "#FFFFFF", "index": 0x1},
        {"name": "黄", "color": "#FFFF00", "deviceColor": "#FFFF00", "index": 0x2},
        {"name": "红", "color": "#FF0000", "deviceColor": "#FF0000", "index": 0x3},
        {"name": "蓝", "color": "#0000FF", "deviceColor": "#0000FF", "index": 0x5},
        {"name": "绿", "color": "#00FF00", "deviceColor": "#00FF00", "index": 0x6},
    ],
    "Spectra 6 校准": [
        {"name": "black",  "color": "#020202", "deviceColor": "#000000", "index": 0x0},
        {"name": "white",  "color": "#BEC8C8", "deviceColor": "#FFFFFF", "index": 0x1},
        {"name": "yellow", "color": "#CDCA00", "deviceColor": "#FFFF00", "index": 0x2},
        {"name": "red",    "color": "#871300", "deviceColor": "#FF0000", "index": 0x3},
        {"name": "blue",   "color": "#05409E", "deviceColor": "#0000FF", "index": 0x5},
        {"name": "green",  "color": "#27663C", "deviceColor": "#00FF00", "index": 0x6},
    ],
}

DITHER_MODES = [
    ("Floyd-Steinberg", "floyd_steinberg"),
    ("Atkinson", "atkinson"),
    ("Burkes", "burkes"),
    ("Stucki", "stucki"),
    ("Jarvis-Judice-Ninke", "jarvis"),
    ("Sierra", "sierra"),
    ("Sierra Lite", "sierra_lite"),
    ("Bayer 4×4", "bayer4"),
    ("Bayer 8×8", "bayer8"),
    ("仅量化", "none"),
]

KERNELS = {
    "floyd_steinberg": [(1, 0, 7/16), (-1, 1, 3/16), (0, 1, 5/16), (1, 1, 1/16)],
    "atkinson": [(1, 0, 1/8), (2, 0, 1/8), (-1, 1, 1/8), (0, 1, 1/8), (1, 1, 1/8), (0, 2, 1/8)],
    "burkes": [(1, 0, 8/32), (2, 0, 4/32), (-2, 1, 2/32), (-1, 1, 4/32),
               (0, 1, 8/32), (1, 1, 4/32), (2, 1, 2/32),
               (-2, 2, 1/32), (-1, 2, 2/32), (0, 2, 4/32), (1, 2, 2/32), (2, 2, 1/32)],
    "stucki": [(1, 0, 8/42), (2, 0, 4/42),
               (-2, 1, 2/42), (-1, 1, 4/42), (0, 1, 8/42), (1, 1, 4/42), (2, 1, 2/42),
               (-2, 2, 1/42), (-1, 2, 2/42), (0, 2, 4/42), (1, 2, 2/42), (2, 2, 1/42)],
    "jarvis": [(1, 0, 7/48), (2, 0, 5/48),
               (-2, 1, 3/48), (-1, 1, 5/48), (0, 1, 7/48), (1, 1, 5/48), (2, 1, 3/48),
               (-2, 2, 1/48), (-1, 2, 3/48), (0, 2, 5/48), (1, 2, 3/48), (2, 2, 1/48)],
    "sierra": [(1, 0, 5/32), (2, 0, 3/32),
               (-2, 1, 2/32), (-1, 1, 4/32), (0, 1, 5/32), (1, 1, 4/32), (2, 1, 2/32),
               (-1, 2, 2/32), (0, 2, 3/32), (1, 2, 2/32)],
    "sierra_lite": [(1, 0, 2/4), (-1, 1, 1/4), (0, 1, 1/4)],
}

BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]


def hex_to_rgb(hex_str):
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def palette_to_rgb(palette):
    """字典列表 → 校准色 RGB 元组列表（用于抖动）"""
    return [hex_to_rgb(p["color"]) for p in palette]


def palette_to_device_rgb(palette):
    """字典列表 → 设备色 RGB 元组列表（用于 Device 预览）"""
    return [hex_to_rgb(p["deviceColor"]) for p in palette]


def palette_to_indices(palette):
    """字典列表 → 设备索引列表（用于 pack）"""
    return [p["index"] for p in palette]


def nearest(r, g, b, palette_colors):
    best, bestd = 0, 1 << 30
    for i, (cr, cg, cb) in enumerate(palette_colors):
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < bestd:
            bestd, best = d, i
    return best


def diffuse(img, kernel, palette_colors, serpentine):
    w, h = img.size
    px = img.load()
    buf = [[list(px[x, y]) for x in range(w)] for y in range(h)]
    block = [[0] * w for _ in range(h)]

    for y in range(h):
        xs = range(w) if (not serpentine or y % 2 == 0) else range(w - 1, -1, -1)
        for x in xs:
            r, g, b = buf[y][x]
            r = max(0, min(255, int(r)))
            g = max(0, min(255, int(g)))
            b = max(0, min(255, int(b)))
            i = nearest(r, g, b, palette_colors)
            cr, cg, cb = palette_colors[i]
            block[y][x] = i
            er, eg, eb = r - cr, g - cg, b - cb
            for dx, dy, wt in kernel:
                nx = x + (dx if (not serpentine or y % 2 == 0) else -dx)
                ny = y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    buf[ny][nx][0] += er * wt
                    buf[ny][nx][1] += eg * wt
                    buf[ny][nx][2] += eb * wt
    return block


def ordered(img, matrix, palette_colors):
    w, h = img.size
    n = len(matrix)
    px = img.load()
    block = [[0] * w for _ in range(h)]
    scale = 255.0 / (n * n)
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            t = (matrix[y % n][x % n] + 0.5) * scale - 127.5
            rr = max(0, min(255, int(r + t)))
            gg = max(0, min(255, int(g + t)))
            bb = max(0, min(255, int(b + t)))
            block[y][x] = nearest(rr, gg, bb, palette_colors)
    return block


def quantize(img, palette_colors):
    w, h = img.size
    px = img.load()
    block = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            block[y][x] = nearest(*px[x, y], palette_colors)
    return block


def dither(img, mode, palette_colors, serpentine=True):
    if mode in KERNELS:
        return diffuse(img, KERNELS[mode], palette_colors, serpentine)
    if mode == "bayer4":
        return ordered(img, BAYER4, palette_colors)
    if mode == "bayer8":
        return ordered(img, BAYER8, palette_colors)
    return quantize(img, palette_colors)


def block_to_image(block, palette_colors):
    h = len(block)
    w = len(block[0])
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = palette_colors[block[y][x]]
    return img


def pack(block, palette_indices):
    """block 是抖动后的索引（0..N-1），palette_indices 是每个调色板位置对应的设备索引"""
    h = len(block)
    w = len(block[0])
    buf = bytearray()
    for y in range(h):
        for x in range(0, w, 2):
            hi = palette_indices[block[y][x]]
            lo = palette_indices[block[y][x + 1]] if x + 1 < w else hi
            buf.append((hi << 4) | lo)
    return bytes(buf)