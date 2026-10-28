"""
looseends.count_participants wraps Interaction.get_participants for a while during play, so the wrapper must give the
game exactly what EA's method gives (results, errors, missing arguments), must not hide the method from the fixes that
check it is EA's, and must finish and write its counts even when the console that started it is gone after travel.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]


def _module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


class ParticipantType(int):
    pass


for _name, _value in (('Actor', 1), ('Object', 2), ('TargetSim', 4), ('All', 16), ('PickedSim', 1 << 24)):
    setattr(ParticipantType, _name, ParticipantType(_value))

from sims4.utils import flexmethod


def _ea_get_participants(cls, inst, participant_type, sim=None, target=None, **interaction_parameters):
    if participant_type == 99:
        raise ValueError('EA raised')
    if participant_type == ParticipantType.All:
        return tuple(sorted(cls.get_participants(ParticipantType.Actor, sim=sim) + cls.get_participants(ParticipantType.Object, target=target)))
    if participant_type == ParticipantType.Actor:
        return (sim,) if sim is not None else ()
    if participant_type == ParticipantType.Object:
        return (target,) if target is not None else ()
    return (participant_type, sim, target, tuple(sorted(interaction_parameters.items())))


class Interaction:
    get_participants = flexmethod(_ea_get_participants)


class CraftingInteraction(Interaction):
    @flexmethod
    def get_participants(cls, inst, participant_type, **kwargs):
        return ('crafting',) + super(CraftingInteraction, inst if inst is not None else cls).get_participants(participant_type, **kwargs)


_module('interactions').ParticipantType = ParticipantType
_module('interactions.base')
_module('interactions.base.interaction').Interaction = Interaction

import services
from codebleu_loose_ends import guard, participant_count
from sims4 import commands as sims4_commands


class Clients:
    raises = None
    client = None

    def get_first_client(self):
        if Clients.raises is not None:
            raise Clients.raises
        return Clients.client


services.client_manager = Clients
services.current_zone_id = lambda: 7


def gone(text):
    raise KeyError('Failed to find ZoneSession')


class CountTests(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.original = Interaction.__dict__['get_participants']
        self.addCleanup(setattr, Interaction, 'get_participants', self.original)
        participant_count._state.clear()
        participant_count._state['counting'] = False
        sims4_commands.CheatOutput.lines.clear()
        Clients.raises = None
        Clients.client = types.SimpleNamespace(id=3)
        self.lines = []

    def start(self, seconds=60):
        participant_count.start(seconds, self.lines.append, lambda: self.folder, guard.logger)

    def reports(self):
        return [name for name in os.listdir(self.folder) if name.startswith('LooseEnds_participants_')]

    def report(self):
        names = self.reports()
        self.assertEqual(len(names), 1)
        with open(os.path.join(self.folder, names[0]), encoding='utf-8') as f:
            return f.read()

    def outcome(self, call, *args, **kwargs):
        try:
            return 'result', call(*args, **kwargs)
        except Exception as e:
            return 'raised', type(e), str(e)

    def test_answers_are_exactly_eas(self):
        cases = [
            ((ParticipantType.Actor,), {'sim': 's'}),
            ((ParticipantType.All,), {'sim': 's', 'target': 't'}),
            ((), {'participant_type': ParticipantType.PickedSim, 'sim': 's', 'picked_item_ids': (5,)}),
            ((ParticipantType.PickedSim, 's', 't'), {'saved_participants': 1}),
            ((), {}),
            ((99,), {}),
            (('not a type',), {}),
            ((ParticipantType.Object,), {'target': 't', 'unexpected': 1}),
        ]
        expected = [(self.outcome(Interaction.get_participants, *args, **kwargs), self.outcome(CraftingInteraction.get_participants, *args, **kwargs),
            self.outcome(Interaction().get_participants, *args, **kwargs)) for args, kwargs in cases]
        self.start()
        self.assertIsNot(Interaction.__dict__['get_participants'], self.original)
        self.assertIs(guard.unpatched(Interaction.__dict__['get_participants']), self.original)
        counted = [(self.outcome(Interaction.get_participants, *args, **kwargs), self.outcome(CraftingInteraction.get_participants, *args, **kwargs),
            self.outcome(Interaction().get_participants, *args, **kwargs)) for args, kwargs in cases]
        self.assertEqual(counted, expected)
        self.assertTrue(participant_count.stop())
        self.assertIs(Interaction.__dict__['get_participants'], self.original)
        self.assertEqual(guard.temporary, {})
        self.assertFalse(participant_count.stop())

    def test_counts_by_type_and_caller_with_nested_calls_separate(self):
        self.start()

        def autonomy_test():
            return Interaction.get_participants(ParticipantType.All, sim='s', target='t')

        for _ in range(5):
            autonomy_test()
        CraftingInteraction.get_participants(ParticipantType.PickedSim)
        participant_count.stop()
        calls = participant_count._state['calls']
        by_type = {}
        for (value, code), count in calls.items():
            by_type[(value, code.co_name)] = by_type.get((value, code.co_name), 0) + count
        self.assertEqual(by_type, {(16, 'autonomy_test'): 5, (1, '_ea_get_participants'): 5, (2, '_ea_get_participants'): 5,
            (1 << 24, 'get_participants'): 1})
        text = self.report()
        self.assertIn('Calls to Interaction.get_participants: 16', text)
        self.assertIn('chain  All', text)
        self.assertIn('early  Actor', text)
        self.assertIn('PickedSim  <-  ', text)
        self.assertIn('autonomy_test', text)
        self.assertIn('Started at', text)
        self.assertIn('ended on zone 7', text)
        self.assertTrue(self.lines[-1].startswith('Loose Ends: counted 16 participant lookups'))

    def test_time_up_finishes_after_the_outermost_call_only(self):
        self.start()
        participant_count._state['deadline'] = 0.0
        self.assertEqual(Interaction.get_participants(ParticipantType.All, sim='s', target='t'), ('s', 't'))
        self.assertIs(Interaction.__dict__['get_participants'], self.original)
        self.assertEqual(sum(participant_count._state['calls'].values()), 3)
        self.assertEqual(len(self.reports()), 1)
        self.assertEqual(Interaction.get_participants(ParticipantType.Actor, sim='s'), ('s',))
        self.assertEqual(len(self.reports()), 1)

    def test_console_gone_after_travel(self):
        self.start()
        participant_count._state.update(output=gone, deadline=0.0)
        self.assertEqual(Interaction.get_participants(ParticipantType.Actor, sim='s'), ('s',))
        self.assertEqual(len(self.reports()), 1)
        self.assertTrue(sims4_commands.CheatOutput.lines[-1].startswith('Loose Ends: counted 1 participant lookups'))
        self.assertIs(Interaction.__dict__['get_participants'], self.original)

    def test_no_console_and_no_client_is_quiet(self):
        for raises, client in ((KeyError('Failed to find ZoneSession'), None), (None, None)):
            self.setUp()
            Clients.raises, Clients.client = raises, client
            self.start()
            participant_count._state.update(output=gone, deadline=0.0)
            self.assertEqual(Interaction.get_participants(ParticipantType.Actor, sim='s'), ('s',))
            self.assertEqual(len(self.reports()), 1)
            self.assertEqual(sims4_commands.CheatOutput.lines, [])
            self.assertIs(Interaction.__dict__['get_participants'], self.original)

    def test_failed_write_still_restores_and_never_raises_into_the_game(self):
        participant_count.start(60, self.lines.append, lambda: os.path.join(self.folder, 'missing', 'folder'), guard.logger)
        participant_count._state['deadline'] = 0.0
        self.assertEqual(Interaction.get_participants(ParticipantType.Actor, sim='s'), ('s',))
        self.assertIs(Interaction.__dict__['get_participants'], self.original)
        self.assertEqual(guard.temporary, {})
        self.assertIn('failed', self.lines[-1])

    def test_another_mod_replacing_it_is_left_alone(self):
        self.start()
        counter = Interaction.__dict__['get_participants']
        inner = counter.__wrapped_method__

        def other_mod(cls, inst, *args, **kwargs):
            return ('other mod',) + inner(cls, inst, *args, **kwargs)

        Interaction.get_participants = flexmethod(other_mod)
        replaced = Interaction.__dict__['get_participants']
        self.assertTrue(participant_count.stop())
        self.assertIs(Interaction.__dict__['get_participants'], replaced)
        self.assertIn('Another mod replaced', self.report())
        before = sum(participant_count._state['calls'].values())
        self.assertEqual(Interaction.get_participants(ParticipantType.Actor, sim='s'), ('other mod', 's'))
        self.assertEqual(sum(participant_count._state['calls'].values()), before)

    def test_already_counting_and_unwrappable_method(self):
        self.start()
        self.start()
        self.assertIn('already counting', self.lines[-1])
        participant_count.stop()
        Interaction.get_participants = classmethod(lambda cls, *args: ())
        self.start()
        self.assertIn('nothing was changed', self.lines[-1])
        self.assertFalse(participant_count._state['counting'])


if __name__ == '__main__':
    unittest.main()
