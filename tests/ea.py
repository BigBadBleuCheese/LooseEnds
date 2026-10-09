"""Builds functions from the game's own compiled code objects, with stub globals, so tests run EA's real bytecode."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))

import fp


def _cell(value):
    return (lambda: value).__closure__[0]


def function(module, qualname, globals_, klass=None, defaults=None):
    code = fp.find(fp.module_code(module), qualname)
    closure = None
    if code.co_freevars:
        assert code.co_freevars == ('__class__',), code.co_freevars
        closure = (_cell(klass),)
    globals_.setdefault('__builtins__', __builtins__)
    return types.FunctionType(code, globals_, code.co_name, defaults, closure)


def drive(generator):
    """Runs an EA generator method to completion and returns its result."""
    if not hasattr(generator, '__next__'):
        return generator
    try:
        while True:
            next(generator)
    except StopIteration as e:
        return e.value
