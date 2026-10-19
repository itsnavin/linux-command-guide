import {
  RISK_LEVELS,
  ROOT_LABEL,
  splitPlaceholders,
  hasPlaceholders,
  needsAcknowledgement,
  highestRisk,
  anyRoot,
  manUrl,
  MAN_SITES,
  buildIndex,
  search,
  parseRoute,
  toHash,
} from './lib/core.js';

const DISTROS = [
  ['debian', 'Debian / Ubuntu'],
  ['fedora', 'Fedora / RHEL'],
  ['arch', 'Arch'],
  ['alpine', 'Alpine'],
];

const INSTALL_STATUS = {
  builtin: 'Shell builtin — nothing to install.',
  'usually-installed': 'Usually installed by default on desktop and server distributions.',
  'often-missing': 'Often not installed by default; install it with your package manager if needed.',
};

const GROUPS = [
  ['basics', 'Shell basics'],
  ['everyday', 'Everyday tasks'],
  ['dev', 'C development'],
  ['embedded', 'Embedded & drivers'],
];

const EXAMPLE_QUERIES = ['find large files', 'listening ports', 'read logs', 'compile c', 'kernel module', 'serial permission denied', 'tar', 'grep'];

const state = {
  categories: [],
  commands: [],
  byId: new Map(),
  tasks: [],
  taskById: new Map(),
  index: [],
  route: null,
};

const main = document.getElementById('main');
const searchInput = document.getElementById('search');
const categorySelect = document.getElementById('category');
const live = document.getElementById('live');

// ------------------------------------------------------------ DOM helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = value;
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? '' : String(value));
    }
  }
  appendChildren(el, children);
  return el;
}

function appendChildren(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

function announce(message) {
  live.textContent = '';
  window.setTimeout(() => {
    live.textContent = message;
  }, 30);
}

function safeHttpsUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' ? u.href : null;
  } catch {
    return null;
  }
}

function externalLink(url, label) {
  const href = safeHttpsUrl(url);
  if (!href) return h('span', null, label);
  return h('a', { href, rel: 'noopener noreferrer', target: '_blank' }, label, h('span', { class: 'visually-hidden', text: ' (opens in a new tab)' }));
}

function riskBadge(risk) {
  const info = RISK_LEVELS[risk];
  return h('span', { class: `badge badge-${risk}`, title: info.description }, info.label);
}

function rootBadge() {
  return h('span', { class: 'badge badge-root', title: ROOT_LABEL.description }, ROOT_LABEL.label);
}

function badgesFor(item) {
  return h('span', { class: 'badges' }, riskBadge(item.risk), item.root ? rootBadge() : null);
}

function commandBadges(cmd) {
  const risk = highestRisk(cmd.examples);
  return h(
    'span',
    { class: 'badges', 'aria-label': 'Most risky example' },
    risk !== 'read' ? h('span', { class: 'badge badge-neutral' }, 'up to') : null,
    riskBadge(risk),
    anyRoot(cmd.examples) ? rootBadge() : null,
  );
}

function renderCommandText(cmd) {
  const pre = h('pre', { class: 'cmd' });
  const code = h('code');
  for (const part of splitPlaceholders(cmd)) {
    if (part.placeholder) {
      code.append(h('span', { class: 'ph', title: `Placeholder: replace ${part.text} with your value` }, part.text));
    } else {
      code.append(document.createTextNode(part.text));
    }
  }
  pre.append(code);
  return pre;
}

// ------------------------------------------------------------ copy

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to the legacy path
    }
  }
  const area = h('textarea', { readonly: true, 'aria-hidden': 'true', class: 'visually-hidden' });
  area.value = text;
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

