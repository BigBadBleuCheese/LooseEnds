"""
Prints the free variables and every global/attribute name a game function (and its nested code) refers to.

Usage: python names.py module:Qualified.name [module:Qualified.name ...]
Useful for deciding which globals a test has to stub when it runs the game's own bytecode.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fp


def walk(code):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            yield from walk(constant)


if __name__ == '__main__':
    for argument in sys.argv[1:]:
        module, qualified_name = argument.split(':')
        code = fp.find(fp.module_code(module), qualified_name)
        names = set()
        for nested in walk(code):
            names |= set(nested.co_names)
        print(qualified_name, 'freevars', code.co_freevars, 'names', sorted(names))
