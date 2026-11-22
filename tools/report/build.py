#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把成象图与两张推广图内嵌进报告模板，产出单文件 HTML。

v1.3.2 修「报告点不开」：
  ① 构建后自检：结构、占位符、内嵌图数量、体积、默认可见性，任何一项不合格就报错，
     不把半成品交给用户；
  ② --ascii-copy：同目录再落一份纯英文名的 report.html，上传后链接不会被中文名转义；
  ③ 结尾打印交付方式——单文件 HTML 必须「上传后给链接」，本地路径在聊天窗口里点不开。

模板里的占位符：
  @@SETSE@@   设色成品（必填）
  @@APPR@@    赞赏码
  @@WECHAT@@  微信名片

图片一律压到可控体积再 base64 内嵌，单文件 500KB 上下，离线、转发都能打开。
推广图默认取技能目录下的 assets/，换自己的就指向别的文件；缺图时整张卡片会从报告里去掉（不会留破图）。

用法：
  python build.py --tpl 报告模板.html --out 成象报告.html --color 成象_题诗_设色.png

  # 换自己的赞赏码与名片，并额外落一份英文名副本
  python build.py ... --appreciation 我的赞赏码.jpg --wechat 我的名片.jpg --ascii-copy
"""
import argparse
import base64
import io
import os
import re
import shutil
import sys

from PIL import Image

SPECS = {
    "color": ("@@SETSE@@", 1024, 86),
    "appreciation": ("@@APPR@@", 520, 88),
    "wechat": ("@@WECHAT@@", 440, 88),
}

# 模板里每张卡片的包夹标记，缺图时整块删掉
CARD_MARK = {"appreciation": "QR:appreciation", "wechat": "QR:wechat"}
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets")
ASSET_FILE = {"appreciation": "appreciation.jpg", "wechat": "wechat_qr.jpg"}


def default_asset(key):
    p = os.path.normpath(os.path.join(ASSET_DIR, ASSET_FILE[key]))
    return p if os.path.exists(p) else ""


def drop_card(tpl, key):
    """把「缺图」的那张卡片整块从模板里摘掉。"""
    mark = CARD_MARK[key]
    pat = re.compile(r"[ \t]*<!--%s-->.*?<!--/QR-->[ \t]*\n?" % re.escape(mark), re.S)
    out, n = pat.subn("", tpl)
    if n:
        return out
    # 模板没有标记时退回：清空占位符，至少不留 src 空串
    return tpl.replace(SPECS[key][0], "").replace('<img src="">', "")


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


def verify(html, expect_images):
    """构建后自检。返回 [(说明, 是否通过)]，任何一项不过就不算成功。"""
    checks = []

    checks.append(("HTML 结构完整", html.lstrip().lower().startswith("<!doctype html>")
                   and "</html>" in html.lower()))
    checks.append(("UTF-8 声明", 'charset="utf-8"' in html.lower()))
    checks.append(("占位符已全部替换", "@@" not in html))

    n_img = html.count("data:image/jpeg;base64,")
    checks.append(("内嵌图片 %d/%d" % (n_img, expect_images), n_img == expect_images))

    # 「点不开」的直接防线：脚本被预览器屏蔽时，页面必须仍然可见
    gated = ("html.js [data-reveal]" in html) and ("className += ' js'" in html)
    checks.append(("脚本被屏蔽仍可读", gated))

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    checks.append(("标题非空", bool(title and title.group(1).strip())))

    size_kb = len(html.encode("utf-8")) / 1024
    checks.append(("体积 %.0f KB（上限 4096）" % size_kb, size_kb < 4096))
    return checks


def main():
    ap = argparse.ArgumentParser(description="内嵌图片生成单文件成象报告")
    ap.add_argument("--tpl", required=True, help="模板路径（含 @@ 占位符）")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--color", required=True, help="设色成品图")
    ap.add_argument("--appreciation", default="", help="赞赏码（默认取 assets/appreciation.jpg）")
    ap.add_argument("--wechat", default="", help="微信名片（默认取 assets/wechat_qr.jpg）")
    ap.add_argument("--live-url", default="", help="可选：替换所有外链（默认用模板内的苍盘链接）")
    ap.add_argument("--ascii-copy", action="store_true",
                    help="同目录额外落一份 report.html（纯英文名，便于上传成链接）")
    ap.add_argument("--no-verify", action="store_true", help="跳过构建后自检（不建议）")
    args = ap.parse_args()

    # 没指定就用随包素材；随包也没有，就把那张卡片摘掉
    for key, val in (("appreciation", args.appreciation), ("wechat", args.wechat)):
        if not val:
            val = default_asset(key)
        if key == "appreciation":
            args.appreciation = val
        else:
            args.wechat = val

    tpl = open(args.tpl, encoding="utf-8").read()
    total, expect = 0, 0
    for key, src in (("color", args.color), ("appreciation", args.appreciation), ("wechat", args.wechat)):
        ph, max_w, q = SPECS[key]
        if not src:
            tpl = drop_card(tpl, key)
            print("跳过 %s（未提供，卡片已移除）" % key)
            continue
        if not os.path.exists(src):
            raise SystemExit("图片不存在：%s" % src)
        uri, n = to_data_uri(src, max_w, q)
        total += n
        expect += 1
        tpl = tpl.replace(ph, uri)
        print("内嵌 %-13s %6.1f KB  %s" % (key, n / 1024, os.path.basename(src)))

    if args.live_url:
        tpl = tpl.replace("https://mp.weixin.qq.com/s/9NFaItizyhEpjDzmTyEcPQ", args.live_url)

    left = [p for p in ("@@SETSE@@", "@@APPR@@", "@@WECHAT@@") if p in tpl]
    if left:
        raise SystemExit("仍有占位符未替换：%s" % left)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(tpl)

    if not args.no_verify:
        bad = 0
        print("自检：")
        for label, ok in verify(tpl, expect):
            print("  %s %s" % ("✓" if ok else "✗", label))
            bad += 0 if ok else 1
        if bad:
            print("自检未通过（%d 项），先修再交付。" % bad)
            sys.exit(1)

    if args.ascii_copy:
        ascii_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "report.html")
        shutil.copyfile(args.out, ascii_path)
        print("英文名副本：%s" % ascii_path)

    print("已输出：%s（%.0f KB，其中图片 %.0f KB，自检 %s）"
          % (args.out, os.path.getsize(args.out) / 1024, total / 1024,
             "通过" if not args.no_verify else "已跳过"))
    print("交付：把这个 HTML 上传（或放到网盘/静态页）后把链接给用户——"
          "本地文件路径在聊天窗口里点不开，会被当成附件或直接失效。")


if __name__ == "__main__":
    main()
