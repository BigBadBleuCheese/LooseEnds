"""
Installs each fix only over the exact EA code it was written against.

A fix names every EA function it wraps (hooks) and every EA function whose behavior it relies on without wrapping
(requirements), each with the fingerprint of the code it was written against. Before anything is installed, all of
them are checked. If any no longer matches, the fix stays off and the reason is recorded: either a game update changed
EA's code, or another mod replaced it. Once installed, a fix that raises from its own code switches itself off for the
rest of the session; its wrappers then just call through to the game.
"""

import sims4.log

from codebleu_loose_ends.fingerprint import fingerprint

logger = sims4.log.Logger('LooseEnds')

EA_SOURCE_PREFIX = 'T:\\InGame\\Gameplay\\Scripts\\'
PREDECESSORS = {'quick_slice': 'QuickSlice.ts4script', 'codebleu_phantom_mood_fix': 'CodeBleu-PhantomMoodFix.ts4script'}
ABSENT = object()

ACTIVE = 'active'
GAME_CHANGED = 'game changed'
OTHER_MOD = 'other mod'
FAULTED = 'faulted'
DISABLED = 'disabled by player'

fixes = []
fault_listeners = []
temporary = {}


def unpatched(value):
    """The attribute value behind any temporary diagnostic wrappers (looseends.anatomy) installed over it."""
    while temporary and id(value) in temporary:
        value = temporary[id(value)]
    return value


class Hook:
    """
    Replaces owner.name with make(current) once owner.name is verified to be the EA function with fingerprint expected
    (or, when stack_on_mods, another mod's functools.wraps wrapper around it). With expected ABSENT, owner must not
    define name itself and make(None) supplies a new attribute.
    """

    def __init__(self, owner, name, expected, make, stack_on_mods=True):
        self.owner = owner
        self.name = name
        self.expected = expected
        self.make = make
        self.stack_on_mods = stack_on_mods


class Requirement:
    """
    An EA function a fix relies on without wrapping it. Another mod's wrapper around it is acceptable unless
    stack_on_mods is False (the fix bypasses the function, so a wrapper would be skipped).
    """

    def __init__(self, owner, name, expected, stack_on_mods=True):
        self.owner = owner
        self.name = name
        self.expected = expected
        self.stack_on_mods = stack_on_mods


def _function(raw):
    """The plain function behind a class or module attribute (function, classmethod, staticmethod or flexmethod)."""
    if raw is None:
        return None
    for attribute in ('__wrapped_method__', '__func__'):
        inner = getattr(raw, attribute, None)
        if inner is not None:
            return inner
    return raw


def _code(raw):
    return getattr(_function(raw), '__code__', None)


def _is_ea(code):
    return code is not None and code.co_filename.startswith(EA_SOURCE_PREFIX)


def _mod_name(raw):
    function = _function(raw)
    module = getattr(function, '__globals__', {}).get('__name__') or getattr(function, '__module__', None) or 'an unknown mod'
    return module.split('.')[0]


def _ea_original(raw):
    """Follows functools.wraps links from another mod's replacement down to the EA function it wraps, if possible."""
    function = _function(raw)
    seen = set()
    while function is not None and id(function) not in seen:
        seen.add(id(function))
        if _is_ea(getattr(function, '__code__', None)):
            return function
        function = _function(getattr(function, '__wrapped__', None))
    return None


def _describe(owner, name):
    if isinstance(owner, type):
        return '{}.{}.{}'.format(owner.__module__, owner.__qualname__, name)
    return '{}.{}'.format(owner.__name__, name)


