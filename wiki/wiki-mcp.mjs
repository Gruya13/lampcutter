#!/usr/bin/env node
/**
 * wiki-mcp — a shared knowledge base for several agents, exposed over MCP.
 *
 * Three layers, resolved from nearest to farthest:
 *
 *   agent    <project>/.wiki/agents/<AGENT>/   private working memory
 *   project  <project>/.wiki/shared/           shared per project
 *   global   ~/.agent-wiki/                    shared across projects
 *
 * Access control is enforced HERE, not on the filesystem. Agents run as the
 * same OS user, so file permissions cannot separate them; a server that refuses
 * the operation can. Identity and scope arrive through the environment, which
 * means one server process per agent — the natural MCP stdio arrangement.
 *
 *   WIKI_AGENT   required identity, e.g. "dsh"
 *   WIKI_ROOT    project root                     (default: cwd)
 *   WIKI_GLOBAL  global layer root                (default: ~/.agent-wiki)
 *   WIKI_READ    comma list of readable layers    (default: agent,project,global)
 *   WIKI_WRITE   comma list of writable layers    (default: agent)
 *
 * Nothing but JSON-RPC ever reaches stdout. Diagnostics go to stderr.
 *
 * Run with no arguments it speaks MCP on stdio; with arguments it is a CLI:
 *
 *   node wiki-mcp.mjs layers
 *   node wiki-mcp.mjs read knowledge/api.md
 *   node wiki-mcp.mjs write artifacts/x.md --layer project < body.md
 *   node wiki-mcp.mjs search "rate limiting"
 */
import { createInterface } from 'node:readline';
import { execFile } from 'node:child_process';
import { mkdir, readFile, writeFile, appendFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const SERVER_NAME = 'wiki';
const SERVER_VERSION = '1.0.0';
const ALL_LAYERS = ['agent', 'project', 'global'];

// ---------------------------------------------------------------- identity

const AGENT = process.env.WIKI_AGENT || 'anonymous';
const PROJECT_ROOT = path.resolve(process.env.WIKI_ROOT || process.cwd());
const GLOBAL_ROOT = path.resolve(process.env.WIKI_GLOBAL || path.join(os.homedir(), '.agent-wiki'));

function layerList(raw, fallback) {
  if (raw === undefined) return [...fallback];
  const parts = raw.split(',').map((s) => s.trim()).filter(Boolean);
  const unknown = parts.filter((p) => !ALL_LAYERS.includes(p));
  if (unknown.length) throw new Error(`unknown layer(s) in scope: ${unknown.join(', ')}`);
  return parts;
}

const READ_LAYERS = layerList(process.env.WIKI_READ, ['agent', 'project', 'global']);
const WRITE_LAYERS = layerList(process.env.WIKI_WRITE, ['agent']);

function log(...args) {
  process.stderr.write(`[wiki:${AGENT}] ${args.join(' ')}\n`);
}

function layerRoot(layer) {
  switch (layer) {
    case 'agent': return path.join(PROJECT_ROOT, '.wiki', 'agents', AGENT);
    // Deliberately a sibling of agents/, never its parent: nesting the private
    // agent layer inside the shared project layer would leak every agent's
    // notes into every other agent's project-wide list and search.
    case 'project': return path.join(PROJECT_ROOT, '.wiki', 'shared');
    case 'global': return GLOBAL_ROOT;
    default: throw new Error(`unknown layer "${layer}" — expected one of ${ALL_LAYERS.join(', ')}`);
  }
}

function requireRead(layer) {
  if (!ALL_LAYERS.includes(layer)) throw new Error(`unknown layer "${layer}"`);
  if (!READ_LAYERS.includes(layer)) throw new Error(`layer "${layer}" is not readable for agent "${AGENT}"`);
}

function requireWrite(layer) {
  if (!ALL_LAYERS.includes(layer)) throw new Error(`unknown layer "${layer}"`);
  if (!WRITE_LAYERS.includes(layer)) throw new Error(`layer "${layer}" is read-only for agent "${AGENT}"`);
}

/** Resolve a relative note path inside one layer, refusing any escape. */
function resolveInLayer(layer, rel) {
  if (typeof rel !== 'string' || !rel.trim()) throw new Error('path is required');
  const root = layerRoot(layer);
  const clean = path.normalize(rel.replace(/^[/\\]+/, ''));
  if (clean === '.' || clean === '..' || clean.startsWith('..' + path.sep)) {
    throw new Error(`path escapes the ${layer} layer: ${rel}`);
  }
  const full = path.resolve(root, clean);
  const prefix = root.endsWith(path.sep) ? root : root + path.sep;
  if (full !== root && !full.startsWith(prefix)) throw new Error(`path escapes the ${layer} layer: ${rel}`);
  return full;
}

// -------------------------------------------------------------------- git

/**
 * Commit one write, signed with the writing agent's name.
 *
 * Every write becomes a commit authored by the agent that made it, which turns
 * `git log` into the audit trail the wiki otherwise lacks: who changed what,
 * and when. The identity is passed per-invocation with `-c` so it works even on
 * a machine with no global git identity configured, and no repository settings
 * are mutated.
 *
 * A repository that ignores the layer (`.wiki/.gitignore` excludes `agents/`)
 * simply produces "no changes" — private notes stay out of shared history.
 *
 * Set WIKI_GIT=0 to skip committing entirely.
 */
function gitCommit(root, message) {
  return new Promise((resolve) => {
    if (process.env.WIKI_GIT === '0') return resolve({ skipped: 'disabled (WIKI_GIT=0)' });

    execFile('git', ['-C', root, 'rev-parse', '--is-inside-work-tree'], (probeError, probeOut) => {
      if (probeError || String(probeOut).trim() !== 'true') return resolve({ skipped: 'not in a git repository' });

      const identity = ['-c', `user.name=${AGENT}`, '-c', `user.email=${AGENT}@agent-wiki.local`];
      execFile('git', ['-C', root, ...identity, 'add', '-A'], (addError) => {
        if (addError) return resolve({ skipped: `git add failed` });

        execFile('git', ['-C', root, ...identity, 'commit', '-m', message], (commitError, commitOut) => {
          if (commitError) {
            const text = `${commitError.stderr ?? ''}${commitOut ?? ''}`;
            if (/nothing to commit|no changes added/i.test(text)) return resolve({ skipped: 'nothing to commit' });
            return resolve({ skipped: `git commit failed: ${text.split('\n')[0].slice(0, 80)}` });
          }
          const sha = String(commitOut).match(/\[[^\]]*?([0-9a-f]{7,})\]/)?.[1];
          return resolve({ committed: true, sha, message });
        });
      });
    });
  });
}