function copyBlock(item) {
  const cmd = item.cmd;
  const status = h('p', { class: 'copy-status', 'aria-live': 'polite' });
  const placeholderNote = hasPlaceholders(cmd)
    ? h('p', { class: 'ph-note' }, 'Replace every ', h('span', { class: 'ph' }, '<placeholder>'), ' (including the angle brackets) with your own value, quoted if it contains spaces, and read the command before running it.')
    : null;

  async function doCopy() {
    const ok = await copyText(cmd);
    status.textContent = ok ? 'Copied. Review it in your terminal before pressing Enter.' : 'Copy failed: select the command text and copy it manually.';
    announce(status.textContent);
  }

  if (!needsAcknowledgement(item)) {
    const btn = h('button', { type: 'button', class: 'copy-btn', 'data-action': 'copy', onclick: doCopy }, 'Copy');
    btn.setAttribute('aria-label', `Copy command: ${cmd}`);
    return h('div', null, h('div', { class: 'cmd-row' }, renderCommandText(cmd), btn), placeholderNote, status);
  }

  const panelId = `ack-${Math.random().toString(36).slice(2, 10)}`;
  const checkbox = h('input', { type: 'checkbox', 'data-action': 'ack' });
  const confirmBtn = h('button', { type: 'button', disabled: true, 'data-action': 'confirm-copy', onclick: doCopy }, 'Copy command');
  checkbox.addEventListener('change', () => {
    confirmBtn.disabled = !checkbox.checked;
  });
  const reasons = [];
  if (item.risk === 'destructive') reasons.push('it can delete, overwrite or interrupt things with no undo');
  if (item.root) reasons.push('it runs with root privileges');
  const panel = h(
    'div',
    { class: 'ack-panel', id: panelId, hidden: true },
    h('p', null, h('strong', null, 'Before copying: '), `this command needs extra care because ${reasons.join(' and ')}. A warning label does not make it safe.`),
    h('label', null, checkbox, h('span', null, 'I have read the warning, I will replace the placeholders, and I will check the target (paths, device, PID, package) before running it.')),
    h('div', { class: 'ack-actions' }, confirmBtn,
      h('button', { type: 'button', class: 'secondary', onclick: () => { panel.hidden = true; reviewBtn.setAttribute('aria-expanded', 'false'); reviewBtn.focus(); } }, 'Cancel')),
  );
  const reviewBtn = h('button', {
    type: 'button',
    class: 'copy-btn secondary',
    'aria-expanded': 'false',
    'aria-controls': panelId,
    'data-action': 'review',
    onclick: () => {
      panel.hidden = !panel.hidden;
      reviewBtn.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) checkbox.focus();
    },
  }, 'Review & copy');
  return h('div', null, h('div', { class: 'cmd-row' }, renderCommandText(cmd), reviewBtn), panel, placeholderNote, status);
}

function warningNote(text) {
  return h('div', { class: 'warning', role: 'note' }, h('strong', null, 'Warning:'), text);
}

// ------------------------------------------------------------ views

function setTitle(text) {
  document.title = text ? `${text} — Linux Command Guide` : 'Linux Command Guide';
}

function heading(text, extra) {
  return h('h1', { tabindex: '-1' }, text, extra || null);
}

function commandLink(cmd) {
  return h('a', { href: toHash({ view: 'command', id: cmd.id }) }, h('code', null, cmd.name));
}

function resultItem(result) {
  if (result.kind === 'command') {
    const c = result.item;
    return h('li', { class: 'result card', 'data-kind': 'command', 'data-id': c.id },
      h('a', { class: 'result-link', href: toHash({ view: 'command', id: c.id }) },
        h('span', { class: 'result-title' }, h('code', null, c.name)),
        h('span', { class: 'result-kind' }, labelForCategory(c.category)),
        h('p', null, c.summary)),
      commandBadges(c));
  }
  const t = result.item;
  return h('li', { class: 'result card', 'data-kind': 'task', 'data-id': t.id },
    h('a', { class: 'result-link', href: toHash({ view: 'task', id: t.id }) },
      h('span', { class: 'result-title' }, t.title),
      h('span', { class: 'result-kind' }, t.group === 'basics' ? 'Shell basics' : 'Walkthrough'),
      h('p', null, t.summary)));
}

function labelForCategory(id) {
  const c = state.categories.find((x) => x.id === id);
  return c ? c.label : id;
}

