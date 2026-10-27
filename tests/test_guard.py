import functools
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src'), os.path.join(HERE, '..', 'tools')]

import fp
from codebleu_loose_ends import guard
from sims4.utils import flexmethod


def ea_function(module, qualname):
    code = fp.find(fp.module_code(module), qualname)
    return types.FunctionType(code, {})


GET_ORDERED_TYPES = ('sims4.tuning.instance_manager', 'InstanceManager.get_ordered_types', 0xf8538d2118da745c)
HAS_VALID_CHOICE = ('interactions.base.picker_interaction', 'AutonomousSimPickerSuperInteraction.has_valid_choice', 0x9d0f21532ba41c3e)
VALID_CHOICES = ('interactions.base.picker_interaction', 'SimPickerMixin._get_valid_sim_choices_gen', 0x3c3eeabebaddf896)


def mod_wrapper(original, module='some_mod.injector', keep_link=True):
    namespace = {'__name__': module, 'original': original}
    exec('def wrapper(*args, **kwargs):\n    return original(*args, **kwargs)\n', namespace)
    wrapper = namespace['wrapper']
    if keep_link:
        functools.update_wrapper(wrapper, original)
    return wrapper


def fresh_fix(build):
    guard.fixes.clear()
    return guard.Fix('test', 'Test fix', build)


