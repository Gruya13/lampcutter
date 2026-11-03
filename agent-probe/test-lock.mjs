#!/usr/bin/env node
/**
 * test-lock — zamrzava test set i dokazuje da se nije menjao.
 *
 * Podela uloga je stroga: **testove piše asistent, orkestrator ih izvršava i ne
 * sme da ih menja**. Ako izvršeni test ne valja, orkestrator se obraća autoru —
 * ne ispravlja ga sam. Ova skripta je mehanizam koji to pravilo čini
 * proverljivim, a ne samo izgovorenim:
 *
 *   lock   — autor (ili orkestrator pri prijemu) zabeleži sha256 test seta;
 *   check  — svako izvršavanje prvo dokaže da je hash isti;
 *   show   — ispiše šta je zaključano i da li je bilo ponovnog zaključavanja.
 *
 * Zaključan test se **ne menja**. Ako izmena ipak mora da se desi, radi se kroz
 * `--relock`, koja zahteva `--by` i `--reason` i trajno ostavlja trag u fajlu
 * zaključavanja. Watchdog (codex) radi nezavisnu proveru istim alatom, iz svoje
 * niti, i prijavljuje svaku razliku.
 *
 * Usage:
 *   node test-lock.mjs lock  <cases.json> [--by <ime>] [--json]
 *   node test-lock.mjs check <cases.json> [--json]
 *   node test-lock.mjs show  <cases.json>
 *
 * Exit codes: 0 ok · 1 changed · 2 not locked · 3 usage/IO error
 */
import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { lockVerdict } from './lock-verdict.mjs';
import { fileURLToPath } from 'node:url';

const WIKI_SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'wiki', 'wiki-mcp.mjs');

export const LOCK_VERSION = 1;
export const EXIT_OK = 0;
export const EXIT_CHANGED = 1;
export const EXIT_UNLOCKED = 2;
export const EXIT_ERROR = 3;
/** The git provenance of a test set does not support its lock. */
export const EXIT_GIT = 4;

/** The sidecar path that holds one test set's lock. */
export function lockPathFor(casesFile) {
  return `${casesFile}.lock.json`;
}

/** sha256 of a file's bytes, read as-is. */
function sha256Of(text) {
  return createHash('sha256').update(text).digest('hex');
}

/** Strip a leading wiki YAML header, preserving the body's exact bytes. */
export function casesBody(text) {
  return text.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '');
}

/** Read a cases file and describe it without interpreting the cases. */
function describeCases(casesFile) {
  const text = casesBody(readFileSync(casesFile, 'utf8'));
  const parsed = JSON.parse(text);
  const cases = Array.isArray(parsed) ? parsed : parsed.cases;
  return {
    sha256: sha256Of(text),
    cases: Array.isArray(cases) ? cases.length : 0,
    entry: typeof parsed?.entry === 'string' ? parsed.entry : '',
  };
}

/** Read a lock file, or undefined when there is none. */
export function readLock(casesFile) {
  const lockPath = lockPathFor(casesFile);
  if (!existsSync(lockPath)) return undefined;
  try {
    return JSON.parse(readFileSync(lockPath, 'utf8'));
  } catch (error) {
    throw new Error(`lock file is unreadable: ${lockPath}: ${error.message}`);
  }
}

/** Whether git knows the sidecar; undefined outside a repository. */
function lockVersioned(casesFile) {
  const abs = path.resolve(lockPathFor(casesFile));
  let root;
  try { root = git(['rev-parse', '--show-toplevel'], path.dirname(abs)).trim(); }
  catch { return undefined; }
  try { git(['ls-files', '--error-unmatch', '--', path.relative(root, abs)], root); return true; }
  catch { return false; }
}

// ── git provenance ───────────────────────────────────────────────────────────

/** Run one git command; throws when git does. */
function git(args, cwd) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 15000 });
}