function viewHome(route) {
  const q = route.q.trim();
  const cat = route.category && state.categories.some((c) => c.id === route.category) ? route.category : null;
  const nodes = [];

  if (q) {
    const results = search(state.index, q, { category: cat });
    setTitle(`Search: ${q}`);
    nodes.push(heading(`Results for “${q}”`));
    if (cat) nodes.push(h('p', { class: 'muted' }, `Filtered to category: ${labelForCategory(cat)}. `, h('a', { href: toHash({ view: 'home', q }) }, 'Search all categories')));
    if (results.length) {
      nodes.push(h('p', { class: 'muted', id: 'result-count' }, `${results.length} match${results.length === 1 ? '' : 'es'}`));
      nodes.push(h('ul', { class: 'results', 'aria-labelledby': 'result-count' }, results.map(resultItem)));
    } else {
      nodes.push(emptyState(q, cat));
    }
    announce(results.length ? `${results.length} results` : 'No results');
    return nodes;
  }

  setTitle(cat ? labelForCategory(cat) : '');
  nodes.push(heading(cat ? labelForCategory(cat) : 'Linux commands, explained'));
  if (!cat) {
    nodes.push(h('p', { class: 'lead' },
      `${state.commands.length} common commands and ${state.tasks.length} task walkthroughs with explained examples, option tables and safety labels. Search by command name or by what you want to do.`));
    nodes.push(h('p', null, 'Try: '), h('ul', { class: 'chip-list', 'aria-label': 'Example searches' },
      EXAMPLE_QUERIES.map((s) => h('li', null, h('a', { href: toHash({ view: 'home', q: s }) }, s)))));
    nodes.push(riskLegend());
    nodes.push(h('h2', null, 'Task walkthroughs'));
    nodes.push(h('ul', { class: 'grid' }, state.tasks.filter((t) => t.group !== 'basics').map((t) =>
      h('li', { class: 'card' }, h('h3', null, h('a', { href: toHash({ view: 'task', id: t.id }) }, t.title)), h('p', { class: 'muted' }, t.summary)))));
    nodes.push(h('p', null, h('a', { href: '#/guides' }, 'All guides, including shell basics (redirection, quoting, pipes, sudo)')));
  }
  const cats = cat ? state.categories.filter((c) => c.id === cat) : state.categories;
  for (const c of cats) {
    const cmds = state.commands.filter((x) => x.category === c.id);
    const section = h('section', { 'aria-labelledby': `cat-${c.id}` },
      h(cat ? 'p' : 'h2', { id: `cat-${c.id}` }, cat ? c.description : c.label),
      cat ? null : h('p', { class: 'muted' }, c.description),
      h('ul', { class: 'grid' }, cmds.map((x) => h('li', { class: 'card', 'data-id': x.id },
        h('h3', null, commandLink(x)), h('p', null, x.summary), commandBadges(x)))));
    nodes.push(section);
  }
  return nodes;
}

function emptyState(q, cat) {
  return h('section', { class: 'card empty-state', 'data-empty': 'true' },
    h('h2', null, 'No matching commands or guides'),
    h('p', null, 'This is a curated guide, not a list of every Linux command. Some ideas:'),
    h('ul', null,
      cat ? h('li', null, h('a', { href: toHash({ view: 'home', q }) }, 'Search all categories'), ' instead of only this one.') : null,
      h('li', null, 'Describe the task in simple words, e.g. “disk space”, “ports”, “logs”, “usb”.'),
      h('li', null, 'Use fewer words: every word must match.'),
      h('li', null, 'On your own machine, ', h('code', null, 'man -k <keyword>'), ' (same as ', h('code', null, 'apropos'), ') searches the installed manual pages, and ', h('code', null, '<command> --help'), ' prints a summary for most programs.')),
    h('p', null, 'Try: '),
    h('ul', { class: 'chip-list' }, EXAMPLE_QUERIES.slice(0, 5).map((s) => h('li', null, h('a', { href: toHash({ view: 'home', q: s }) }, s)))));
}

function riskLegend() {
  return h('section', { class: 'card', 'aria-labelledby': 'legend-title' },
    h('h2', { id: 'legend-title' }, 'Safety labels'),
    h('dl', { class: 'legend' },
      ['read', 'modify', 'destructive'].map((r) => h('div', null, h('dt', null, riskBadge(r)), h('dd', null, RISK_LEVELS[r].description))),
      h('div', null, h('dt', null, rootBadge()), h('dd', null, ROOT_LABEL.description))),
    h('p', { class: 'muted' }, 'Destructive and root examples need a deliberate confirmation before copying. Labels are guidance for typical use, not a guarantee: always check what a command will touch.'));
}

