import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from silent_claim_audit.audit import SILENT, VERBOSE, audit, claims_from_text, evidence_from_text, main

class Tests(unittest.TestCase):
    def tree(self, claim, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'README.md').write_text(claim)
        for name, source in files.items():
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        return root

    def test_fixtures(self):
        for name, status, rule in [('good/silent',0,None),('good/verbose',0,None),('bad/silent',2,'documented-silent-claim-false'),('bad/verbose',2,'documented-verbose-claim-false'),('testonly',2,'documented-silent-claim-false-test-only')]:
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([str(Path(__file__).parent/'fixtures'/name),'--json']),status)
                result=json.loads(out.getvalue())
                self.assertEqual(len(result['findings']),int(rule is not None))
                if rule:
                    self.assertEqual(result['findings'][0]['rule'],rule)
                else:
                    self.assertEqual(len(result['verified_claims']),1)

    def test_threshold(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(Path(__file__).parent/'fixtures/testonly'),'--fail-on','HIGH']),0)
        self.assertIn('MEDIUM',out.getvalue())

    def test_ignore(self):
        root=self.tree('quiet mode',{'main.py':'x=1','noise.py':'print(1)'})
        self.assertFalse(audit(root,['noise.py'])['findings'])

    def test_both_no_source(self):
        result=audit(self.tree('quiet mode. Verbose mode.',{}))
        self.assertEqual(len(result['findings']),2)
        self.assertTrue(all(f['evidence']==[{'kind':'no-source'}] for f in result['findings']))

    def test_verbose_testonly(self):
        result=audit(self.tree('verbose mode',{'main.py':'x=1','tests/a.py':'print(1)'}))
        self.assertEqual(result['findings'][0]['rule'],'documented-verbose-claim-false-test-only')

    def test_no_claim(self):
        self.assertFalse(audit(self.tree('Hello',{'main.py':'print(1)'}))['findings'])

    def test_all_evidence(self):
        result=audit(self.tree('quiet mode',{'main.py':'print(1)\nprint(2)'}))
        self.assertEqual(len(result['findings']),1)
        self.assertEqual(len(result['findings'][0]['evidence']),2)

    def test_env(self):
        root=self.tree('quiet mode',{'main.py':'x=1','.env':'MARKER_9182'})
        original=Path.open
        def guard(path,*args,**kwargs):
            self.assertNotEqual(path.name,'.env')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guard), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(root),'--json']),0)
        self.assertNotIn('MARKER_9182',out.getvalue())

    def test_self(self):
        self.assertEqual(audit(Path(__file__).resolve().parents[1])['claims'],[])

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
            main(['--version'])
        self.assertEqual(cm.exception.code,0)
        self.assertEqual(out.getvalue().strip(),'0.1.0')

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(['--unknown'])
        self.assertEqual(cm.exception.code,1)

    def test_symlink(self):
        root=self.tree('quiet mode',{'main.py':'x=1','examples/a.py':'print(1)'})
        (root/'link.py').symlink_to(root/'examples/a.py')
        self.assertFalse(audit(root)['findings'])

    def test_docs(self):
        root=self.tree('Hello',{'main.py':'x=1','docs/sub/a.md':'quiet mode','OTHER.md':'verbose mode'})
        self.assertEqual([c['family'] for c in audit(root)['claims']],['silent'])

def claim_test(text,family):
    def test(self):
        self.assertEqual({c['family'] for c in claims_from_text(text)},{family} if family else set())
    return test

for i,(text,family) in enumerate([(p,'silent') for p in SILENT]+[(p,'verbose') for p in VERBOSE]+[("doesn't print",'silent'),('quiet-mode','silent'),('`quiet mode`','silent'),('```\nquiet mode\n```',None),('~~~\nverbose mode\n~~~',None),('no verbose output',None),('never prints',None),('is not verbose',None),('is not silent',None),('silent',None),('verbose',None),('output',None),('quiet   mode','silent'),('quiet\nmode','silent')]):
    setattr(Tests,'test_claim_%02d'%i,claim_test(text,family))

def evidence_test(source,kind):
    def test(self):
        self.assertEqual([e['kind'] for e in evidence_from_text(source,'main.py')],[kind] if kind else [])
    return test

for i,(source,kind) in enumerate([
('print(1)','print'),('print(1,file=x)','print'),('def print(x): pass\nprint(1)',None),('def f(print): print(1)',None),('class print: pass\nprint(1)',None),
('logging.info(1)','logging'),('import logging as lg\nlg.warning(1)','logging'),('logging.basicConfig()',None),('logger=logging.getLogger(__name__)\nlogger.info(1)','logging'),('import logging as lg\na=lg.getLogger()\na.log(1)','logging'),
('sys.stdout.write(1)','stream'),('sys.stderr.writelines([])','stream'),('import sys as s\ns.stdout.write(1)','stream'),('open("x").write(1)',None),('Path("x").write_text(1)',None),
('click.echo(1)','click'),('import click as c\nc.secho(1)','click'),('console=Console()\nconsole.print(1)','rich'),('console.print(1)','rich'),('console=other\nconsole.print(1)',None),
('tqdm([])','tqdm'),('tqdm.write(1)','tqdm'),('module.tqdm([])','tqdm'),('warnings.warn(1)',None),('warnings.warn_explicit(1)',None),('"print(1)"',None),('# print(1)',None),('subprocess.run("echo hi")',None),('if False:\n print(1)','print'),('thing.info(1)',None),('logging.disable()',None),('logging.setLevel(1)',None)]):
    setattr(Tests,'test_evidence_%02d'%i,evidence_test(source,kind))
