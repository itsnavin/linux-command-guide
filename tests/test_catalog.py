"""Catalog integrity and safety-classification tests (stdlib only).

Run: python -m unittest discover -s tests -v
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

RISKS = {"read", "modify", "destructive"}
INSTALL_STATUS = {"builtin", "usually-installed", "often-missing"}
DISTROS = {"debian", "fedora", "arch", "alpine"}
GROUPS = {"basics", "everyday", "dev", "embedded"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAN_RE = re.compile(r"^[a-z0-9_.+-]+\.[1-8]$", re.I)
PLACEHOLDER_RE = re.compile(r"<([a-z][a-z0-9_.-]*)>")

COMMAND_KEYS = {"id", "name", "category", "summary", "aliases", "tags", "man", "manSite", "docs", "install", "compat", "examples"}
EXAMPLE_KEYS = {"title", "cmd", "explain", "risk", "root", "warning", "output", "options", "test"}
TEST_KEYS = {"vars", "before", "after", "expect", "reject", "status", "needs"}
TASK_KEYS = {"id", "group", "title", "summary", "tags", "related", "steps"}
STEP_KEYS = {"title", "cmd", "explain", "risk", "root", "warning", "output", "errors"}

# Patterns that must never appear in the catalog, even with warnings.
FORBIDDEN = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]*\s+)*(--\s+)?(/|~|\$HOME|\*|\.)(\s|$)"), "recursive rm of /, ~, *, ."),
    (re.compile(r"--no-preserve-root"), "--no-preserve-root"),
    (re.compile(r"\bchmod\s+(-R\s+)?0?777\b"), "chmod 777"),
    (re.compile(r"\bchmod\s+-R\b.*\s/(\s|$)"), "recursive chmod of /"),
    (re.compile(r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"), "pipe download to shell"),
    (re.compile(r":\(\)\s*\{"), "fork bomb"),
    (re.compile(r"\bmkfs(\.\w+)?\s+/dev/(sd[a-z]|nvme|mmcblk|hd)"), "mkfs on a real device"),
    (re.compile(r"\bof=/dev/(sd[a-z]|nvme|mmcblk|hd)"), "dd to a real device"),
    (re.compile(r">\s*/dev/(sd[a-z]|nvme|mmcblk)"), "redirect to a real device"),
    (re.compile(r"\beval\b"), "eval"),
]

ALLOWED_ABS = {"/dev/null", "/dev/zero", "/dev/urandom", "/dev/stdin", "/dev/stdout", "/dev/stderr"}
ABS_PATH_RE = re.compile(r"(?<![\w$.:/<>-])(/(?:[A-Za-z0-9_.*/-]|<[a-z][a-z0-9_.-]*>)+)")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_catalog():
    categories = load_json(DATA / "categories.json")
    commands = []
    files = {}
    for cat in categories:
        items = load_json(DATA / "commands" / f"{cat['id']}.json")
        files[cat["id"]] = items
        commands.extend(items)
    tasks = load_json(DATA / "tasks.json")
    return categories, commands, tasks, files


def all_entries(commands, tasks):
    """Yield (where, entry) for every example and every task step with a command."""
    for c in commands:
        for i, ex in enumerate(c["examples"]):
            yield f"command {c['id']} example {i + 1}", ex
    for t in tasks:
        for i, s in enumerate(t["steps"]):
            if "cmd" in s:
                yield f"task {t['id']} step {i + 1}", s


def option_token(flag):
    return re.split(r"[ ,=]", flag.strip(), maxsplit=1)[0]


def option_present(flag, cmd):
    token = option_token(flag)
    if token in cmd:
        return True
    if re.fullmatch(r"-[A-Za-z0-9]", token):
        # bundled short options such as -la or -czf
        return any(re.fullmatch(rf"-[A-Za-z0-9]*{re.escape(token[1])}[A-Za-z0-9]*", w) for w in cmd.split())
    return not token.startswith("-")


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories, cls.commands, cls.tasks, cls.files = load_catalog()
        cls.cat_ids = [c["id"] for c in cls.categories]
        cls.cmd_ids = [c["id"] for c in cls.commands]

    def test_category_files_match(self):
        self.assertEqual(len(self.cat_ids), len(set(self.cat_ids)))
        on_disk = {p.stem for p in (DATA / "commands").glob("*.json")}
        self.assertEqual(on_disk, set(self.cat_ids), "every category needs a file and every file a category")
        for c in self.categories:
            self.assertRegex(c["id"], ID_RE)
            self.assertTrue(c["label"] and c["description"])
            self.assertTrue(self.files[c["id"]], f"category {c['id']} is empty")

    def test_size_is_substantial(self):
        self.assertGreaterEqual(len(self.commands), 60)
        self.assertGreaterEqual(len(self.tasks), 15)

    def test_unique_ids(self):
        dupes = {i for i in self.cmd_ids if self.cmd_ids.count(i) > 1}
        self.assertFalse(dupes, f"duplicate command ids: {dupes}")
        task_ids = [t["id"] for t in self.tasks]
        self.assertEqual(len(task_ids), len(set(task_ids)), "duplicate task ids")

    def test_command_schema(self):
        for c in self.commands:
            with self.subTest(cmd=c.get("id")):
                self.assertLessEqual(set(c), COMMAND_KEYS, f"unknown keys {set(c) - COMMAND_KEYS}")
                for key in ("id", "name", "category", "summary", "install", "compat", "examples", "tags"):
                    self.assertIn(key, c)
                self.assertRegex(c["id"], ID_RE)
                self.assertIn(c["category"], self.cat_ids)
                self.assertIn(c["id"], [x["id"] for x in self.files[c["category"]]], "command stored in its category file")
                self.assertGreaterEqual(len(c["summary"]), 20)
                self.assertTrue(c["tags"])
                self.assertIsInstance(c.get("aliases", []), list)
                if "man" in c:
                    self.assertRegex(c["man"], MAN_RE)
                if "manSite" in c:
                    self.assertIn("man", c)
                    self.assertEqual(c["manSite"], "debian")
                inst = c["install"]
                self.assertIn(inst["status"], INSTALL_STATUS)
                self.assertLessEqual(set(inst.get("packages", {})), DISTROS)
                if inst["status"] != "builtin":
                    self.assertTrue(inst.get("packages"), "non-builtin needs package names")
                if "man" not in c and not c.get("docs"):
                    self.assertEqual(inst["status"], "builtin", "need a man page or docs link")
                for d in c.get("docs", []):
                    self.assertTrue(d["label"])
                    self.assertTrue(d["url"].startswith("https://"), d["url"])
                self.assertGreaterEqual(len(c["examples"]), 1)

    def test_most_commands_have_several_examples(self):
        single = [c["id"] for c in self.commands if len(c["examples"]) < 2]
        self.assertLessEqual(len(single), len(self.commands) // 8, f"too many single-example commands: {single}")

    def test_example_schema(self):
        for c in self.commands:
            for i, ex in enumerate(c["examples"]):
                with self.subTest(cmd=c["id"], example=i + 1):
                    self.assertLessEqual(set(ex), EXAMPLE_KEYS, f"unknown keys {set(ex) - EXAMPLE_KEYS}")
                    for key in ("title", "cmd", "explain", "risk"):
                        self.assertTrue(ex.get(key), f"missing {key}")
                    for opt in ex.get("options", []):
                        self.assertEqual(len(opt), 2)
                        self.assertTrue(option_present(opt[0], ex["cmd"]), f"option {opt[0]} not in command")
                    if "test" in ex:
                        self.assertLessEqual(set(ex["test"]), TEST_KEYS)
                        for name in ex["test"].get("vars", {}):
                            self.assertIn(f"<{name}>", ex["cmd"], f"test var {name} unused")
                        if "expect" in ex["test"]:
                            re.compile(ex["test"]["expect"])
                        if "reject" in ex["test"]:
                            re.compile(ex["test"]["reject"])

    def test_task_schema(self):
        for t in self.tasks:
            with self.subTest(task=t.get("id")):
                self.assertLessEqual(set(t), TASK_KEYS)
                self.assertRegex(t["id"], ID_RE)
                self.assertIn(t["group"], GROUPS)
                self.assertTrue(t["title"] and t["summary"] and t["tags"])
                self.assertGreaterEqual(len(t["steps"]), 3)
                for rel in t["related"]:
                    self.assertIn(rel, self.cmd_ids, f"related id {rel} does not exist")
                for s in t["steps"]:
                    self.assertLessEqual(set(s), STEP_KEYS)
                    self.assertTrue(s["title"] and s["explain"])
                    if "cmd" not in s:
                        for key in ("risk", "root", "warning"):
                            self.assertNotIn(key, s, "text-only steps carry no risk fields")
                    self.assertIsInstance(s.get("errors", []), list)

    def test_risk_classification(self):
        for where, e in all_entries(self.commands, self.tasks):
            with self.subTest(where=where):
                cmd = e["cmd"]
                self.assertIn(e.get("risk"), RISKS)
                self.assertIn(e.get("root", False), (True, False))
                if re.search(r"(^|[|;&(]\s*)sudo\b", cmd):
                    self.assertTrue(e.get("root"), "sudo commands must be marked root")
                if e["risk"] == "destructive" or e.get("root"):
                    self.assertTrue(e.get("warning"), "destructive/root entries need an adjacent warning")
                if e["risk"] == "read":
                    self.assertNotRegex(cmd, r"(^|[|;&]\s*)(sudo\s+)?(rm|rmdir|mv|dd|kill(?!\s+-l\b)|pkill|rmmod|insmod|chmod|chown|mkfs)\b",
                                        "read-only label on a modifying command")
                    stripped = re.sub(r"'[^']*'", "''", PLACEHOLDER_RE.sub("PH", cmd))
                    for target in re.findall(r"(?:^|\s)\d?>>?\s*(\S+)", stripped):
                        self.assertTrue(target == "/dev/null" or target.startswith("&"),
                                        f"read-only label but redirects into {target}")
                if re.search(r"(^|[|;&]\s*)(sudo\s+)?(rm|dd\b.*\bof=(/dev/|<)|rmmod|kill(?!\s+-l\b)|pkill|shred|truncate)\b", cmd) and "-n" not in cmd.split():
                    if not re.search(r"\b(rm\s+-i|rmdir)\b", cmd):
                        self.assertIn(e["risk"], ("destructive",), "deleting/killing commands must be destructive")

    def test_forbidden_patterns(self):
        for where, e in all_entries(self.commands, self.tasks):
            for pattern, label in FORBIDDEN:
                with self.subTest(where=where, rule=label):
                    self.assertIsNone(pattern.search(e["cmd"]), f"forbidden: {label}: {e['cmd']}")

    def test_risky_commands_target_placeholders(self):
        for where, e in all_entries(self.commands, self.tasks):
            if not (e["risk"] == "destructive" or (e.get("root") and e["risk"] == "modify")):
                continue
            with self.subTest(where=where):
                cmd = e["cmd"]
                for path in ABS_PATH_RE.findall(cmd):
                    self.assertTrue(path in ALLOWED_ABS or PLACEHOLDER_RE.search(path), f"risky command hard-codes system path {path}")
                if re.search(r"\b(rm|chmod|chown)\b[^|;&]*\s-[a-zA-Z]*[rR]", cmd):
                    self.assertTrue(PLACEHOLDER_RE.search(cmd), "recursive change must target a placeholder")

    def test_recursive_rm_has_inspect_first(self):
        rm = next(c for c in self.commands if c["id"] == "rm")
        cmds = [e["cmd"] for e in rm["examples"]]
        self.assertTrue(any(re.search(r"\b(ls|find)\b", c) for c in cmds), "rm needs an inspect-first example")
        self.assertTrue(any(" -- " in c for c in cmds), "rm needs a -- example")

    def test_placeholders_never_look_like_redirection_targets(self):
        for where, e in all_entries(self.commands, self.tasks):
            with self.subTest(where=where):
                stripped = PLACEHOLDER_RE.sub("PH", e["cmd"])
                self.assertNotRegex(stripped, r"<[A-Za-z]", "a < must be a placeholder or followed by a space")
                self.assertNotRegex(stripped, r"[A-Za-z]>(?!&)", "a > must be a placeholder end or preceded by a space")

    def test_testable_examples_are_safe_to_run(self):
        for c in self.commands:
            for i, ex in enumerate(c["examples"]):
                if "test" not in ex:
                    continue
                with self.subTest(cmd=c["id"], example=i + 1):
                    self.assertNotEqual(ex["risk"], "destructive", "destructive examples are never executed")
                    self.assertFalse(ex.get("root"), "root examples are never executed")
                    text = " ; ".join([ex["cmd"], ex["test"].get("before", ""), ex["test"].get("after", "")])
                    self.assertNotRegex(text, r"\b(sudo|su|curl|wget|ssh|scp|apt|apt-get|dnf|yum|pacman|apk|systemctl|insmod|rmmod|modprobe|mount|umount|pkill|reboot|shutdown|mkfs)\b",
                                        "network, package, service, privileged or system-changing tools are never executed")
                    self.assertNotRegex(text, r"\bkill\s+(?!-l\b)", "only kill -l (list signals) may run")
                    self.assertNotRegex(text, r"\brsync\b[^;|&]*\S:", "no remote rsync")
                    self.assertNotRegex(text, r"\bof=/", "dd may only write relative fixture files")
                    for path in re.findall(r"(?:^|[\s=])(/[^\s;|&]*)", text):
                        self.assertRegex(path, r"^/(dev/(null|zero|urandom)|proc/|sys/|etc/(os-release|passwd)$)",
                                         "fixture tests only read whitelisted absolute paths")
                    if re.search(r"(?:^|[\s=])/(proc|sys|etc)/", text):
                        self.assertEqual(ex["risk"], "read", "system paths are only read")
                    for value in ex["test"].get("vars", {}).values():
                        self.assertFalse(str(value).startswith("/"), "vars must be relative to the fixture")
                        self.assertFalse(str(value).startswith(".."), "vars must stay inside the fixture")

    def test_fixture_coverage(self):
        tested = sum(1 for c in self.commands for ex in c["examples"] if "test" in ex)
        self.assertGreaterEqual(tested, 50, "keep a broad set of executable fixture checks")

    def test_search_vocabulary_for_key_tasks(self):
        text = json.dumps(self.tasks).lower()
        for phrase in ("large files", "listening ports", "read logs", "kernel module", "permission denied"):
            self.assertIn(phrase, text)

    def test_dev_and_kernel_coverage(self):
        for cid in ("gcc", "make", "cmake", "file", "readelf", "lsmod", "modinfo", "journalctl", "dmesg"):
            self.assertIn(cid, self.cmd_ids)


if __name__ == "__main__":
    unittest.main()