function viewCommand(route) {
  const c = state.byId.get(route.id);
  if (!c) return viewNotFound();
  setTitle(c.name);
  const nodes = [];
  nodes.push(h('p', { class: 'muted' }, h('a', { href: toHash({ view: 'home', category: c.category }) }, labelForCategory(c.category))));
  nodes.push(heading(h('code', null, c.name)));
  nodes.push(h('p', { class: 'lead' }, c.summary));
  if (c.aliases && c.aliases.length) {
    nodes.push(h('p', { class: 'muted' }, 'Also searched as: ', c.aliases.join(', ')));
  }

  const docs = [];
  const site = c.manSite === 'debian' ? 'debian' : 'man7';
  const man = manUrl(c.man, site);
  if (man) docs.push(h('li', null, externalLink(man, `man page ${c.man.replace(/\.(\d)$/, '($1)')} on ${MAN_SITES[site]}`)));
  for (const d of c.docs || []) docs.push(h('li', null, externalLink(d.url, d.label)));
  if (!c.man) docs.push(h('li', null, 'Local help: ', h('code', null, c.install && c.install.status === 'builtin' ? `help ${c.name}` : `${c.name} --help`)));
  else {
    const [, page, section] = /^(.+)\.(\d)$/.exec(c.man);
    docs.push(h('li', null, 'Local manual: ', h('code', null, `man ${section} ${page}`)));
  }

  const install = c.install || {};
  const pk = install.packages || {};
  const rows = DISTROS.filter(([k]) => pk[k]).map(([k, label]) => h('tr', null, h('th', { scope: 'row' }, label), h('td', null, h('code', null, pk[k]))));
  nodes.push(h('div', { class: 'meta-grid' },
    h('section', { class: 'card', 'aria-labelledby': 'install-h' },
      h('h2', { id: 'install-h' }, 'Availability & package'),
      h('p', null, INSTALL_STATUS[install.status] || ''),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', null, h('caption', { class: 'visually-hidden' }, 'Package name by distribution'), h('tbody', null, rows))) : null,
      install.note ? h('p', null, install.note) : null,
      install.status !== 'builtin' ? h('p', { class: 'muted' }, 'Installing software is your decision; check with your package manager (see the Packages category).') : null),
    h('section', { class: 'card', 'aria-labelledby': 'compat-h' },
      h('h2', { id: 'compat-h' }, 'Compatibility notes'),
      h('p', null, c.compat || 'No special notes.'),
      h('h2', null, 'Documentation'),
      h('ul', null, docs))));

  nodes.push(h('h2', null, 'Examples'));
  nodes.push(h('ol', { class: 'examples' }, c.examples.map((ex, i) => exampleCard(ex, `${c.id}-${i}`))));

  const relatedTasks = state.tasks.filter((t) => (t.related || []).includes(c.id));
  if (relatedTasks.length) {
    nodes.push(h('h2', null, 'Guides that use it'));
    nodes.push(h('ul', null, relatedTasks.map((t) => h('li', null, h('a', { href: toHash({ view: 'task', id: t.id }) }, t.title)))));
  }
  const same = state.commands.filter((x) => x.category === c.category && x.id !== c.id);
  if (same.length) {
    nodes.push(h('h2', null, `More in ${labelForCategory(c.category)}`));
    nodes.push(h('ul', { class: 'chip-list' }, same.map((x) => h('li', null, commandLink(x)))));
  }
  return nodes;
}

function optionsTable(options) {
  if (!options || !options.length) return null;
  return h('details', { class: 'options', open: true },
    h('summary', null, 'Options explained'),
    h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Option'), h('th', { scope: 'col' }, 'Meaning'))),
      h('tbody', null, options.map(([flag, meaning]) => h('tr', null, h('td', null, h('code', null, flag)), h('td', null, meaning)))))));
}

function exampleCard(ex, id) {
  return h('li', { class: 'card example', id: `ex-${id}`, 'data-risk': ex.risk, 'data-root': ex.root ? 'true' : 'false' },
    h('h3', null, h('span', null, ex.title), badgesFor(ex)),
    ex.warning ? warningNote(ex.warning) : null,
    copyBlock(ex),
    h('p', null, ex.explain),
    optionsTable(ex.options),
    ex.output ? h('p', { class: 'output-note' }, h('strong', null, 'Reading the output:'), ex.output) : null);
}

