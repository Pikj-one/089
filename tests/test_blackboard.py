import sys, tempfile, shutil, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from vulnhunt.blackboard import sanitize_blackboard, format_blackboard_js


class BlackboardSanitizeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_removes_css_images_fonts_and_header_dumps(self):
        (self.dir / "style.css").write_text("body{}")
        (self.dir / "logo.png").write_bytes(b"\x89PNG")
        (self.dir / "font.woff2").write_bytes(b"wOF2")
        (self.dir / "home_headers.txt").write_text(
            "HTTP/1.1 200 OK\r\nServer: nginx\r\nContent-Type: text/html\r\nX-Powered-By: PHP\r\n"
        )
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "img.gif").write_bytes(b"GIF")

        removed = sanitize_blackboard(self.dir)

        names = {p.name for p in removed}
        self.assertIn("style.css", names)
        self.assertIn("logo.png", names)
        self.assertIn("font.woff2", names)
        self.assertIn("home_headers.txt", names)
        self.assertIn("img.gif", names)
        self.assertFalse((self.dir / "style.css").exists())
        self.assertFalse((self.dir / "sub" / "img.gif").exists())

    def test_keeps_reusable_assets(self):
        (self.dir / "page.html").write_text("<html>ok</html>")
        (self.dir / "umi.js").write_text("// x\nconsole.log(1)\n")
        (self.dir / "inventory.json").write_text('{"a":1}')
        # robots.txt 也是 "Key: value" 形态，且超过阈值，必须被显式保留
        (self.dir / "robots.txt").write_text(
            "User-agent: *\nDisallow: /manage/\nAllow: /public/\nSitemap: https://hg.imou.com/sitemap.xml"
        )
        # 纯文本注释，不是响应头 dump（无 "Key: value" 形态）
        (self.dir / "notes.txt").write_text("just some plain notes, not headers")

        removed = sanitize_blackboard(self.dir)

        self.assertEqual(removed, [])
        self.assertTrue((self.dir / "page.html").exists())
        self.assertTrue((self.dir / "umi.js").exists())
        self.assertTrue((self.dir / "inventory.json").exists())
        self.assertTrue((self.dir / "robots.txt").exists())
        self.assertTrue((self.dir / "notes.txt").exists())

    def test_header_dump_heuristic_requires_key_value_shape(self):
        # 有 HTML 骨架的 txt 不算响应头 dump
        (self.dir / "page_dump.txt").write_text("Server: nginx\n<html><body>hi</body></html>")
        sanitize_blackboard(self.dir)
        self.assertTrue((self.dir / "page_dump.txt").exists())


class BlackboardPrettierTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.has_prettier = shutil.which("prettier") is not None

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_formats_small_js(self):
        if not self.has_prettier:
            self.skipTest("prettier 未安装")
        (self.dir / "x.js").write_text("const a={b:1};\nfunction f(){return 1+2;}\n")
        format_blackboard_js(self.dir, 1_000_000)
        self.assertTrue((self.dir / "x.js").read_text().startswith("const a = { b: 1 };"))

    def test_skips_minified_and_oversized(self):
        (self.dir / "mini.js").write_text("const a=1;")  # 单行但很小 -> 会格式化
        orig = "// c\n" + "const zz=" + "a" * 100_000 + ";\n"  # 100KB 压缩 -> 跳过
        (self.dir / "minified.js").write_text(orig)
        (self.dir / "big.js").write_text("// l\n" * 2 + "x" * 2_000_000 + "\n")  # 2MB -> 跳过
        format_blackboard_js(self.dir, 1_000_000)
        self.assertTrue((self.dir / "mini.js").read_text().startswith("const a = 1;"))
        self.assertEqual((self.dir / "minified.js").read_text(), orig)
        self.assertGreater((self.dir / "big.js").stat().st_size, 1_000_000)


if __name__ == "__main__":
    unittest.main()
