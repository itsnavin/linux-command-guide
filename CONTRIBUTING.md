# Contributing commands and guides

Content lives in JSON under `data/`. Keep entries original, short and verified: read
the upstream manual page (`man <cmd>` or the linked man7/Debian page) for every option
you explain, and try the example yourself in a scratch directory — never on real data
or system paths.

## Command entry (`data/commands/<category>.json`)

```json
{
  "id": "tar",                       // unique, lowercase, used in #/cmd/<id>
  "name": "tar",
  "category": "archives",            // must match the file name
  "summary": "One sentence.",
  "aliases": ["untar"],              // extra search words people type
  "tags": ["archive", "backup"],
  "man": "tar.1",                    // page.section; linked on man7.org
  "manSite": "debian",               // optional: use manpages.debian.org when man7 lacks the page
  "docs": [{ "label": "GNU tar manual", "url": "https://..." }],   // https only
  "install": {
    "status": "builtin | usually-installed | often-missing",
    "packages": { "debian": "tar", "fedora": "tar", "arch": "tar", "alpine": "tar" },
    "note": "optional"
  },
  "compat": "GNU vs BusyBox / bash vs sh / systemd notes",
  "examples": [ ... ]
}
```

Example:

```json
{
  "title": "Extract an archive into a directory",
  "cmd": "tar -xf <archive> -C <dest-dir>",
  "explain": "What it does and why.",
  "risk": "read | modify | destructive",
  "root": true,                      // only if it needs sudo/root
  "warning": "Shown next to the command; required for destructive or root examples.",
  "output": "What to look for in the output (never claim exact output).",
  "options": [["-x", "extract"], ["-C <dir>", "change to <dir> first"]],
  "test": { "vars": { "archive": "s.tar.gz", "dest-dir": "out" },
            "before": "tar -czf s.tar.gz src && mkdir out",
            "after": "ls out/src", "expect": "hello\\.c" }
}
```

- **Placeholders** are written `<name>` (letters, digits, `-`). The UI highlights them and
  tells readers to replace and quote them. Write redirections with a space (`> file`,
  `< file`) so they are never mistaken for placeholders.
- **Options**: every flag in `options` must appear in `cmd`.

## Task walkthrough (`data/tasks.json`)

`id`, `group` (`basics`, `everyday`, `dev`, `embedded`), `title`, `summary`, `tags`,
`related` (existing command ids) and `steps`. A step has `title` and `explain`, and
optionally `cmd` with `risk`/`root`/`warning`, `output` (“what the output means”) and
`errors` (common problems and fixes). Text-only steps omit `cmd` and the risk fields.

## Safety rules (enforced by `tests/test_catalog.py`)

- `sudo` ⇒ `root: true`; destructive or root ⇒ a `warning`.
- `rm`, `dd of=<device>`, `kill`/`pkill`, `rmmod`, `shred` and `truncate` ⇒ `destructive`.
- `read` examples must not write into files (other than `/dev/null`).
- Destructive/root examples must target placeholders, not real absolute paths such as
  `/`, `/etc` or `/dev/sda`. No `rm -rf /`, `chmod -R 777`, `curl | sh` and so on.
- Copying a destructive or root example always requires the acknowledgement panel.
- `test` blocks run real commands, so they may only touch the fixture directory: no
  sudo, network, package, service or module tools; only allow-listed read-only absolute
  paths. See the fixture contents at the top of `tests/fixture_check.py`.

Labels are guidance; a warning never makes a command safe. When unsure, choose the
more cautious label.

## Check your change

```sh
python3 -m unittest tests.test_catalog -v
python3 tests/fixture_check.py -v          # Linux/WSL with bash
python3 -m unittest tests.e2e.test_app -v  # needs Playwright + Chromium
python3 scripts/check_links.py             # if you added links
```
