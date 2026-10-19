"""Browser tests (Playwright for Python, Chromium) for search, deep links, copy and risk flows.

Run: python -m unittest discover -s tests/e2e -v
Requires: pip install playwright && python -m playwright install chromium
Local files are served to Chromium through request routing on a virtual https origin
(no sockets). Set LCG_BASE_URL to test a deployed site instead.
"""
import json
import mimetypes
import os
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
LOCAL_ORIGIN = "https://lcg.test"
SITE_FILES = ("index.html", "assets/", "src/", "data/")
TYPES = {".js": "text/javascript", ".json": "application/json", ".css": "text/css",
         ".svg": "image/svg+xml", ".html": "text/html"}


def serve_from_disk(route):
    """Fulfil requests for the virtual origin from the repo, without opening any socket."""
    path = unquote(urlsplit(route.request.url).path).lstrip("/") or "index.html"
    target = (ROOT / path).resolve()
    allowed = path == "index.html" or path.startswith(SITE_FILES[1:])
    if not allowed or ROOT not in target.parents or not target.is_file():
        route.fulfill(status=404, body="not found")
        return
    ctype = TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    route.fulfill(status=200, body=target.read_bytes(), headers={"Content-Type": ctype})


def load_commands():
    cats = json.loads((ROOT / "data" / "categories.json").read_text(encoding="utf-8"))
    cmds = []
    for c in cats:
        cmds += json.loads((ROOT / "data" / "commands" / f"{c['id']}.json").read_text(encoding="utf-8"))
    return cmds


