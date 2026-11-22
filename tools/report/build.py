#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把成象图与两张推广图内嵌进报告模板，产出单文件 HTML。

模板里的占位符：
  @@SETSE@@   设色成品（必填）
  @@APPR@@    赞赏码
  @@WECHAT@@  微信名片

图片一律压到可控体积再 base64 内嵌，单文件 500KB 上下，离线、转发都能打开。

用法：
  python build.py --tpl 报告模板.html --out 成象报告.html \
      --color 成象_题诗_设色.png \
      --appreciation ~/.workbuddy/skills/ps-zonglun/references/assets/appreciation.jpg \
      --wechat ~/.workbuddy/skills/ps-zonglun/references/assets/wechat_qr.jpg
"""
import argparse
import base64
import io
import os

from PIL import Image

SPECS = {
    "color": ("@@SETSE@@", 1024, 86),
    "appreciation": ("@@APPR@@", 520, 88),
    "wechat": ("@@WECHAT@@", 440, 88),
}


def to_data_uri(path, max_w, quality):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > max_w:
        h = round(im.height * max_w / im.width)
        im = im.resize((max_w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    b = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(b).decode(), len(b)


def main():
    ap = argparse.ArgumentParser(description="内嵌图片生成单文件成象报告")
    ap.add_argument("--tpl", required=True, help="模板路径（含 @@ 占位符）")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--color", required=True, help="设色成品图")
    ap.add_argument("--appreciation", default="", help="赞赏码")
    ap.add_argument("--wechat", default="", help="微信名片")
    ap.add_argument("--live-url", default="", help="可选：替换所有外链（默认用模板内的苍盘链接）")
    args = ap.parse_args()

    tpl = open(args.tpl, encoding="utf-8").read()
    total = 0
    for key, src in (("color", args.color), ("appreciation", args.appreciation), ("wechat", args.wechat)):
        ph, max_w, q = SPECS[key]
        if not src:
            # 缺图就把那一段整体留空，但不留破图
            tpl = tpl.replace(ph, "")
            print("跳过 %s（未提供）" % key)
            continue
        if not os.path.exists(src):
            raise SystemExit("图片不存在：%s" % src)
        uri, n = to_data_uri(src, max_w, q)
        total += n
        tpl = tpl.replace(ph, uri)
        print("内嵌 %-13s %6.1f KB  %s" % (key, n / 1024, os.path.basename(src)))

    if args.live_url:
        tpl = tpl.replace("https://mp.weixin.qq.com/s/9NFaItizyhEpjDzmTyEcPQ", args.live_url)

    left = [p for p in ("@@SETSE@@", "@@APPR@@", "@@WECHAT@@") if p in tpl]
    if left:
        raise SystemExit("仍有占位符未替换：%s" % left)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(tpl)
    print("已输出：%s（%.0f KB，其中图片 %.0f KB）"
          % (args.out, os.path.getsize(args.out) / 1024, total / 1024))


if __name__ == "__main__":
    main()
