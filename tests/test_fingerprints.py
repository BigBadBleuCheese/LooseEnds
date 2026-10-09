import ast
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', 'tools')]

import fp

FIXES = os.path.join(HERE, '..', 'src', 'codebleu_loose_ends', 'fixes')


def expectations():
    for path in sorted(glob.glob(os.path.join(FIXES, '*.py'))):
        tree = ast.parse(open(path, encoding='utf-8').read())
        for function in [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('_build')]:
            names = {}
            for node in ast.walk(function):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        names[alias.asname or alias.name] = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        names[alias.asname or alias.name] = None
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', None) in ('Hook', 'Requirement'):
                    owner, name, expected = node.args[:3]
                    if not isinstance(expected, ast.Num):
                        continue
                    module = names[owner.id]
                    qualname = name.s if module is None else '{}.{}'.format(owner.id, name.s)
                    yield os.path.basename(path), module or owner.id, qualname, expected.n


class FingerprintTests(unittest.TestCase):

    def test_every_expected_fingerprint_matches_the_game(self):
        checked = 0
        for file_name, module, qualname, expected in expectations():
            with self.subTest(file=file_name, function=qualname):
                try:
                    actual, _ = fp.fp(module, qualname)
                except KeyError:
                    owner, name = qualname.split('.')
                    actual, _ = fp.fp(module + '.' + owner, name)
                self.assertEqual('{:016x}'.format(actual), '{:016x}'.format(expected))
                checked += 1
        print('checked', checked, 'fingerprints')
        self.assertGreater(checked, 25)


if __name__ == '__main__':
    unittest.main()