class AppTests(unittest.TestCase):
    viewport = {"width": 1280, "height": 900}
    is_mobile = False

    @classmethod
    def setUpClass(cls):
        cls.base = os.environ.get("LCG_BASE_URL") or LOCAL_ORIGIN + "/"
        cls.local = cls.base.startswith(LOCAL_ORIGIN)
        if not cls.base.endswith("/"):
            cls.base += "/"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.commands = load_commands()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport=self.viewport, is_mobile=self.is_mobile, has_touch=self.is_mobile,
        )
        if self.local:
            self.context.route(LOCAL_ORIGIN + "/**", serve_from_disk)
        origin = "/".join(self.base.split("/", 3)[:3])
        self.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        expect.set_options(timeout=5000)
        self.errors = []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "browser console errors")

    def open(self, hash_=""):
        self.page.goto(self.base + hash_)
        self.page.wait_for_selector("html[data-ready='true']", state="attached", timeout=15000)

    def search(self, text):
        box = self.page.locator("#search")
        box.fill(text)
        expect(self.page.locator("h1")).to_have_text(f"Results for “{text}”")

    # ------------------------------------------------------------ tests

    def test_home_lists_catalog(self):
        self.open()
        expect(self.page.locator("h1")).to_have_text("Linux commands, explained")
        expect(self.page.locator(".lead")).to_contain_text(f"{len(self.commands)} common commands")
        self.assertEqual(self.page.locator("main .grid li[data-id]").count(), len(self.commands))
        expect(self.page).to_have_title("Linux Command Guide")

    def test_search_by_command_name(self):
        self.open()
        self.search("tar")
        first = self.page.locator(".results > li").first
        expect(first).to_have_attribute("data-id", "tar")

    def test_search_by_alias(self):
        self.open()
        self.search("gunzip")
        expect(self.page.locator(".results > li").first).to_have_attribute("data-id", "gzip")

    def test_search_by_task(self):
        self.open()
        for query, task in [("find large files", "find-large-files"), ("listening ports", "check-listening-ports"),
                            ("read logs", "read-logs")]:
            self.search(query)
            ids = self.page.locator(".results > li").evaluate_all("els => els.slice(0, 3).map(e => e.dataset.id)")
            self.assertIn(task, ids, f"{query!r} should find {task}, got {ids}")

    def test_search_matches_example_text(self):
        self.open()
        self.search("dialout")
        ids = self.page.locator(".results > li").evaluate_all("els => els.map(e => e.dataset.id)")
        self.assertIn("serial-port-permission", ids)

    def test_empty_state(self):
        self.open()
        self.search("qwertyzzz")
        empty = self.page.locator("[data-empty='true']")
        expect(empty).to_be_visible()
        expect(empty).to_contain_text("man -k")
        expect(empty.locator("a").first).to_be_visible()

    def test_category_filter(self):
        self.open("#/?cat=kernel")
        expect(self.page.locator("#category")).to_have_value("kernel")
        ids = self.page.locator("main .grid li[data-id]").evaluate_all("els => els.map(e => e.dataset.id)")
        self.assertIn("lsmod", ids)
        self.assertNotIn("ls", ids)
        self.page.locator("#search").fill("module")
        expect(self.page.locator("h1")).to_contain_text("Results for")
        kinds = self.page.locator(".results > li").evaluate_all("els => els.map(e => e.dataset.kind)")
        self.assertTrue(kinds and set(kinds) == {"command"})

    def test_search_deep_link_restores_state(self):
        self.open("#/?q=compile%20c")
        expect(self.page.locator("#search")).to_have_value("compile c")
        expect(self.page.locator(".results > li").first).to_be_visible()

    def test_command_deep_link(self):
        self.open("#/cmd/journalctl")
        expect(self.page.locator("h1")).to_have_text("journalctl")
        expect(self.page).to_have_title("journalctl — Linux Command Guide")
        link = self.page.locator("a[href='https://man7.org/linux/man-pages/man1/journalctl.1.html']")
        expect(link).to_have_count(1)
        expect(link).to_have_attribute("rel", "noopener noreferrer")
        expect(self.page.locator("main")).to_contain_text("systemd-journal")

    def test_task_deep_link_and_navigation(self):
        self.open("#/task/kernel-module-basics")
        expect(self.page.locator("h1")).to_have_text("Inspect, load and unload a kernel module")
        expect(self.page.locator(".steps > li")).to_have_count(7)
        self.page.locator("main a[href='#/cmd/insmod']").click()
        expect(self.page.locator("h1")).to_have_text("insmod")
        self.page.go_back()
        expect(self.page.locator("h1")).to_have_text("Inspect, load and unload a kernel module")

    def test_not_found(self):
        self.open("#/cmd/does-not-exist")
        expect(self.page.locator("h1")).to_have_text("Page not found")
        self.open("#/nonsense/path/here")
        expect(self.page.locator("h1")).to_have_text("Page not found")

    def test_command_text_is_exact_and_placeholders_marked(self):
        self.open("#/cmd/grep")
        grep = next(c for c in self.commands if c["id"] == "grep")
        shown = self.page.locator("pre.cmd code").all_inner_texts()
        self.assertEqual(shown, [e["cmd"] for e in grep["examples"]])
        self.assertGreater(self.page.locator("pre.cmd .ph").count(), 0)
        expect(self.page.locator(".ph-note").first).to_contain_text("Replace every")

    def test_safe_copy(self):
        self.open("#/cmd/ls")
        first = self.page.locator(".example").first
        expect(first).to_have_attribute("data-risk", "read")
        first.locator("[data-action='copy']").click()
        expect(first.locator(".copy-status")).to_contain_text("Copied")
        if self.local:
            text = self.page.evaluate("navigator.clipboard.readText()")
            ls = next(c for c in self.commands if c["id"] == "ls")
            self.assertEqual(text, ls["examples"][0]["cmd"])

    def test_risky_examples_require_acknowledgement(self):
        self.open("#/cmd/rm")
        risky = self.page.locator(".example[data-risk='destructive']")
        self.assertGreater(risky.count(), 0)
        for i in range(risky.count()):
            ex = risky.nth(i)
            self.assertEqual(ex.locator("[data-action='copy']").count(), 0, "no one-click copy on destructive examples")
            expect(ex.locator(".warning")).to_be_visible()
        ex = risky.first
        review = ex.locator("[data-action='review']")
        expect(review).to_have_attribute("aria-expanded", "false")
        review.click()
        expect(review).to_have_attribute("aria-expanded", "true")
        confirm = ex.locator("[data-action='confirm-copy']")
        expect(confirm).to_be_disabled()
        ack = ex.locator("[data-action='ack']")
        expect(ack).to_be_focused()
        ack.check()
        expect(confirm).to_be_enabled()
        confirm.click()
        expect(ex.locator(".copy-status")).to_contain_text("Copied")

    def test_root_examples_require_acknowledgement(self):
        self.open("#/cmd/insmod")
        ex = self.page.locator(".example[data-root='true']").first
        expect(ex.locator(".badge-root")).to_have_text("Needs root")
        self.assertEqual(ex.locator("[data-action='copy']").count(), 0)
        expect(ex.locator("[data-action='review']")).to_be_visible()

    def test_every_risky_example_gated(self):
        for c in self.commands:
            if not any(e["risk"] == "destructive" or e.get("root") for e in c["examples"]):
                continue
            self.open(f"#/cmd/{c['id']}")
            for i, e in enumerate(c["examples"]):
                card = self.page.locator(".example").nth(i)
                gated = e["risk"] == "destructive" or e.get("root")
                self.assertEqual(card.locator("[data-action='review']").count(), 1 if gated else 0, f"{c['id']} #{i + 1}")
                self.assertEqual(card.locator("[data-action='copy']").count(), 0 if gated else 1, f"{c['id']} #{i + 1}")

    def test_keyboard_shortcuts(self):
        self.open("#/cmd/ls")
        self.page.locator("body").press("/")
        expect(self.page.locator("#search")).to_be_focused()
        self.page.keyboard.type("ports")
        expect(self.page.locator("h1")).to_contain_text("Results for")
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#search")).to_have_value("")
        expect(self.page.locator("h1")).to_have_text("Linux commands, explained")

    def test_skip_link(self):
        self.open()
        self.page.keyboard.press("Tab")
        skip = self.page.locator(".skip-link")
        expect(skip).to_be_focused()
        self.page.keyboard.press("Enter")
        expect(self.page.locator("#main")).to_be_focused()

    def test_untrusted_query_rendered_as_text(self):
        self.open()
        payload = "<img src=x onerror=window.__pwned=1>"
        self.page.locator("#search").fill(payload)
        expect(self.page.locator("h1")).to_contain_text(payload)
        self.assertEqual(self.page.locator("main img").count(), 0)
        self.assertIsNone(self.page.evaluate("window.__pwned"))

    def test_no_horizontal_overflow(self):
        for route in ["", "#/cmd/find", "#/task/flash-sd-card", "#/guides", "#/about"]:
            self.open(route)
            overflow = self.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            self.assertLessEqual(overflow, 1, f"horizontal overflow on {route or 'home'}")

    def test_core_logic(self):
        self.open()
        result = self.page.evaluate("""async () => {
            const core = await import('./src/lib/core.js');
            const routes = ['#/', '#/?q=find%20large&cat=files', '#/cmd/ls', '#/task/read-logs', '#/guides', '#/about'];
            const roundtrip = routes.map((r) => core.toHash(core.parseRoute(r)));
            return {
                roundtrip,
                bad: core.parseRoute('#/cmd/..%2Fetc').view,
                parts: core.splitPlaceholders('cp -- <src> <dest-dir>/').filter((p) => p.placeholder).map((p) => p.name),
                redirect: core.hasPlaceholders('sort < in.txt > out.txt'),
                ack: [core.needsAcknowledgement({risk: 'read'}), core.needsAcknowledgement({risk: 'read', root: true}),
                      core.needsAcknowledgement({risk: 'destructive'})],
                man: core.manUrl('modprobe.8'),
                debian: core.manUrl('xz.1', 'debian'),
            };
        }""")
        self.assertEqual(result["roundtrip"], ['#/', '#/?q=find+large&cat=files', '#/cmd/ls', '#/task/read-logs', '#/guides', '#/about'])
        self.assertEqual(result["bad"], "notfound")
        self.assertEqual(result["parts"], ["src", "dest-dir"])
        self.assertFalse(result["redirect"])
        self.assertEqual(result["ack"], [False, True, True])
        self.assertEqual(result["man"], "https://man7.org/linux/man-pages/man8/modprobe.8.html")
        self.assertEqual(result["debian"], "https://manpages.debian.org/xz.1")


class MobileAppTests(AppTests):
    viewport = {"width": 390, "height": 844}
    is_mobile = True

    def test_skip_link(self):
        self.skipTest("Tab-key navigation is covered by the desktop suite; touch emulation has no Tab order guarantee")

    def test_mobile_layout(self):
        self.open("#/cmd/dd")
        box = self.page.locator("#search").bounding_box()
        self.assertGreater(box["width"], 200)
        btn = self.page.locator(".example [data-action='review']").first.bounding_box()
        self.assertGreaterEqual(btn["height"], 40, "touch target height")


if __name__ == "__main__":
    unittest.main()
