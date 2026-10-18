// codex-qwen-exec.mjs - the "exec" half of codex-qwen.cmd (18 Oct 2026).
// cmd.exe cannot drop the first argument of %* without re-parsing it: a re-parse runs text after "&" inside a quoted
// prompt as a command, and batch %1/shift splits unquoted arguments on "=" (breaking -c key="value"). Node receives the
// arguments already split by the Windows rules, so this inserts the Qwen overrides after "exec" and passes everything
// else through untouched to codex.exe (no shell). Settings come from the launcher's environment:
//   QWEN_WIN, QWEN_COMPACT_AT  context window and auto-compaction point (tokens)
//   QWEN_GITDIR                optional: the repo's .git, made writable for unattended runs
// Usage (from codex-qwen.cmd): node codex-qwen-exec.mjs exec [codex exec args...]
import { spawnSync } from 'node:child_process';

const argv = process.argv.slice(2);
if (argv[0]?.toLowerCase() !== 'exec') {
  process.stderr.write('codex-qwen-exec: first argument must be "exec"\n');
  process.exit(2);
}
const overrides = [];
if (/^\d+$/.test(process.env.QWEN_WIN ?? '')) overrides.push('-c', `model_context_window=${process.env.QWEN_WIN}`);
if (/^\d+$/.test(process.env.QWEN_COMPACT_AT ?? '')) overrides.push('-c', `model_auto_compact_token_limit=${process.env.QWEN_COMPACT_AT}`);
const gitDir = process.env.QWEN_GITDIR;
// a TOML literal string cannot contain a single quote; skip the override rather than build a broken one
if (gitDir && !gitDir.includes("'")) overrides.push('-c', `sandbox_workspace_write.writable_roots=['${gitDir}']`);

const args = ['exec', ...overrides, ...argv.slice(1)];
if (process.env.QWEN_EXEC_DRYRUN === '1') { process.stdout.write(JSON.stringify(args) + '\n'); process.exit(0); }
const child = spawnSync('codex', args, { stdio: 'inherit', shell: false, windowsHide: false });
if (child.error) {
  process.stderr.write(`codex-qwen-exec: could not start codex: ${child.error.code ?? child.error.message}\n`);
  process.exit(1);
}
process.exit(child.status ?? 1);
