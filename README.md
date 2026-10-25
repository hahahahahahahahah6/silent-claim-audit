# silent-claim-audit

Offline auditing of documented terminal-output claims against Python source.

A stdlib-only static auditor: executes none of the target code, uses no network,
and never reads .env contents. Reads root README.md and docs/**/*.md.

## Usage

```sh
python3 -m pip install .
silent-claim-audit path/to/project --json
python3 -m silent_claim_audit . --verbose --ignore 'vendor/*' --fail-on HIGH
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

The directory defaults to the current directory. Repeatable --ignore globs match
relative paths and prune matching directories. --verbose adds evidence to text.
--version reports 0.1.0. JSON contains findings, verified_claims, claims, errors.
Exit 0 means pass, 2 means findings at threshold, 1 means usage/read/parse error.
Default --fail-on MEDIUM fails for either severity; HIGH still reports MEDIUM.

## Rules

| Rule | Severity | Condition |
| --- | --- | --- |
| documented-silent-claim-false | HIGH | Silent family with production evidence |
| documented-silent-claim-false-test-only | MEDIUM | Silent family with only test evidence |
| documented-verbose-claim-false | HIGH | Verbose family with evidence absent |
| documented-verbose-claim-false-test-only | MEDIUM | Verbose family with only test evidence |

Each family produces one finding with all evidence. Missing production source
produces one HIGH finding per claimed family with no-source evidence. Both
families are independent. Silent claims without any evidence and verbose claims
with production evidence are verified. Without claims, the audit passes.

## Exact phrases

Lowercase, expand n't to ' not', replace hyphens with spaces, collapse whitespace.
Fenced code is excluded; inline code counts. Negation words no, not, never,
without suppress only verbose claims. Bare silent, quiet, verbose, output words
are excluded. Examples and the complete vocabulary follow:

```text
SILENT:
silent mode
quiet mode
runs silently
runs quietly
silent by default
quiet by default
is silent
is quiet
no output
prints nothing
does not print
does not output
does not log
no stdout
no console output
suppresses output
no logging
VERBOSE:
verbose mode
verbose by default
is verbose
verbose output
verbose logging
detailed output
logs every step
prints every step
chatty output
chatty mode
Matches: doesn't print; quiet-mode; does not print
No claim: never prints; no verbose output; is not verbose; is not silent
```

## Evidence

| Kind | Calls |
| --- | --- |
| print | Builtin print, including file= |
| logging | debug/info/warning/warn/error/exception/critical/log on logging or direct getLogger assignment |
| stream | sys.stdout/sys.stderr write/writelines, including attribute chains |
| click | click.echo/secho |
| rich | Console constructor assignment receiver print; unassigned console.print |
| tqdm | tqdm(...), any receiver.tqdm(...), tqdm.write |

Per-file imports track aliases for logging, sys, click. Deduplicate by file,
line, kind. Test directories, fixtures, test_*.py, *_test.py are separate evidence;
docs and examples are excluded. Symlinked files and directories are skipped.

## Honest limitations

Existence is checked, not volume: a single print suffices. Dead code counts.
print(file=...) counts even when writing a file. Any function, class, or parameter
named print suppresses builtin evidence throughout its file, without scope
resolution. Direct assignment only tracks loggers and consoles; dynamic code
and reassignment effects are not resolved. The unassigned conventional console
name is a simplification. tqdm construction counts even if disabled at runtime,
because progress normally writes to stderr. Exact phrases miss paraphrases.
Warnings (warnings.warn/warn_explicit), string literals, comments, subprocess
shell echo/printf strings, file writes (open(...).write, Path.write_text), and
logging configuration (basicConfig/getLogger/disable/setLevel) are excluded.
There is no shell parsing or proof of successful-run reachability.

## Differentiation

| Neighbour | Scope |
| --- | --- |
| privacy-claim-audit | Network/telemetry rather than terminal writes |
| readonly-claim-audit | Filesystem writes rather than stdout/stderr |
| error-claim-audit | Failure behaviour rather than successful-run chatter |
| interactive-claim-audit | User reads rather than user writes |
| bandit/ruff | Code issues rather than documentation promises |
| logging/click/rich/tqdm docs | Output primitives rather than docs-versus-code truth |

Requires Python 3.9+. MIT licensed. Runtime dependencies: none. Build tooling:
setuptools, wheel, build. Fixtures ship in the sdist via MANIFEST.in.