/**
 * Where a test set stands in git, and whether the locked hash is recoverable
 * from the revision the lock names.
 *
 * A sidecar lock proves only that a file has not changed since it was locked —
 * and the orchestrator, who runs tests rather than writing them, could have
 * written both. Git closes that: when the author commits the test set, the
 * revision is a record the orchestrator did not create, and `blobMatchesLock`
 * checks that the content behind that revision is exactly the content the lock
 * froze. A hash that cannot be recovered from an authored revision is not
 * evidence of anything.
 *
 * @returns {{state: 'clean'|'dirty'|'untracked'|'nogit', root: string, rel: string, head: string, blobMatchesLock: boolean|undefined}}
 */
export function gitProvenance(casesFile, lock) {
  const abs = path.resolve(casesFile);
  try {
    const root = git(['rev-parse', '--show-toplevel'], path.dirname(abs)).trim();
    const rel = path.relative(root, abs);
    let tracked = true;
    try {
      git(['ls-files', '--error-unmatch', '--', rel], root);
    } catch (error) {
      tracked = false;
    }
    const dirty = tracked && git(['status', '--porcelain', '--', rel], root).trim() !== '';
    const state = !tracked ? 'untracked' : dirty ? 'dirty' : 'clean';
    const result = { state, root, rel, head: '', blobMatchesLock: undefined };

    let head = '';
    try {
      head = git(['rev-parse', 'HEAD'], root).trim();
    } catch (error) {
      head = '';
    }
    result.head = head;

    const revision = typeof lock?.gitRevision === 'string' && lock.gitRevision !== '' ? lock.gitRevision : '';
    if (revision !== '' && typeof lock?.casesSha256 === 'string') {
      try {
        const blob = execFileSync('git', ['show', `${revision}:${typeof lock.gitRel === 'string' ? lock.gitRel : rel}`], {
          cwd: root,
          encoding: 'buffer',
          stdio: ['ignore', 'pipe', 'ignore'],
          timeout: 15000,
        });
        result.blobMatchesLock = sha256Of(casesBody(blob.toString('utf8'))) === lock.casesSha256;
      } catch (error) {
        result.blobMatchesLock = false;
      }
    }
    return result;
  } catch (error) {
    return { state: 'nogit', root: '', rel: '', head: '', blobMatchesLock: undefined };
  }
}

/**
 * Lock one test set. A test that is already locked is never re-locked silently:
 * a different hash is refused unless `relock` is set, and then the change is
 * recorded with who did it and why.
 *
 * @returns {{status: 'locked'|'unchanged'|'relocked', lock: object, previous: object|undefined}}
 */
export function lockCases(casesFile, { by = 'unknown', reason = '', relock = false, requireGit = false, now = () => new Date().toISOString() } = {}) {
  const { sha256, cases, entry } = describeCases(casesFile);
  const existing = readLock(casesFile);

  // A lock on a working copy nobody committed is a lock the orchestrator could
  // have written alone. Authors commit; `--require-git` demands that.
  const provenance = gitProvenance(casesFile, undefined);
  if (requireGit && provenance.state !== 'clean') {
    throw new Error(
      `the test set is not committed, so there is no authored revision to trust: ${casesFile}\n`
      + `  git says: ${provenance.state}${provenance.root === '' ? '' : ` (${provenance.rel})`}\n`
      + '  commit it first (the author does that in the wiki), then lock it.',
    );
  }

  const base = {
    version: LOCK_VERSION,
    casesFile: path.basename(casesFile),
    casesSha256: sha256,
    cases,
    entry,
    gitRel: provenance.rel,
    gitState: provenance.state,
    gitRevision: provenance.state === 'clean' ? provenance.head : '',
  };

  if (existing === undefined) {
    const lock = { ...base, lockedAt: now(), lockedBy: by, relocks: [] };
    writeFileSync(lockPathFor(casesFile), `${JSON.stringify(lock, null, 2)}\n`, 'utf8');
    return { status: 'locked', lock, previous: undefined };
  }

  if (existing.casesSha256 === sha256) {
    return { status: 'unchanged', lock: existing, previous: undefined };
  }

  if (!relock) {
    throw new Error(
      `a locked test set is never edited: ${casesFile}\n`
      + `  locked sha256 ${String(existing.casesSha256).slice(0, 16)}… by ${existing.lockedBy} at ${existing.lockedAt}\n`
      + `  now    sha256 ${sha256.slice(0, 16)}…\n`
      + 'If the author really changed the test, record it: --relock --by <ime> --reason "<zasto>".',
    );
  }

  const relockEntry = {
    at: now(),
    by,
    reason,
    from: existing.casesSha256,
    to: sha256,
  };
  const lock = {
    ...base,
    lockedAt: existing.lockedAt,
    lockedBy: existing.lockedBy,
    relocks: [...(Array.isArray(existing.relocks) ? existing.relocks : []), relockEntry],
  };
  writeFileSync(lockPathFor(casesFile), `${JSON.stringify(lock, null, 2)}\n`, 'utf8');
  return { status: 'relocked', lock, previous: existing };
}