def evaluate(owner, name, expected, stack_on_mods=True):
    """Returns (problem state or None, detail) for owner.name against the expected fingerprint."""
    where = _describe(owner, name)
    raw = owner.__dict__.get(name)
    if expected is ABSENT:
        if raw is None:
            return None, where + ' is free'
        if _is_ea(_code(raw)):
            return GAME_CHANGED, where + ' is now defined by the game'
        return OTHER_MOD, where + ' is defined by ' + _mod_name(raw)
    if raw is None:
        return GAME_CHANGED, where + ' no longer exists'
    code = _code(raw)
    if code is not None and fingerprint(code) == expected:
        return None, where + ' matches'
    if _is_ea(code):
        return GAME_CHANGED, '{} changed ({:016x})'.format(where, fingerprint(code))
    original = _ea_original(raw)
    if original is None:
        return OTHER_MOD, '{} is replaced by {}'.format(where, _mod_name(raw))
    if fingerprint(original.__code__) != expected:
        return GAME_CHANGED, '{} changed under a wrapper from {}'.format(where, _mod_name(raw))
    if not stack_on_mods or _mod_name(raw) in PREDECESSORS:
        return OTHER_MOD, '{} is wrapped by {}'.format(where, _mod_name(raw))
    return None, '{} is wrapped by {}'.format(where, _mod_name(raw))


class Fix:
    """
    One independently switchable correction. build() imports what the fix needs and returns (hooks, requirements);
    nothing is installed unless every one of them checks out.
    """

    def __init__(self, key, title, build):
        self.key = key
        self.title = title
        self._build = build
        self.state = None
        self.detail = 'not installed yet'
        self.notes = []
        self.blocker = None
        fixes.append(self)

    @property
    def active(self):
        return self.state == ACTIVE

    def _set(self, state, detail, owner=None, name=None):
        self.state = state
        if state == OTHER_MOD:
            self.blocker = _mod_name(owner.__dict__.get(name))
        self.detail = detail
        if state == ACTIVE:
            logger.info('Loose Ends: {} is active', self.key)
        else:
            logger.warn('Loose Ends: {} is off ({}): {}', self.key, state, detail)

    def install(self):
        try:
            hooks, requirements = self._build()
        except (ImportError, AttributeError) as e:
            self._set(GAME_CHANGED, 'game code it needs is missing: {}'.format(e))
            return
        except Exception as e:
            logger.exception('Loose Ends: {} could not be prepared', self.key)
            self._set(FAULTED, 'could not be prepared: {}: {}'.format(type(e).__name__, e))
            return
        self.notes = []
        for requirement in requirements:
            problem, detail = evaluate(requirement.owner, requirement.name, requirement.expected, requirement.stack_on_mods)
            if problem is not None:
                self._set(problem, detail, requirement.owner, requirement.name)
                return
        for hook in hooks:
            problem, detail = evaluate(hook.owner, hook.name, hook.expected, hook.stack_on_mods)
            if problem is not None:
                self._set(problem, detail, hook.owner, hook.name)
                return
            if 'wrapped by' in detail:
                self.notes.append(detail)
        installed = []
        try:
            for hook in hooks:
                previous = hook.owner.__dict__.get(hook.name, ABSENT)
                setattr(hook.owner, hook.name, hook.make(None if previous is ABSENT else previous))
                installed.append((hook, previous))
        except Exception as e:
            logger.exception('Loose Ends: {} failed to install', self.key)
            for hook, previous in reversed(installed):
                if previous is ABSENT:
                    delattr(hook.owner, hook.name)
                else:
                    setattr(hook.owner, hook.name, previous)
            self._set(FAULTED, 'failed to install: {}: {}'.format(type(e).__name__, e))
            return
        self._set(ACTIVE, '; '.join(self.notes) if self.notes else 'all game code matches')

    def fault(self, exception=None):
        """Switches the fix off for the rest of the session after its own code failed."""
        if self.state != ACTIVE:
            return
        if exception is None:
            self._set(FAULTED, 'stopped after an error')
        else:
            logger.exception('Loose Ends: {} hit an error and switched itself off', self.key, exc=exception)
            self._set(FAULTED, 'stopped after {}: {}'.format(type(exception).__name__, exception))
        for listener in fault_listeners:
            try:
                listener(self)
            except Exception:
                logger.exception('Loose Ends: fault listener failed')


def set_enabled(key, enabled):
    """Switches an installed fix off or back on for this session; returns the fix, or None if no fix has that key."""
    for fix in fixes:
        if fix.key != key:
            continue
        if enabled and fix.state == DISABLED:
            fix.state = ACTIVE
        elif not enabled and fix.state == ACTIVE:
            fix.state = DISABLED
        return fix
    return None


def install_all():
    for fix in fixes:
        if fix.state is None:
            fix.install()