// ------------------------------------------------------------------ notes

function hasFrontmatter(text) {
  return text.startsWith('---\n') || text.startsWith('---\r\n');
}

function addFrontmatter(content, layer, now) {
  const header = [
    '---',
    `agent: ${AGENT}`,
    `layer: ${layer}`,
    `created: ${now}`,
    `updated: ${now}`,
    '---',
    '',
  ].join('\n');
  return header + content;
}

/** Recursively list every file under one layer root, relative to it. */
async function walk(dir, base = dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const out = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await walk(full, base));
    else if (entry.isFile()) out.push(path.relative(base, full));
  }
  return out;
}

// ------------------------------------------------------------------- tools

const TOOLS = [
  {
    name: 'wiki_layers',
    description: 'Show which knowledge layers exist for this agent, where they live on disk, and whether this agent may read or write each one. Call this first when unsure what knowledge you can reach.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'wiki_read',
    description: 'Read a note by relative path, e.g. "knowledge/api.md". Searches the nearest layer first (agent, then project, then global) and returns the first match, labelled with the layer it came from.',
    inputSchema: {
      type: 'object',
      properties: { path: { type: 'string', description: 'Relative note path, e.g. knowledge/api.md' } },
      required: ['path'],
      additionalProperties: false,
    },
  },
  {
    name: 'wiki_write',
    description: 'Create or replace a note. Defaults to the private agent layer. Writing to "project" or "global" requires that layer to be in this agent\'s write scope, otherwise the call fails. Frontmatter is added when the content does not already start with one.',
    inputSchema: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Relative note path, e.g. knowledge/api.md' },
        content: { type: 'string', description: 'Full note body (markdown)' },
        layer: { type: 'string', enum: ALL_LAYERS, description: 'Target layer; defaults to agent' },
      },
      required: ['path', 'content'],
      additionalProperties: false,
    },
  },
  {
    name: 'wiki_append',
    description: 'Append text to a note without rewriting it — for journals and running logs. Creates the note if missing, with no frontmatter.',
    inputSchema: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Relative note path' },
        text: { type: 'string', description: 'Text to append' },
        layer: { type: 'string', enum: ALL_LAYERS, description: 'Target layer; defaults to agent' },
      },
      required: ['path', 'text'],
      additionalProperties: false,
    },
  },
  {
    name: 'wiki_list',
    description: 'List note paths available to this agent, across every readable layer or one named layer, optionally filtered by a path prefix.',
    inputSchema: {
      type: 'object',
      properties: {
        layer: { type: 'string', enum: ALL_LAYERS, description: 'Limit to one layer' },
        prefix: { type: 'string', description: 'Only paths starting with this string' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'wiki_search',
    description: 'Search note contents across every readable layer. Returns matching lines with their layer and path. Use this to find what other agents have already written down before starting work.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Case-insensitive substring to search for' },
        limit: { type: 'number', description: 'Maximum matching lines to return (default 20)' },
      },
      required: ['query'],
      additionalProperties: false,
    },
  },
];