/**
 * Compare a test set against its lock, and the lock against its authored
 * revision.
 *
 * @returns {{status: 'ok'|'changed'|'unlocked'|'unproven'|'uncommitted'|'unversioned', lock?: object, sha256: string, git: object}}
 */
export function checkCases(casesFile, { requireGit = false } = {}) {
  const { sha256 } = describeCases(casesFile);
  const lock = readLock(casesFile);
  const gitInfo = gitProvenance(casesFile, lock);
  // The decision itself is a pure function with an independently authored
  // test set (agent-probe/pipelines/cases-lock-verdict.json, locked by agy):
  // this function only supplies the inputs. That keeps rule 5 — a lock that
  // names no revision proves nothing once git is available — testable
  // without a repository, a spawn, or this script.
  const verdict = lockVerdict({ lock, sha256, git: gitInfo, requireGit });
  const status = requireGit === true && verdict === 'ok'
    && lock !== undefined && lockVersioned(casesFile) === false
    ? 'unversioned'
    : verdict;
  return { status, ...(lock === undefined ? {} : { lock }), sha256, git: gitInfo };
}

// ── the git-verifiable copy of the lock ──────────────────────────────────────

/**
 * Write one lock through the wiki server.
 *
 * The sidecar lock file lives next to the tests, where the orchestrator *could*
 * rewrite it. The wiki layer is a git repository, so a copy written there is
 * append-only in practice: the hash a test set was locked at can be read back
 * from the log, and a rewrite shows up as a new revision with a different hash.
 * That is the evidence the codex watchdog checks.
 */
function wikiWrite(notePath, content, layer) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(process.execPath, [WIKI_SERVER, 'write', notePath, '--layer', layer], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          // A CLI invocation has no MCP identity in its environment, and the
          // wiki defaults to `anonymous`, which may write nothing. The lock note
          // is written by the orchestrator, so name it and grant the layers it
          // records into; an author's own `--by` stays a field of the note.
          WIKI_AGENT: process.env.WIKI_AGENT ?? 'dsh',
          WIKI_WRITE: process.env.WIKI_WRITE ?? 'agent,project',
        },
      });
    } catch (error) {
      return resolve({ ok: false, message: String(error) });
    }
    let out = '';
    let err = '';
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => resolve({ ok: false, message: String(e) }));
    child.on('close', (code) => resolve({ ok: code === 0, message: (out || err).trim() }));
    child.stdin.end(content);
  });
}

/** The note path one cases file's lock is recorded under. */
export function wikiNotePath(casesFile) {
  const stem = path.basename(casesFile).replace(/[^\w.-]+/g, '-');
  return `artifacts/test-lock-${stem}.md`;
}

