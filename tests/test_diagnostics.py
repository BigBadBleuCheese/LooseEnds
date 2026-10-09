"""
The picker timer and profiler wrap game code on the click path, so they must never raise into it. In the game an
immediate picker interaction runs inside Client.select_interaction (choice_menu.select executes it synchronously),
which is the order that caused a KeyError in the first version of the timer.
"""

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]


def _module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


class PickerSuperInteractionMixin:
    def _show_picker_dialog(self, owner, **kwargs):
        return 'shown'


class Client:
    picker = None

    def select_interaction(self, choice_id, revision):
        if Client.picker is not None:
            return Client.picker._show_picker_dialog('crafter')
        return 'pushed'


_module('interactions')
_module('interactions.base')
_module('interactions.base.picker_interaction').PickerSuperInteractionMixin = PickerSuperInteractionMixin
_module('server')
_module('server.client').Client = Client

from codebleu_loose_ends import commands
from sims4 import commands as sims4_commands


class TimerTests(unittest.TestCase):

    def setUp(self):
        sims4_commands.CheatOutput.lines.clear()
        Client.picker = None

    def arm(self):
        commands.loose_ends_time_next_picker()

    def last(self):
        return sims4_commands.CheatOutput.lines[-1]

    def test_picker_inside_the_click(self):
        self.arm()
        Client.picker = PickerSuperInteractionMixin()
        self.assertEqual(Client().select_interaction(1, 2), 'shown')
        self.assertIn('picker started', self.last())
        self.assertIn('click fully handled', self.last())
        self.assertFalse(commands._next_picker['timing'])

    def test_picker_after_the_click(self):
        self.arm()
        self.assertEqual(Client().select_interaction(1, 2), 'pushed')
        self.assertEqual(PickerSuperInteractionMixin()._show_picker_dialog('crafter'), 'shown')
        self.assertIn('picker started', self.last())
        self.assertFalse(commands._next_picker['timing'])

    def test_picker_without_a_click(self):
        self.arm()
        self.assertEqual(PickerSuperInteractionMixin()._show_picker_dialog('crafter'), 'shown')
        self.assertIn('no pie menu click was seen first', self.last())

    def test_disarmed_wrappers_are_pass_through(self):
        self.arm()
        PickerSuperInteractionMixin()._show_picker_dialog('crafter')
        count = len(sims4_commands.CheatOutput.lines)
        Client.picker = PickerSuperInteractionMixin()
        self.assertEqual(Client().select_interaction(1, 2), 'shown')
        self.assertEqual(len(sims4_commands.CheatOutput.lines), count)

    def test_reporting_failure_never_reaches_the_game(self):
        self.arm()
        original = sims4_commands.CheatOutput.__call__

        def broken(self, text):
            raise RuntimeError('console gone')
        sims4_commands.CheatOutput.__call__ = broken
        try:
            Client.picker = PickerSuperInteractionMixin()
            self.assertEqual(Client().select_interaction(1, 2), 'shown')
        finally:
            sims4_commands.CheatOutput.__call__ = original


if __name__ == '__main__':
    unittest.main()