async function toolLayers() {
  const lines = [
    `agent:        ${AGENT}`,
    `project root: ${PROJECT_ROOT}`,
    `read scope:   ${READ_LAYERS.join(', ') || '(none)'}`,
    `write scope:  ${WRITE_LAYERS.join(', ') || '(none)'}`,
    '',
    'layer     read  write  path',
  ];
  for (const layer of ALL_LAYERS) {
    const canRead = READ_LAYERS.includes(layer) ? 'yes' : 'no ';
    const canWrite = WRITE_LAYERS.includes(layer) ? 'yes' : 'no ';
    lines.push(`${layer.padEnd(9)} ${canRead.padEnd(5)} ${canWrite.padEnd(6)} ${layerRoot(layer)}`);
  }
  return lines.join('\n');
}

async function toolRead({ path: rel }) {
  const tried = [];
  for (const layer of READ_LAYERS) {
    const full = resolveInLayer(layer, rel);
    try {
      const text = await readFile(full, 'utf8');
      // Show a project-relative path when it is inside the project, otherwise the
      // absolute one — "../../../.agent-wiki/..." is not a useful label.
      const shown = path.relative(PROJECT_ROOT, full);
      return `[layer: ${layer} | ${shown.startsWith('..') ? full : shown}]\n\n${text}`;
    } catch {
      tried.push(layer);
    }
  }
  throw new Error(`note not found in any readable layer (${tried.join(', ')}): ${rel}`);
}

/** Render a git outcome for a tool result, without noise for normal cases. */
function gitNote(git) {
  if (git?.committed) return `\ncommitted ${(git.sha ?? '').slice(0, 8)}`;
  const quiet = ['not in a git repository', 'nothing to commit', 'disabled (WIKI_GIT=0)'];
  if (git?.skipped && !quiet.includes(git.skipped)) return `\n(git: ${git.skipped})`;
  return '';
}

async function toolWrite({ path: rel, content, layer = 'agent' }) {
  requireWrite(layer);
  const full = resolveInLayer(layer, rel);
  await mkdir(path.dirname(full), { recursive: true });
  const now = new Date().toISOString();
  const body = hasFrontmatter(content) ? content : addFrontmatter(content, layer, now);
  await writeFile(full, body, 'utf8');
  const git = await gitCommit(layerRoot(layer), `write ${layer}:${rel}`);
  return `wrote ${layer}:${rel} — ${Buffer.byteLength(body)} bytes\n${full}${gitNote(git)}`;
}

async function toolAppend({ path: rel, text, layer = 'agent' }) {
  requireWrite(layer);
  const full = resolveInLayer(layer, rel);
  await mkdir(path.dirname(full), { recursive: true });
  const stamp = new Date().toISOString();
  await appendFile(full, `\n## ${stamp} — ${AGENT}\n\n${text}\n`, 'utf8');
  const git = await gitCommit(layerRoot(layer), `append ${layer}:${rel}`);
  return `appended to ${layer}:${rel}\n${full}${gitNote(git)}`;
}

async function toolList({ layer, prefix = '' }) {
  const layers = layer ? [layer] : READ_LAYERS;
  const out = [];
  for (const l of layers) {
    requireRead(l);
    const root = layerRoot(l);
    const files = await walk(root);
    for (const file of files.sort()) {
      if (prefix && !file.startsWith(prefix)) continue;
      out.push(`${l}:${file}`);
    }
  }
  if (!out.length) return `no notes found (layers: ${layers.join(', ')}${prefix ? `, prefix: ${prefix}` : ''})`;
  return `${out.length} note(s)\n\n${out.join('\n')}`;
}