function viewTask(route) {
  const t = state.taskById.get(route.id);
  if (!t) return viewNotFound();
  setTitle(t.title);
  const group = GROUPS.find(([g]) => g === t.group);
  const nodes = [
    h('p', { class: 'muted' }, h('a', { href: '#/guides' }, 'Guides'), ' › ', group ? group[1] : ''),
    heading(t.title),
    h('p', { class: 'lead' }, t.summary),
    h('p', { class: 'muted' }, 'Output differs between machines and distributions; the notes describe what to look for, not exact text.'),
    h('ol', { class: 'steps' }, t.steps.map((s, i) => h('li', { class: 'card', id: `step-${i + 1}`, 'data-risk': s.risk || 'none' },
      h('h3', null, h('span', null, s.title), s.cmd ? badgesFor(s) : null),
      s.warning ? warningNote(s.warning) : null,
      s.cmd ? copyBlock(s) : null,
      h('p', null, s.explain),
      s.output ? h('p', { class: 'output-note' }, h('strong', null, 'What the output means:'), s.output) : null,
      s.errors && s.errors.length ? h('div', null, h('strong', null, 'Common problems:'), h('ul', { class: 'errors' }, s.errors.map((e) => h('li', null, e)))) : null))),
  ];
  const related = (t.related || []).map((id) => state.byId.get(id)).filter(Boolean);
  if (related.length) {
    nodes.push(h('h2', null, 'Commands used'));
    nodes.push(h('ul', { class: 'chip-list' }, related.map((c) => h('li', null, commandLink(c)))));
  }
  return nodes;
}

function viewGuides() {
  setTitle('Guides');
  const nodes = [heading('Guides'), h('p', { class: 'lead' }, 'Step-by-step walkthroughs for common jobs, plus shell basics that make every command easier to use safely.')];
  for (const [g, label] of GROUPS) {
    const list = state.tasks.filter((t) => t.group === g);
    if (!list.length) continue;
    nodes.push(h('h2', { id: `group-${g}` }, label));
    nodes.push(h('ul', { class: 'grid' }, list.map((t) => h('li', { class: 'card' },
      h('h3', null, h('a', { href: toHash({ view: 'task', id: t.id }) }, t.title)),
      h('p', { class: 'muted' }, t.summary)))));
  }
  return nodes;
}

function viewAbout() {
  setTitle('About & safety');
  return [
    heading('About & safety'),
    h('p', { class: 'lead' }, 'A curated, beginner-friendly Linux command reference, with extra focus on C development, embedded Linux and driver work.'),
    h('h2', null, 'What this site does — and does not do'),
    h('ul', null,
      h('li', null, 'It shows commands for you to read, understand and copy. Nothing is executed in your browser and there is no server, account, analytics or tracking.'),
      h('li', null, 'It does not show real output from your machine. Output descriptions explain what to look for; real output varies by distribution, version and hardware.'),
      h('li', null, 'It is a curated selection, not every Linux command or option. For the full story, read the linked manual pages or run man <command> locally.')),
    riskLegend(),
    h('h2', null, 'Using copied commands safely'),
    h('ul', null,
      h('li', null, 'Replace every <placeholder> including the angle brackets. Leaving < or > in a command makes the shell treat it as a redirection, which can create or overwrite files.'),
      h('li', null, 'Quote values containing spaces or special characters with single quotes.'),
      h('li', null, 'Read the whole command in your terminal before pressing Enter, especially after pasting.'),
      h('li', null, 'Use sudo only for the specific command that needs it, and only after checking the target. Practise risky operations (kernel modules, disk writes) on a VM or test board.'),
      h('li', null, 'Safety labels describe typical use. They cannot know your system, so they do not make any command safe.')),
    h('h2', null, 'Sources and license'),
    h('p', null, 'All explanations are written for this project and checked against upstream manuals: the Linux man-pages project (man7.org), GNU manuals (coreutils, grep, sed, gawk, tar, make, GCC, binutils, Bash), and the official documentation of systemd, OpenSSH, curl, Git, CMake, kmod, util-linux and the distribution package managers. Links on each command page point to these sources.'),
    h('p', null, 'The search-first, example-driven format is inspired by the ', externalLink('https://tldr.sh/', 'tldr pages'), ' project; no tldr page content is copied. The site has no third-party runtime dependencies.'),
    h('p', null, 'Code and content are released under the MIT License. See the ', externalLink('https://github.com/itsnavin/linux-command-guide', 'GitHub repository'), ' to report mistakes or contribute.'),
  ];
}