class GuardTests(unittest.TestCase):

    def setUp(self):
        self.owner = type('Owner', (), {'get_ordered_types': ea_function(*GET_ORDERED_TYPES[:2])})

    def hook(self, expected=GET_ORDERED_TYPES[2], stack_on_mods=True):
        return guard.Hook(self.owner, 'get_ordered_types', expected, lambda original: mod_wrapper(original, 'codebleu_loose_ends.x'), stack_on_mods)

    def test_pristine_installs(self):
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual(fix.state, guard.ACTIVE)
        self.assertEqual(self.owner.__dict__['get_ordered_types'].__globals__['__name__'], 'codebleu_loose_ends.x')

    def test_changed_by_game(self):
        fix = fresh_fix(lambda: ([self.hook(expected=0x1234)], []))
        fix.install()
        self.assertEqual(fix.state, guard.GAME_CHANGED)
        self.assertNotEqual(self.owner.__dict__['get_ordered_types'].__globals__.get('__name__'), 'codebleu_loose_ends.x')

    def test_stacks_on_wrapping_mod(self):
        self.owner.get_ordered_types = mod_wrapper(self.owner.get_ordered_types)
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual(fix.state, guard.ACTIVE)
        self.assertIn('wrapped by some_mod', fix.detail)

    def test_refuses_wrapping_mod_when_strict(self):
        self.owner.get_ordered_types = mod_wrapper(self.owner.get_ordered_types)
        fix = fresh_fix(lambda: ([self.hook(stack_on_mods=False)], []))
        fix.install()
        self.assertEqual(fix.state, guard.OTHER_MOD)
        self.assertEqual(fix.blocker, 'some_mod')

    def test_predecessor_is_never_stacked_on(self):
        self.owner.get_ordered_types = mod_wrapper(self.owner.get_ordered_types, 'codebleu_phantom_mood_fix')
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual((fix.state, fix.blocker), (guard.OTHER_MOD, 'codebleu_phantom_mood_fix'))

    def test_unverifiable_replacement(self):
        self.owner.get_ordered_types = mod_wrapper(self.owner.get_ordered_types, keep_link=False)
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual(fix.state, guard.OTHER_MOD)

    def test_game_changed_under_wrapper(self):
        changed = ea_function(*HAS_VALID_CHOICE[:2])
        self.owner.get_ordered_types = mod_wrapper(changed)
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual(fix.state, guard.GAME_CHANGED)

    def test_missing_attribute(self):
        del self.owner.get_ordered_types
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertEqual(fix.state, guard.GAME_CHANGED)

    def test_missing_module(self):
        def build():
            import no_such_ea_module
        fix = fresh_fix(build)
        fix.install()
        self.assertEqual(fix.state, guard.GAME_CHANGED)

    def test_classmethod_and_flexmethod_fingerprints(self):
        owner = type('Picker', (), {'has_valid_choice': classmethod(ea_function(*HAS_VALID_CHOICE[:2])), '_get_valid_sim_choices_gen': flexmethod(ea_function(*VALID_CHOICES[:2]))})
        self.assertIsNone(guard.evaluate(owner, 'has_valid_choice', HAS_VALID_CHOICE[2])[0])
        self.assertIsNone(guard.evaluate(owner, '_get_valid_sim_choices_gen', VALID_CHOICES[2])[0])

    def test_requirement_failure_installs_nothing(self):
        other = type('Other', (), {'start': ea_function(*HAS_VALID_CHOICE[:2])})
        fix = fresh_fix(lambda: ([self.hook()], [guard.Requirement(other, 'start', 0x99)]))
        fix.install()
        self.assertEqual(fix.state, guard.GAME_CHANGED)
        self.assertNotEqual(self.owner.__dict__['get_ordered_types'].__globals__.get('__name__'), 'codebleu_loose_ends.x')

    def test_absent_hook(self):
        base = type('Base', (), {'_destroy': lambda self: 'base'})
        owner = type('Owner', (base,), {})
        fix = fresh_fix(lambda: ([guard.Hook(owner, '_destroy', guard.ABSENT, lambda _: lambda self: 'added')], []))
        fix.install()
        self.assertEqual(fix.state, guard.ACTIVE)
        self.assertEqual(owner()._destroy(), 'added')
        defined = type('Defined', (base,), {'_destroy': mod_wrapper(lambda self: 1)})
        fix = fresh_fix(lambda: ([guard.Hook(defined, '_destroy', guard.ABSENT, lambda _: None)], []))
        fix.install()
        self.assertEqual(fix.state, guard.OTHER_MOD)

    def test_install_failure_rolls_back(self):
        original = self.owner.__dict__['get_ordered_types']

        def boom(_):
            raise RuntimeError('nope')
        second = type('Second', (), {})
        fix = fresh_fix(lambda: ([self.hook(), guard.Hook(second, 'x', guard.ABSENT, lambda _: 1), guard.Hook(second, 'y', guard.ABSENT, boom)], []))
        fix.install()
        self.assertEqual(fix.state, guard.FAULTED)
        self.assertIs(self.owner.__dict__['get_ordered_types'], original)
        self.assertNotIn('x', second.__dict__)

    def test_player_can_disable_and_reenable(self):
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        self.assertIs(guard.set_enabled('test', False), fix)
        self.assertEqual(fix.state, guard.DISABLED)
        self.assertFalse(fix.active)
        guard.set_enabled('test', True)
        self.assertTrue(fix.active)
        self.assertIsNone(guard.set_enabled('nope', True))
        fix.state = guard.GAME_CHANGED
        guard.set_enabled('test', True)
        self.assertEqual(fix.state, guard.GAME_CHANGED, 'enable never turns on a fix that failed its checks')

    def test_restoring_fix_puts_the_game_back_while_disabled(self):
        original = self.owner.__dict__['get_ordered_types']
        guard.fixes.clear()
        fix = guard.Fix('test', 'Test fix', lambda: ([self.hook()], []), restore_when_disabled=True)
        fix.install()
        wrapper = self.owner.__dict__['get_ordered_types']
        self.assertIsNot(wrapper, original)
        guard.set_enabled('test', False)
        self.assertEqual(fix.state, guard.DISABLED)
        self.assertIs(self.owner.__dict__['get_ordered_types'], original)
        guard.set_enabled('test', True)
        self.assertEqual(fix.state, guard.ACTIVE)
        self.assertIs(self.owner.__dict__['get_ordered_types'], wrapper)

    def test_restoring_fix_leaves_later_mod_wrappers_alone(self):
        guard.fixes.clear()
        fix = guard.Fix('test', 'Test fix', lambda: ([self.hook()], []), restore_when_disabled=True)
        fix.install()
        later = mod_wrapper(self.owner.__dict__['get_ordered_types'], 'later_mod')
        self.owner.get_ordered_types = later
        guard.set_enabled('test', False)
        self.assertIs(self.owner.__dict__['get_ordered_types'], later)
        guard.set_enabled('test', True)
        self.assertIs(self.owner.__dict__['get_ordered_types'], later)
        self.assertEqual(fix.state, guard.ACTIVE)

    def test_restoring_fix_removes_and_returns_added_attributes(self):
        base = type('Base', (), {'_destroy': lambda self: 'base'})
        owner = type('Owner', (base,), {})
        guard.fixes.clear()
        fix = guard.Fix('test', 'Test fix', lambda: ([guard.Hook(owner, '_destroy', guard.ABSENT, lambda _: lambda self: 'added')], []), restore_when_disabled=True)
        fix.install()
        guard.set_enabled('test', False)
        self.assertNotIn('_destroy', owner.__dict__)
        self.assertEqual(owner()._destroy(), 'base')
        guard.set_enabled('test', True)
        self.assertEqual(owner()._destroy(), 'added')

    def test_other_fixes_keep_their_wrappers_while_disabled(self):
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        wrapper = self.owner.__dict__['get_ordered_types']
        guard.set_enabled('test', False)
        self.assertIs(self.owner.__dict__['get_ordered_types'], wrapper)

    def test_fault_switches_off_and_notifies(self):
        heard = []
        guard.fault_listeners[:] = [heard.append]
        fix = fresh_fix(lambda: ([self.hook()], []))
        fix.install()
        fix.fault(ValueError('bad'))
        self.assertEqual(fix.state, guard.FAULTED)
        self.assertFalse(fix.active)
        self.assertEqual(heard, [fix])
        fix.fault(ValueError('again'))
        self.assertEqual(heard, [fix])
        guard.fault_listeners.clear()


if __name__ == '__main__':
    unittest.main()
