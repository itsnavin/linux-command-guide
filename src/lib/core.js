// Pure, DOM-free helpers: risk metadata, placeholders, search and routing.

export const RISK_LEVELS = {
  read: {
    label: 'Read-only',
    description: 'Only reads information. It should not change files or system state.',
  },
  modify: {
    label: 'Modifies',
    description: 'Creates or changes files, processes or settings. Check the target before running.',
  },
  destructive: {
    label: 'Destructive',
    description: 'Can delete, overwrite or interrupt things with no undo. Inspect every path before running.',
  },
};

export const RISK_ORDER = ['read', 'modify', 'destructive'];

export const ROOT_LABEL = {
  label: 'Needs root',
  description: 'Runs with administrator privileges (sudo). Mistakes can affect the whole system.',
};

// Placeholders look like <file> or <source-dir>. Real redirections in the
// catalog always have a space after < or >, so they never match this pattern.
export const PLACEHOLDER_SOURCE = '<([a-z][a-z0-9_.-]*)>';

export function hasPlaceholders(cmd) {
  return new RegExp(PLACEHOLDER_SOURCE).test(String(cmd));
}

export function splitPlaceholders(cmd) {
  const text = String(cmd);
  const parts = [];
  const re = new RegExp(PLACEHOLDER_SOURCE, 'g');
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), placeholder: false });
    parts.push({ text: m[0], placeholder: true, name: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), placeholder: false });
  return parts;
}

export function needsAcknowledgement(example) {
  return Boolean(example) && (example.risk === 'destructive' || example.root === true);
}

export function highestRisk(examples) {
  let best = 0;
  for (const ex of examples || []) {
    const i = RISK_ORDER.indexOf(ex.risk);
    if (i > best) best = i;
  }
  return RISK_ORDER[best];
}

export function anyRoot(examples) {
  return (examples || []).some((ex) => ex.root === true);
}

export const MAN_SITES = { man7: 'man7.org', debian: 'manpages.debian.org' };

export function manUrl(man, site = 'man7') {
  const m = /^([a-z0-9_.+-]+)\.([1-8])$/i.exec(String(man || ''));
  if (!m) return null;
  if (site === 'debian') return `https://manpages.debian.org/${m[1]}.${m[2]}`;
  return `https://man7.org/linux/man-pages/man${m[2]}/${m[1]}.${m[2]}.html`;
}

// ---------------------------------------------------------------- search

const STOPWORDS = new Set([
  'a', 'an', 'the', 'to', 'how', 'do', 'i', 'in', 'of', 'for', 'my', 'me', 'what', 'which',
  'is', 'on', 'with', 'and', 'or', 'can', 'see', 'linux', 'command', 'commands', 'use', 'using',
]);

export function normalize(value) {
  return String(value)
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '');
}

export function tokenize(query) {
  const raw = normalize(query)
    .split(/[^a-z0-9_.+\-/]+/)
    .filter(Boolean);
  const filtered = raw.filter((t) => !STOPWORDS.has(t));
  return filtered.length ? filtered : raw;
}

function stem(term) {
  if (term.length > 3 && term.endsWith('ies')) return term.slice(0, -3);
  if (term.length > 3 && term.endsWith('s') && !term.endsWith('ss')) return term.slice(0, -1);
  return term;
}

function joinText(list) {
  return normalize((list || []).filter(Boolean).join(' \n '));
}

