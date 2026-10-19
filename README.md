# Linux Command Guide

A searchable, browser-only reference for common Linux commands, in the spirit of
[tldr pages](https://tldr.sh/) but with longer explanations aimed at beginners —
especially people learning C, embedded Linux/Yocto and device drivers.

**Live site:** https://itsnavin.github.io/linux-command-guide/

- **103 commands** in 14 categories, with 300 explained examples.
- **22 task walkthroughs**: everyday jobs (find large files, read logs, check listening
  ports…), C development (compile, make, inspect an ELF binary), embedded work (kernel
  modules, USB/serial devices, flashing an SD card) and shell basics (redirection, quoting,
  pipes and exit status, `--`, sudo, GNU vs BusyBox vs POSIX `sh`).
- Search by command name, alias (e.g. `gunzip`), or what you want to do (e.g. “listening ports”).
- Option-by-option tables, install notes for Debian/Ubuntu, Fedora, Arch and Alpine,
  compatibility notes, and links to the upstream manual pages.
- Safety labels on every example: **Read-only**, **Modifies**, **Destructive**, **Needs root**.
  Destructive and root examples cannot be copied with one click; you must open
  *Review & copy* and tick an acknowledgement first. Labels are guidance, not a guarantee.
- Shareable deep links, e.g. `#/cmd/tar`, `#/task/find-large-files`, `#/?q=compile%20c&cat=dev`.
- Keyboard friendly: `/` focuses search, `Esc` clears it; skip link; visible focus;
  works on mobile; light/dark theme follows the system.

The app **never runs commands**. It has no backend, no accounts, no analytics and no
third-party scripts; it only shows text for you to read, adapt and run yourself.
Example output in the guides describes what to look for — real output varies by
machine and distribution.

This is a curated set of commonly useful commands, not “every Linux command”. For
anything missing, use `man <command>`, `<command> --help`, or `man -k <keyword>`.

## Run locally

The site is plain HTML, CSS, ES modules and JSON — there is no build step and no
dependencies. It must be served over HTTP (browsers block `fetch` from `file://`):

```sh
python3 -m http.server 8000
# then open http://localhost:8000/
```

## Project layout

```
index.html               App shell (strict Content-Security-Policy, no inline scripts)
assets/                  Stylesheet and favicon
src/lib/core.js          Pure logic: search index, routing, placeholders, risk rules
src/app.js               UI rendering (DOM API + textContent only, no innerHTML/eval)
data/categories.json     Category list (one data file per category)
data/commands/*.json     Command entries and examples
data/tasks.json          Task walkthroughs
tests/test_catalog.py    Schema, uniqueness, link targets and safety-classification rules
tests/fixture_check.py   bash -n on every command + runs tested examples in a temp fixture
tests/e2e/test_app.py    Playwright browser tests (desktop + mobile)
scripts/check_links.py   Checks every man page / documentation URL resolves
```

## Testing

```sh
# 1. Catalog integrity and safety rules (stdlib only, any OS)
python3 -m unittest tests.test_catalog -v

# 2. Shell syntax + fixture execution (Linux or WSL with bash; dev examples need gcc/make/binutils)
python3 tests/fixture_check.py -v

# 3. Browser tests (installs Playwright into your Python environment)
python3 -m pip install playwright
python3 -m playwright install chromium
python3 -m unittest tests.e2e.test_app -v
# Test the deployed site instead of local files:
LCG_BASE_URL=https://itsnavin.github.io/linux-command-guide/ python3 -m unittest tests.e2e.test_app

# 4. External links (network access)
python3 scripts/check_links.py
```

**What the fixture check does.** Every example's command is parsed with `bash -n`
(placeholders replaced by dummy words). The 112 examples with a `test` block are executed
in a fresh directory created with `mkdtemp(prefix="lcg-fixture-")` containing small sample
files; `HOME` points inside it, stdin is `/dev/null`, there is a 20 s timeout, and that
directory is removed afterwards. The catalog tests enforce that tested examples are
read-only or fixture-local: no `sudo`, network, package, service or module commands, and
no absolute paths other than a small read-only allow-list (`/proc/…`, `/etc/os-release`…).
Examples whose tools are missing are skipped and reported.

The browser tests serve the repository to Chromium through Playwright request routing
on a virtual `https://lcg.test` origin, so no local port is opened.

## Publishing

`.github/workflows/pages.yml` runs all tests on every push and pull request. On pushes
to `main` it copies only `index.html`, `assets/`, `src/` and `data/` into the Pages
artifact and deploys it with GitHub Pages (Settings → Pages → Source: *GitHub Actions*).
The link check runs as a separate, non-blocking job because external sites can be flaky.

## Contributing content

See [CONTRIBUTING.md](CONTRIBUTING.md) for the data format, the safety rules the tests
enforce, and how to verify an example against its manual page.

## Sources and licence

All explanations are original and were written against the upstream manual pages
(linked from each command via [man7.org](https://man7.org/linux/man-pages/) or
[manpages.debian.org](https://manpages.debian.org/)) and project documentation. No
text is copied from tldr-pages or other third-party collections; tldr inspired only the
idea of short, example-first pages. Code and content are released under the
[MIT licence](LICENSE). Manual pages and documentation linked from the site belong to
their respective authors and are not redistributed here.
