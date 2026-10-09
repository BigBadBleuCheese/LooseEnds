"""Stable fingerprints of code objects, used to confirm a function is exactly the one a patch was written against."""

import types


def fingerprint(code):
    """64-bit FNV-1a over a code object's bytecode, names, variables and constants, independent of hash randomization."""
    value = 0xcbf29ce484222325
    for part in _parts(code):
        for byte in part:
            value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


def _parts(code):
    yield code.co_code
    yield '\0'.join(code.co_names).encode('utf-8')
    yield '\0'.join(code.co_varnames).encode('utf-8')
    for const in code.co_consts:
        yield b'\1'
        yield from _const_parts(const)


def _const_parts(const):
    if isinstance(const, types.CodeType):
        yield from _parts(const)
    elif isinstance(const, tuple):
        yield b'('
        for item in const:
            yield from _const_parts(item)
            yield b','
        yield b')'
    elif isinstance(const, frozenset):
        yield b'{'
        for item in sorted(repr(item) for item in const):
            yield item.encode('utf-8')
            yield b','
        yield b'}'
    else:
        yield repr(const).encode('utf-8')