function viewNotFound() {
  setTitle('Not found');
  return [
    heading('Page not found'),
    h('p', null, 'That command or guide is not in this catalog. ', h('a', { href: '#/' }, 'Browse all commands'), ' or use the search box.'),
  ];
}

// ------------------------------------------------------------ routing

function syncControls(route) {
  if (route.view === 'home') {
    if (document.activeElement !== searchInput && searchInput.value !== route.q) searchInput.value = route.q;
    categorySelect.value = route.category && state.categories.some((c) => c.id === route.category) ? route.category : '';
  }
  for (const a of document.querySelectorAll('[data-nav]')) {
    const active = a.dataset.nav === route.view || (a.dataset.nav === 'home' && route.view === 'command');
    if (active) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
}

function render(options = {}) {
  const route = parseRoute(window.location.hash);
  const previous = state.route;
  state.route = route;
  let nodes;
  switch (route.view) {
    case 'home': nodes = viewHome(route); break;
    case 'command': nodes = viewCommand(route); break;
    case 'task': nodes = viewTask(route); break;
    case 'guides': nodes = viewGuides(); break;
    case 'about': nodes = viewAbout(); break;
    default: nodes = viewNotFound();
  }
  main.replaceChildren(...nodes);
  syncControls(route);

  const fromSearchTyping = options.fromSearch === true;
  const sameView = previous && previous.view === route.view && route.view === 'home';
  if (!fromSearchTyping && !(sameView && document.activeElement === categorySelect)) {
    const h1 = main.querySelector('h1');
    if (previous && h1) h1.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

function navigateSearch(q, category) {
  const hash = toHash({ view: 'home', q, category });
  const current = parseRoute(window.location.hash);
  if (current.view === 'home') {
    window.history.replaceState(null, '', hash);
    render({ fromSearch: true });
  } else {
    window.history.pushState(null, '', hash);
    render({ fromSearch: true });
  }
}

let searchTimer = 0;

function setupControls() {
  for (const c of state.categories) categorySelect.append(h('option', { value: c.id }, c.label));

  searchInput.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => navigateSearch(searchInput.value, categorySelect.value || null), 120);
  });
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      searchInput.value = '';
      navigateSearch('', categorySelect.value || null);
    }
  });
  categorySelect.addEventListener('change', () => {
    navigateSearch(searchInput.value, categorySelect.value || null);
  });
  document.getElementById('search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    window.clearTimeout(searchTimer);
    navigateSearch(searchInput.value, categorySelect.value || null);
    const first = main.querySelector('.results a');
    if (first) first.focus();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    const typing = t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));
    if (typing) return;
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
  });
  window.addEventListener('hashchange', () => render());
  window.addEventListener('popstate', () => render());
}

// ------------------------------------------------------------ data

async function fetchJson(path) {
  const res = await fetch(path, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

async function loadData() {
  const categories = await fetchJson('data/categories.json');
  const [lists, tasks] = await Promise.all([
    Promise.all(categories.map((c) => fetchJson(`data/commands/${encodeURIComponent(c.id)}.json`))),
    fetchJson('data/tasks.json'),
  ]);
  state.categories = categories;
  state.commands = lists.flat();
  state.byId = new Map(state.commands.map((c) => [c.id, c]));
  state.tasks = tasks;
  state.taskById = new Map(tasks.map((t) => [t.id, t]));
  state.index = buildIndex(state.commands, state.tasks, state.categories);
}

async function start() {
  try {
    await loadData();
  } catch (err) {
    main.replaceChildren(h('p', { class: 'notice', role: 'alert' }, 'The command catalog could not be loaded. If you opened index.html directly from disk, serve the folder over HTTP instead (see README). Details: ', String(err.message || err)));
    return;
  }
  setupControls();
  render();
  document.documentElement.dataset.ready = 'true';
}

start();