/** The markdown body recording one lock, including every relock. */
export function wikiNote(lock, casesFile) {
  const lines = [
    `# Test lock: ${path.basename(casesFile)}`,
    '',
    '| field | value |',
    '|---|---|',
    `| casesFile | \`${casesFile}\` |`,
    `| cases sha256 | \`${lock.casesSha256}\` |`,
    `| git | ${lock.gitState ?? 'nogit'}${lock.gitRevision ? ` @ ${String(lock.gitRevision).slice(0, 12)}` : ''} |`,
    `| cases | ${lock.cases} |`,
    `| entry | \`${lock.entry}\` |`,
    `| lockedBy | ${lock.lockedBy} |`,
    `| lockedAt | ${lock.lockedAt} |`,
    `| relocks | ${Array.isArray(lock.relocks) ? lock.relocks.length : 0} |`,
    '',
    'The test set is frozen at the hash above. The orchestrator runs tests; it',
    'does not write or edit them. An edit is only legitimate through',
    '`--relock --by <ime> --reason "<zasto>"`, and it appears below.',
  ];
  const relocks = Array.isArray(lock.relocks) ? lock.relocks : [];
  if (relocks.length > 0) {
    lines.push('', '## Relocks', '', '| at | by | reason | from | to |', '|---|---|---|---|---|');
    for (const entry of relocks) {
      lines.push(`| ${entry.at} | ${entry.by} | ${entry.reason} | \`${String(entry.from).slice(0, 16)}…\` | \`${String(entry.to).slice(0, 16)}…\` |`);
    }
  }
  lines.push('');
  return lines.join('\n');
}

/** Parse argv for the three subcommands. */
function parseArgs(argv) {
  const [command, casesFile, ...rest] = argv;
  const opts = { command, casesFile, by: '', reason: '', relock: false, json: false, wiki: false, layer: 'project', requireGit: false };
  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i];
    if (arg === '--by') { i += 1; opts.by = rest[i] ?? ''; }
    else if (arg === '--reason') { i += 1; opts.reason = rest[i] ?? ''; }
    else if (arg === '--relock') opts.relock = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--wiki') opts.wiki = true;
    else if (arg === '--require-git') opts.requireGit = true;
    else if (arg === '--layer') { i += 1; opts.layer = rest[i] ?? 'project'; }
    else throw new Error(`unknown argument: ${arg}`);
  }
  return opts;
}

const HELP = `test-lock — zamrzava test set i dokazuje da se nije menjao

  node test-lock.mjs lock  <cases.json> [--by <ime>] [--wiki] [--require-git] [--json]
  node test-lock.mjs check <cases.json> [--require-git] [--json]
  node test-lock.mjs show  <cases.json>

  --by <ime>       ko zakljucava (autor testa, ili orkestrator pri prijemu)
  --wiki           upisi lock i u wiki (git-verzovana kopija dokaza)
  --require-git    zahtevaj da je test set commitovan od autora (git clean)
  --layer <sloj>   wiki sloj za --wiki (default: project)
  --relock         dozvoli izmenu zakljucanog testa; zahteva --by i --reason
  --reason <tekst> zasto je zakljucani test menjan (upisuje se trajno)

Exit: 0 ok · 1 changed · 2 not locked · 3 greska · 4 git provenijencija ne drzi`;

