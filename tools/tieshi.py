#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""题诗上画：把诗、落款、朱印叠到已经生成的画面上。

只做合成，不做生成——画面由生图模型出，文字由本脚本出，各管一段，中文才不会乱。

两种版式：
  h（默认）横排，整首压在画面下方，居中，落款与朱印在末行右下
  v        竖排，沿画面某一侧向下

用法：
  python tieshi.py --image 图_无字.png \
      --poem "石上无根铁一枝，|江心倒影万山迟。|风来不问谁磨刃，|只把寒光借月知。" \
      --sign "铁未成器 · 丙午秋" --seal 象 --layout h --out 成象_题诗.png
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONTS = {
    "kai": [r"C:\Windows\Fonts\simkai.ttf", r"C:\Windows\Fonts\STKAITI.TTF"],
    "song": [r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\STSONG.TTF"],
    "hei": [r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyh.ttc"],
}
# macOS / Linux 兜底
FONTS["kai"] += ["/System/Library/Fonts/Supplemental/Songti.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]
FONTS["song"] += ["/System/Library/Fonts/Supplemental/Songti.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]
FONTS["hei"] += ["/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]

INK = (38, 32, 27)
SEAL = (168, 40, 36)
TRACK = 0.20   # 横排字距（按字号比例）


def load_font(kind, size):
    for path in FONTS.get(kind, []):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    for path in FONTS["song"]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit("找不到中文字体，请用 --font-path 指定一个 .ttf/.ttc")


# ---------- 竖排 ----------

def draw_vertical(draw, lines, x, y0, unit, font, fill, gap_units=0.55):
    """逐字竖排；句与句之间留 gap_units 个字位的空。返回结束 y。"""
    y = y0
    for i, line in enumerate(lines):
        for ch in line:
            w = draw.textlength(ch, font=font)
            draw.text((x - w / 2, y), ch, font=font, fill=fill)
            y += unit
        if i != len(lines) - 1:
            y += unit * gap_units
    return y


# ---------- 横排 ----------

def line_width(draw, text, font, track):
    if not text:
        return 0.0
    return sum(draw.textlength(ch, font=font) for ch in text) + track * (len(text) - 1)


def draw_horizontal(draw, lines, cx, y0, font, track, line_gap, fill):
    """逐行横排、整行居中。返回结束 y。"""
    y = y0
    for line in lines:
        w = line_width(draw, line, font, track)
        x = cx - w / 2
        for ch in line:
            draw.text((x, y), ch, font=font, fill=fill)
            x += draw.textlength(ch, font=font) + track
        y += line_gap
    return y


def fit_size(draw, lines, max_w, max_h, line_gap_ratio=1.52):
    """求出能同时满足宽、高限制的最大字号。"""
    if not lines:
        return 24
    max_chars = max(len(s) for s in lines)
    n = len(lines)
    # 宽度约束：(n字 + 字距) 
    size_w = max_w / max(1.0, max_chars + (max_chars - 1) * TRACK)
    # 高度约束：n 行 × 行距
    size_h = max_h / max(1.0, n * line_gap_ratio)
    return int(max(14, min(size_w, size_h)))


# ---------- 纸面处理 ----------

def soften_band(img, box, alpha=46):
    """在文字区铺一层极淡纸色（竖排用，矩形均匀）。"""
    layer = Image.new("RGB", img.size, (250, 247, 240))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=alpha)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(6, box[2] - box[0]) // 5))
    img.paste(layer, (0, 0), mask)


def veil_block(img, box, alpha=58, fade=0.55):
    """横向题字带：整幅宽、自上而下渐入的淡纸色，像江面起雾，不像贴纸。

    box 的 x 范围会被忽略（始终铺满整幅），只在垂直方向做渐变，
    这样就不会在画面里留下左右两条矩形硬边。
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    W, H = img.size
    y0, y1 = max(0, y0), min(H, y1)
    if y1 <= y0:
        return img

    h = y1 - y0
    yv = np.arange(H)[:, None].astype(np.float32)
    # 上缘渐入，下缘到画面底部保持满强
    ramp = np.clip((yv - y0) / max(1.0, h * fade), 0, 1)
    band = np.where(yv >= y0, ramp, 0) * alpha
    # 轻微横向起伏，避免死板的均匀底色
    xs = np.linspace(0, np.pi * 2, W, dtype=np.float32)
    wobble = (0.90 + 0.10 * np.sin(xs * 1.5 + 0.7))[None, :]
    band = np.tile(band, (1, W)) * wobble

    mask = Image.fromarray(band.clip(0, 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(10, h // 6)))
    img.paste(Image.new("RGB", img.size, (252, 249, 243)), (0, 0), mask)
    return img


def erase_watermark(img, box):
    """把纸面上的浅色平台水印填掉：只作用于「底色均匀的纸区」，亮字按纸色覆盖。"""
    x0, y0, x1, y1 = box
    reg = np.asarray(img.crop(box)).astype(np.float32)
    g = reg.mean(2)
    base = np.percentile(g, 55)
    mask = g > (base + 12)
    if mask.sum() == 0:
        return img
    clean = reg[~mask]
    fill = np.median(clean.reshape(-1, 3), axis=0)
    reg[mask] = fill
    patch = Image.fromarray(reg.clip(0, 255).astype(np.uint8))
    patch = patch.filter(ImageFilter.GaussianBlur(radius=1.2))
    img.paste(patch, (x0, y0))
    return img


def feather_edge(img, x0, width=30):
    """把 x0 右侧的生图硬留白条羽化为纸色，消掉拼接线。"""
    arr = np.asarray(img).astype(np.float32)
    H, W, _ = arr.shape
    x0 = max(1, min(W - 2, x0))
    right = arr[:, x0 + width:].reshape(-1, 3)
    paper = np.median(right, axis=0) if right.size else np.array([250, 247, 240], np.float32)
    paper_map = np.ones((H, W, 3), np.float32) * paper
    rng = np.random.default_rng(7)
    paper_map += rng.normal(0, 1.1, (H, W, 3))
    t = np.clip((np.arange(W) - x0) / float(max(1, width)), 0, 1)[None, :, None]
    t = np.repeat(t, H, axis=0)
    out = arr * (1 - t) + paper_map * t
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def draw_seal(draw, x, y, size, ch, font_path=""):
    draw.rectangle([x, y, x + size, y + size], outline=SEAL, width=max(2, size // 14))
    sf = ImageFont.truetype(font_path, int(size * 0.72)) if font_path else load_font("song", int(size * 0.72))
    cw = draw.textlength(ch, font=sf)
    bb = sf.getbbox(ch)
    chh = bb[3] - bb[1]
    draw.text((x + (size - cw) / 2, y + (size - chh) / 2 - bb[1] * 0.55), ch, font=sf, fill=SEAL)


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="把题诗、落款、朱印叠到画上")
    ap.add_argument("--image", required=True, help="底图（生图产物）")
    ap.add_argument("--poem", required=True, help='四句，用 | 或换行分隔，句末标点可带')
    ap.add_argument("--sign", default="", help="落款小字（不写四柱，写画题＋时令）")
    ap.add_argument("--seal", default="", help="印章文字，一字最佳")
    ap.add_argument("--out", default="", help="输出路径，默认 <底图名>_题诗.png")
    ap.add_argument("--layout", default="h", choices=["h", "v"], help="h=横排压下方（默认），v=竖排靠侧")
    ap.add_argument("--font", default="kai", choices=["kai", "song", "hei"])
    ap.add_argument("--font-path", default="", help="指定字体文件，覆盖 --font")
    # 横排
    ap.add_argument("--h-span", type=float, default=0.300, help="横排文字块占画面高度的比例（默认 0.30）")
    ap.add_argument("--text-width", type=float, default=0.720, help="横排单行最大宽度占画面宽度的比例（默认 0.72）")
    ap.add_argument("--bottom", type=float, default=0.055, help="横排距画面底部留白比例（默认 0.055）")
    ap.add_argument("--size", type=int, default=0, help="强制字号（默认按空间自动求）")
    # 竖排
    ap.add_argument("--side", default="right", choices=["right", "left"], help="竖排在哪一侧")
    ap.add_argument("--top", type=float, default=0.10, help="竖排从画面高度的百分之几开始")
    ap.add_argument("--width", type=float, default=0.80, help="竖排诗句占画面高度的比例")
    # 纸面
    ap.add_argument("--veil", type=int, default=-1, help="题字带淡纸色强度 0-255（横排默认 58，竖排默认 0）")
    ap.add_argument("--band", action="store_true", help="竖排时在文字区铺一层极淡纸色")
    ap.add_argument("--no-seal", action="store_true", help="不画印")
    ap.add_argument("--wm-box", default="", help="去水印区域 x0,y0,x1,y1（仅用于纸色均匀处）")
    ap.add_argument("--feather", type=int, default=0, help="把这些像素以右羽化为纸色，消掉生图硬留白条的接缝")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        raise SystemExit("底图不存在：%s" % args.image)

    lines = [s.strip() for s in args.poem.replace("\n", "|").split("|") if s.strip()]
    if not lines:
        raise SystemExit("诗不能为空")
    lines = [s.replace("，", "，").replace(",", "，") for s in lines]

    img = Image.open(args.image).convert("RGB")
    if args.wm_box:
        img = erase_watermark(img, tuple(int(v) for v in args.wm_box.split(",")))
    if args.feather > 0:
        img = feather_edge(img, args.feather)
    W, H = img.size
    draw = ImageDraw.Draw(img)

    n_chars = sum(len(s) for s in lines)

    if args.layout == "v":
        n_gaps = len(lines) - 1
        avail = H * args.width
        unit = avail / (n_chars + n_gaps * 0.55)
        p_size = max(18, int(unit * 0.94))
        font = ImageFont.truetype(args.font_path, p_size) if args.font_path else load_font(args.font, p_size)
        s_size = max(11, int(p_size * 0.52))
        sfont = ImageFont.truetype(args.font_path, s_size) if args.font_path else load_font(args.font, s_size)

        edge = int(W * 0.075)
        poem_x = W - edge if args.side == "right" else edge
        sign_x = poem_x - int(p_size * 1.55) if args.side == "right" else poem_x + int(p_size * 1.55)
        y0 = int(H * args.top)

        if args.band:
            left = min(poem_x, sign_x) - int(p_size * 1.1)
            right = max(poem_x, sign_x) + int(p_size * 1.1)
            soften_band(img, (max(0, left), int(H * 0.05), min(W, right), int(H * 0.97)))
            draw = ImageDraw.Draw(img)

        y_end = draw_vertical(draw, lines, poem_x, y0, unit, font, INK)

        if args.sign:
            sign_unit = unit * 0.62
            sy = max(y0 + unit * 1.2, y_end - sign_unit * len(args.sign))
            y_sign_end = draw_vertical(draw, [args.sign], sign_x, sy, sign_unit, sfont, INK)
            if args.seal and not args.no_seal:
                seal_size = int(s_size * 1.8)
                sx = sign_x - seal_size // 2
                sy2 = y_sign_end + int(s_size * 0.9)
                if sy2 + seal_size < H:
                    draw_seal(draw, sx, sy2, seal_size, args.seal[0], args.font_path)
    else:
        # 横排：先按极限求字号，再定基线，最后自下而上摆
        max_w = W * args.text_width
        max_h = H * args.h_span
        p_size = args.size or fit_size(draw, lines, max_w, max_h)
        font = ImageFont.truetype(args.font_path, p_size) if args.font_path else load_font(args.font, p_size)
        s_size = max(12, int(p_size * 0.42))
        sfont = ImageFont.truetype(args.font_path, s_size) if args.font_path else load_font(args.font, s_size)

        track = p_size * TRACK
        line_gap = p_size * 1.52
        poem_h = line_gap * len(lines)
        sign_gap = p_size * 0.55
        sign_h = s_size * 1.25

        bottom = H * args.bottom
        y_sign = H - bottom - sign_h
        y0 = int(y_sign - sign_gap - poem_h + line_gap * 0.22)

        veil_alpha = args.veil if args.veil >= 0 else 58
        if veil_alpha > 0:
            img = veil_block(img, (0, y0 - p_size * 2.0, W, H), alpha=veil_alpha, fade=0.55)
            draw = ImageDraw.Draw(img)

        y_end = draw_horizontal(draw, lines, W / 2, y0, font, track, line_gap, INK)

        if args.sign:
            # 落款整块右对齐到最长一行的右端，印在款后
            track_s = s_size * 0.10
            sw = line_width(draw, args.sign, sfont, track_s)
            seal_size = int(s_size * 1.55) if (args.seal and not args.no_seal) else 0
            gap_seal = s_size * 0.75 if seal_size else 0
            max_line_w = max(line_width(draw, s, font, track) for s in lines)
            right_edge = W / 2 + max_line_w / 2
            total = sw + gap_seal + seal_size
            x = right_edge - total
            if x < W * 0.04:
                x = W * 0.04
            cx = x
            for ch in args.sign:
                draw.text((cx, y_sign), ch, font=sfont, fill=INK)
                cx += draw.textlength(ch, font=sfont) + track_s
            if seal_size:
                draw_seal(draw, int(cx + gap_seal), int(y_sign + (s_size * 1.05 - seal_size) / 2),
                          seal_size, args.seal[0], args.font_path)

    out = args.out or os.path.splitext(args.image)[0] + "_题诗.png"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, quality=95)
    print("已输出：%s（%dx%d，%s，诗 %d 字，字号 %d）"
          % (out, W, H, "横排" if args.layout == "h" else "竖排", n_chars, p_size))


if __name__ == "__main__":
    main()