async function toolSearch({ query, limit = 20 }) {
  if (!query || typeof query !== 'string') throw new Error('query is required');
  const needle = query.toLowerCase();
  const max = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : 20;
  const hits = [];
  for (const layer of READ_LAYERS) {
    const root = layerRoot(layer);
    for (const file of (await walk(root)).sort()) {
      let text;
      try {
        text = await readFile(path.join(root, file), 'utf8');
      } catch {
        continue;
      }
      const lines = text.split('\n');
      for (let i = 0; i < lines.length; i += 1) {
        if (lines[i].toLowerCase().includes(needle)) {
          hits.push(`${layer}:${file}:${i + 1}: ${lines[i].trim().slice(0, 240)}`);
          if (hits.length >= max) {
            return `${hits.length} match(es), truncated at ${max}\n\n${hits.join('\n')}`;
          }
        }
      }
    }
  }
  if (!hits.length) return `no matches for "${query}"`;
  return `${hits.length} match(es)\n\n${hits.join('\n')}`;
}

const HANDLERS = {
  wiki_layers: toolLayers,
  wiki_read: toolRead,
  wiki_write: toolWrite,
  wiki_append: toolAppend,
  wiki_list: toolList,
  wiki_search: toolSearch,
};

// -------------------------------------------------------------- json-rpc

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function textResult(text, isError = false) {
  return { content: [{ type: 'text', text }], isError };
}

async function handle(msg) {
  const { method, params } = msg;

  if (method === 'initialize') {
    const requested = params?.protocolVersion;
    return {
      protocolVersion: typeof requested === 'string' ? requested : '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
    };
  }

  if (method === 'ping') return {};

  if (method === 'tools/list') return { tools: TOOLS };

  if (method === 'tools/call') {
    const name = params?.name;
    const args = params?.arguments ?? {};
    const handler = HANDLERS[name];
    if (!handler) return textResult(`unknown tool "${name}" — available: ${Object.keys(HANDLERS).join(', ')}`, true);
    try {
      return textResult(await handler(args));
    } catch (error) {
      log(`tool ${name} failed: ${error.message}`);
      return textResult(`error: ${error.message}`, true);
    }
  }

  const error = new Error(`method not found: ${method}`);
  error.code = -32601;
  throw error;
}

// -------------------------------------------------------------------- cli

function readStdin() {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) return resolve('');
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
  });
}

/**
 * The same contract over argv, for agents that reach the wiki through a shell
 * tool instead of MCP. Identity and scope still come from the environment, so
 * the access rules are identical — this is a second interface, not a second
 * implementation.
 */
async function cliMain(argv) {
  const [command, ...rest] = argv;
  const flags = {};
  const positional = [];
  for (let i = 0; i < rest.length; i += 1) {
    if (rest[i].startsWith('--')) {
      flags[rest[i].slice(2)] = rest[i + 1] ?? true;
      i += 1;
    } else {
      positional.push(rest[i]);
    }
  }

  switch (command) {
    case 'layers':
      return toolLayers();
    case 'read':
      return toolRead({ path: positional[0] });
    case 'write':
      return toolWrite({ path: positional[0], content: flags.content ?? await readStdin(), layer: flags.layer ?? 'agent' });
    case 'append':
      return toolAppend({ path: positional[0], text: flags.text ?? await readStdin(), layer: flags.layer ?? 'agent' });
    case 'list':
      return toolList({ layer: flags.layer, prefix: flags.prefix ?? '' });
    case 'search':
      return toolSearch({ query: positional.join(' '), limit: flags.limit ? Number(flags.limit) : 20 });
    default: {
      const error = new Error(`unknown command "${command}" — use: layers, read, write, append, list, search`);
      error.code = 2;
      throw error;
    }
  }
}

// ------------------------------------------------------------------- main

function startServer() {
  log(`serving | root=${PROJECT_ROOT} | global=${GLOBAL_ROOT} | read=${READ_LAYERS.join('+')} | write=${WRITE_LAYERS.join('+')}`);

  const rl = createInterface({ input: process.stdin, terminal: false });
  rl.on('line', (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let msg;
    try {
      msg = JSON.parse(trimmed);
    } catch {
      log('ignoring non-JSON line on stdin');
      return;
    }
    if (msg.id === undefined) return; // notification
    handle(msg)
      .then((result) => send({ jsonrpc: '2.0', id: msg.id, result }))
      .catch((error) => {
        if (error.code) send({ jsonrpc: '2.0', id: msg.id, error: { code: error.code, message: error.message } });
        else send({ jsonrpc: '2.0', id: msg.id, result: textResult(`error: ${error.message}`, true) });
      });
  });
  rl.on('close', () => process.exit(0));
}

const argv = process.argv.slice(2);
if (argv.length) {
  cliMain(argv)
    .then((text) => { process.stdout.write(`${text}\n`); })
    .catch((error) => { process.stderr.write(`wiki: ${error.message}\n`); process.exitCode = error.code ?? 1; });
} else {
  startServer();
}