export async function main(argv, io = {}) {
  const out = io.log ?? ((line) => console.log(line));
  const err = io.error ?? ((line) => console.error(line));
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (error) {
    err(String(error.message));
    return EXIT_ERROR;
  }
  if (opts.command === undefined || opts.command === '--help' || opts.command === '-h') {
    out(HELP);
    return opts.command === undefined ? EXIT_ERROR : EXIT_OK;
  }
  if (typeof opts.casesFile !== 'string' || opts.casesFile.length === 0) {
    err('a cases file is required (see --help)');
    return EXIT_ERROR;
  }
  if (!existsSync(opts.casesFile)) {
    err(`no such cases file: ${opts.casesFile}`);
    return EXIT_ERROR;
  }

  try {
    if (opts.command === 'lock') {
      if (opts.relock && (opts.by === '' || opts.reason === '')) {
        err('--relock requires both --by and --reason');
        return EXIT_ERROR;
      }
      const result = lockCases(opts.casesFile, { by: opts.by || 'unknown', reason: opts.reason, relock: opts.relock, requireGit: opts.requireGit });
      if (lockVersioned(opts.casesFile) === false) {
        err(`WARNING: lock must be committed to git with the test set: ${lockPathFor(opts.casesFile)}`);
      }
      const wiki = opts.wiki
        ? await wikiWrite(wikiNotePath(opts.casesFile), wikiNote(result.lock, opts.casesFile), opts.layer)
        : undefined;
      const where = result.lock.gitRevision === ''
        ? `git ${result.lock.gitState}`
        : `git ${result.lock.gitState}@${result.lock.gitRevision.slice(0, 8)}`;
      if (opts.json) {
        out(JSON.stringify({ status: result.status, lock: result.lock, ...(wiki === undefined ? {} : { wiki }) }, null, 2));
      } else {
        if (result.status === 'unchanged') {
          out(`UNCHANGED ${opts.casesFile} sha256 ${result.lock.casesSha256.slice(0, 16)}… (${where})`);
        } else {
          out(`${result.status === 'relocked' ? 'RELOCKED' : 'LOCKED'} ${opts.casesFile} `
            + `sha256 ${result.lock.casesSha256.slice(0, 16)}… (${result.lock.cases} cases, by ${result.lock.lockedBy}, ${where})`);
        }
        if (wiki !== undefined) out(wiki.ok ? `wiki: ${wiki.message.split('\n')[0]}` : `wiki write failed: ${wiki.message}`);
      }
      return EXIT_OK;
    }

    if (opts.command === 'check') {
      const result = checkCases(opts.casesFile, { requireGit: opts.requireGit });
      if (opts.json) out(JSON.stringify(result, null, 2));
      else if (result.status === 'ok') {
        const rev = result.git.head === '' ? '' : `@${result.git.head.slice(0, 8)}`;
        out(`LOCKED ${opts.casesFile} sha256 ${result.sha256.slice(0, 16)}… (git ${result.git.state}${rev})`);
      } else if (result.status === 'changed') {
        err(`CHANGED ${opts.casesFile}`);
        err(`  locked ${String(result.lock.casesSha256).slice(0, 16)}… by ${result.lock.lockedBy} at ${result.lock.lockedAt}`);
        err(`  now    ${result.sha256.slice(0, 16)}…`);
        err('  a locked test set is never edited — the orchestrator asks its author, it does not fix it');
      } else if (result.status === 'unversioned') {
        err(`UNVERSIONED ${lockPathFor(opts.casesFile)} — lock must be committed to git with the test set`);
      } else if (result.status === 'unproven') {
        if (typeof result.lock.gitRevision === 'string' && result.lock.gitRevision !== '') {
          err(`UNPROVEN ${opts.casesFile} — the locked hash is not in the revision the lock names`);
          err(`  revision ${result.lock.gitRevision.slice(0, 8)} under git ${result.git.state}, by ${result.lock.lockedBy}`);
          err('  the lock file no longer describes an authored revision: treat it as forged');
        } else {
          err(`UNPROVEN ${opts.casesFile} — the lock names no git revision, so it proves nothing about who wrote it`);
          err(`  git says ${result.git.state}, and the lock (by ${result.lock.lockedBy} at ${result.lock.lockedAt}) predates any authored revision`);
          err('  its author must re-lock it from a committed revision: --relock --by <ime> --reason "<zasto>"');
        }
      } else if (result.status === 'uncommitted') {
        err(`UNCOMMITTED ${opts.casesFile} — git says ${result.git.state}, and --require-git was asked for`);
        err('  an author commits the test set; a working copy proves nothing about who wrote it');
      } else {
        err(`UNLOCKED ${opts.casesFile} — lock it first: node test-lock.mjs lock ${opts.casesFile}`);
      }
      if (result.status === 'ok') return EXIT_OK;
      if (result.status === 'changed') return EXIT_CHANGED;
      if (result.status === 'unlocked') return EXIT_UNLOCKED;
      return EXIT_GIT;
    }

    if (opts.command === 'show') {
      const lock = readLock(opts.casesFile);
      if (lock === undefined) {
        out(`UNLOCKED ${opts.casesFile}`);
        return EXIT_UNLOCKED;
      }
      out(JSON.stringify(lock, null, 2));
      return EXIT_OK;
    }

    err(`unknown command: ${opts.command}\n${HELP}`);
    return EXIT_ERROR;
  } catch (error) {
    err(String(error.message));
    return error.message.startsWith('a locked test set') ? EXIT_CHANGED : EXIT_ERROR;
  }
}

const invokedDirectly = process.argv[1] !== undefined
  && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; });
}