export function buildIndex(commands, tasks, categories) {
  const catLabel = Object.fromEntries((categories || []).map((c) => [c.id, c.label]));
  const docs = [];
  for (const c of commands || []) {
    docs.push({
      kind: 'command',
      id: c.id,
      item: c,
      name: normalize(c.name),
      aliases: (c.aliases || []).map(normalize),
      fields: [
        { weight: 25, text: joinText(c.tags) },
        { weight: 15, text: normalize(c.summary) },
        { weight: 8, text: normalize(catLabel[c.category] || c.category) },
        { weight: 6, text: joinText((c.examples || []).flatMap((e) => [e.title, e.cmd, e.explain])) },
        {
          weight: 4,
          text: joinText((c.examples || []).flatMap((e) => (e.options || []).flatMap(([f, m]) => [f, m]))),
        },
        { weight: 2, text: normalize(c.compat || '') },
      ],
    });
  }
  for (const t of tasks || []) {
    docs.push({
      kind: 'task',
      id: t.id,
      item: t,
      name: normalize(t.title),
      aliases: [],
      fields: [
        { weight: 30, text: normalize(t.title) },
        { weight: 25, text: joinText(t.tags) },
        { weight: 15, text: normalize(t.summary) },
        { weight: 5, text: joinText((t.steps || []).flatMap((s) => [s.title, s.cmd, s.explain])) },
        { weight: 3, text: joinText(t.related) },
      ],
    });
  }
  return docs;
}

function scoreTerm(doc, term) {
  const s = stem(term);
  let best = 0;
  if (doc.kind === 'command') {
    if (doc.name === term) best = 100;
    else if (doc.name.startsWith(term)) best = 45;
    for (const a of doc.aliases) {
      if (a === term) best = Math.max(best, 80);
      else if (a.includes(s)) best = Math.max(best, 22);
    }
  }
  for (const f of doc.fields) {
    if (f.weight > best && f.text.includes(s)) best = f.weight;
  }
  return best;
}

export function search(index, query, options = {}) {
  const { category = null, limit = 60 } = options;
  const terms = tokenize(query || '');
  if (!terms.length) return [];
  const whole = normalize(String(query).trim());
  const results = [];
  for (const doc of index) {
    if (category && (doc.kind !== 'command' || doc.item.category !== category)) continue;
    let total = 0;
    let ok = true;
    for (const term of terms) {
      const s = scoreTerm(doc, term);
      if (!s) {
        ok = false;
        break;
      }
      total += s;
    }
    if (!ok) continue;
    if (doc.kind === 'command' && (doc.name === whole || doc.aliases.includes(whole))) total += 200;
    if (doc.kind === 'task' && doc.name.includes(whole)) total += 60;
    results.push({ kind: doc.kind, id: doc.id, item: doc.item, score: total });
  }
  results.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
  return results.slice(0, limit);
}

// ---------------------------------------------------------------- routing

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;

export function parseRoute(hash) {
  let h = String(hash || '');
  if (h.startsWith('#')) h = h.slice(1);
  if (!h.startsWith('/')) h = '/' + h;
  const qIndex = h.indexOf('?');
  const path = qIndex === -1 ? h : h.slice(0, qIndex);
  const params = new URLSearchParams(qIndex === -1 ? '' : h.slice(qIndex + 1));
  const segments = path.split('/').filter(Boolean).map((s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  });

  if (segments.length === 0) {
    const cat = params.get('cat');
    return { view: 'home', q: params.get('q') || '', category: cat && ID_RE.test(cat) ? cat : null };
  }
  const [first, second] = segments;
  if ((first === 'cmd' || first === 'task') && segments.length === 2) {
    if (!ID_RE.test(second)) return { view: 'notfound', path };
    return { view: first === 'cmd' ? 'command' : 'task', id: second };
  }
  if (segments.length === 1 && (first === 'guides' || first === 'about')) return { view: first };
  return { view: 'notfound', path };
}

export function toHash(route) {
  switch (route.view) {
    case 'command':
      return `#/cmd/${encodeURIComponent(route.id)}`;
    case 'task':
      return `#/task/${encodeURIComponent(route.id)}`;
    case 'guides':
      return '#/guides';
    case 'about':
      return '#/about';
    case 'home': {
      const params = new URLSearchParams();
      if (route.q) params.set('q', route.q);
      if (route.category) params.set('cat', route.category);
      const qs = params.toString();
      return qs ? `#/?${qs}` : '#/';
    }
    default:
      return '#/';
  }
}
