"""Offline documentation and terminal-output evidence auditing."""
import argparse
import ast
import fnmatch
import json
from pathlib import Path
import re

SILENT = ('silent mode', 'quiet mode', 'runs silently', 'runs quietly', 'silent by default', 'quiet by default', 'is silent', 'is quiet', 'no output', 'prints nothing', 'does not print', 'does not output', 'does not log', 'no stdout', 'no console output', 'suppresses output', 'no logging')
VERBOSE = ('verbose mode', 'verbose by default', 'is verbose', 'verbose output', 'verbose logging', 'detailed output', 'logs every step', 'prints every step', 'chatty output', 'chatty mode')
LEVELS = {'debug', 'info', 'warning', 'warn', 'error', 'exception', 'critical', 'log'}


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def claims_from_text(text, path='README.md'):
    claims = []
    fence = None
    prose = []
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            prose.append('')
        else:
            prose.append(line if fence is None else '')
    for sentence in re.split(r'(?<=[.!?])\s+|\n\s*\n', '\n'.join(prose)):
        normalized = normalize(sentence)
        for family, phrases in (('silent', SILENT), ('verbose', VERBOSE)):
            if family == 'verbose' and re.search(r'\b(no|not|never|without)\b', normalized):
                continue
            if any(re.search(r'(?<!\w)' + re.escape(p) + r'(?!\w)', normalized) for p in phrases):
                claims.append({'family': family, 'path': path, 'sentence': sentence.strip()})
    return claims


def evidence_from_text(text, path):
    tree = ast.parse(text, filename=path)
    aliases = {name: {name} for name in ('logging', 'sys', 'click')}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in aliases:
                    aliases[alias.name].add(alias.asname or alias.name)
    def named(node, names):
        return isinstance(node, ast.Name) and node.id in names
    def getlogger(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'getLogger' and named(node.func.value, aliases['logging']))
    loggers, consoles, assigned = set(), set(), set()
    shadow = any((isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == 'print') or (isinstance(n, ast.arg) and n.arg == 'print') for n in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if getlogger(node.value):
                        loggers.add(target.id)
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        if (isinstance(func, ast.Name) and func.id == 'Console') or (isinstance(func, ast.Attribute) and func.attr == 'Console'):
                            consoles.add(target.id)
    if 'console' not in assigned:
        consoles.add('console')
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func, kind = node.func, None
        if isinstance(func, ast.Name):
            if func.id == 'print' and not shadow:
                kind = 'print'
            elif func.id == 'tqdm':
                kind = 'tqdm'
        elif isinstance(func, ast.Attribute):
            receiver = func.value
            if func.attr in LEVELS and named(receiver, aliases['logging'] | loggers):
                kind = 'logging'
            elif func.attr in {'write', 'writelines'} and isinstance(receiver, ast.Attribute):
                chain = receiver
                while isinstance(chain, ast.Attribute):
                    if chain.attr in {'stdout', 'stderr'} and named(chain.value, aliases['sys']):
                        kind = 'stream'
                        break
                    chain = chain.value
            if func.attr in {'echo', 'secho'} and named(receiver, aliases['click']):
                kind = 'click'
            if func.attr == 'print' and named(receiver, consoles):
                kind = 'rich'
            if func.attr == 'tqdm' or (func.attr == 'write' and named(receiver, {'tqdm'})):
                kind = 'tqdm'
        if kind:
            found.add((path, node.lineno, kind))
    return [{'path': p, 'line': line, 'kind': k} for p, line, k in sorted(found)]


def audit(root, ignore=()):
    root = Path(root)
    claims, production, testonly, errors = [], [], [], []
    source_count = 0
    # Never follow symlinks, including directory components.
    def files(directory):
        for child in sorted(directory.iterdir()):
            if child.is_symlink():
                continue
            relative = child.relative_to(root).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in ignore):
                continue
            if child.is_dir():
                yield from files(child)
            elif child.is_file():
                yield child
    for path in files(root):
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if rel == 'README.md' or (parts[0] == 'docs' and path.suffix == '.md'):
            claims.extend(claims_from_text(path.read_text(encoding='utf-8'), rel))
        if path.suffix != '.py' or any(p in {'docs', 'examples', '.git', '.venv', 'venv', 'build', 'dist', '__pycache__'} for p in parts[:-1]):
            continue
        is_test = any(p in {'tests', 'fixtures'} for p in parts[:-1]) or path.name.startswith('test_') or path.name.endswith('_test.py')
        if not is_test:
            source_count += 1
        try:
            items = evidence_from_text(path.read_text(encoding='utf-8'), rel)
        except (SyntaxError, UnicodeError) as exc:
            errors.append({'path': rel, 'error': str(exc)})
            continue
        (testonly if is_test else production).extend(items)
    findings, verified = [], []
    for family in ('silent', 'verbose'):
        selected = [c for c in claims if c['family'] == family]
        if not selected:
            continue
        rule = 'documented-' + family + '-claim-false'
        evidence, severity = [], 'HIGH'
        if not source_count:
            evidence = [{'kind': 'no-source'}]
        elif family == 'silent' and production:
            evidence = production
        elif not production and testonly:
            rule += '-test-only'
            severity, evidence = 'MEDIUM', testonly
        elif family == 'verbose' and not production:
            evidence = selected
        else:
            verified.append({'family': family, 'claims': selected})
            continue
        findings.append({'rule': rule, 'severity': severity, 'claims': selected, 'evidence': evidence})
    return {'findings': findings, 'verified_claims': verified, 'claims': claims, 'errors': errors}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(__import__('sys').stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description='Audit documented terminal-output claims against Python source.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB')
    parser.add_argument('--fail-on', choices=['MEDIUM', 'HIGH'], default='MEDIUM')
    parser.add_argument('--version', action='version', version='0.1.0')
    args = parser.parse_args(argv)
    if not Path(args.path).is_dir():
        parser.error('path must be a directory')
    try:
        result = audit(args.path, args.ignore)
    except (OSError, UnicodeError) as exc:
        parser.error(str(exc))
    if result['errors']:
        parser.error('source could not be parsed: ' + json.dumps(result['errors']))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for finding in result['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            if args.verbose:
                for evidence in finding['evidence']:
                    print('  ' + json.dumps(evidence, sort_keys=True))
        if not result['findings']:
            print('PASS')
        if args.verbose:
            print('Verified families: ' + str(len(result['verified_claims'])))
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings']) else 0
