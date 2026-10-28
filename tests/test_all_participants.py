"""
Runs the game's real bytecode for Interaction.get_participants and the all_participants shortcut side by side on
randomized interactions, Sims, objects, social groups and services, and checks that for ParticipantType.All and AllSims
they give the same answer in the same order (or the same error), read the same attributes and call the same game
functions in the same order, and keep EA's call counter and yield. Participant types use the game's real values. Then
times both.
"""

import os
import random
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]

import ea
from codebleu_loose_ends import guard
from codebleu_loose_ends.fixes import all_participants as module
from sims4.utils import flexmethod

LOG = []
DEFAULT = type('Default', (), {'__repr__': lambda self: 'DEFAULT'})()


class ParticipantType(int):
    pass


def _class_values(name, globals_):
    body = next(const for const in ea.fp.module_code('interactions').co_consts if isinstance(const, types.CodeType) and const.co_name == name)
    namespace = {}
    exec(body, dict(globals_, __name__='interactions'), namespace)
    return {key: value for key, value in namespace.items() if not key.startswith('_')}


for _name, _value in _class_values('ParticipantType', {}).items():
    setattr(ParticipantType, _name, ParticipantType(_value))
SITUATION_SIMS = list(_class_values('ParticipantTypeSituationSims', {'ParticipantType': ParticipantType}).values())
SAVED_ACTORS = list(_class_values('ParticipantTypeSavedActor', {'ParticipantType': ParticipantType}).values())
TARGET_TYPE = _class_values('TargetType', {})
PIPELINE = _class_values('PipelineProgress', {})
EVERY = (ParticipantType.All, ParticipantType.AllSims)


class Thing:
    """A game object stand-in that logs every attribute read, so EA's and the shortcut's reads can be compared in order."""

    def __init__(self, label, **attributes):
        object.__setattr__(self, '_label', label)
        self.__dict__.update(attributes)

    def __getattribute__(self, name):
        if not name.startswith('__'):
            LOG.append((object.__getattribute__(self, '_label'), name))
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        self.__dict__[name] = value

    def __repr__(self):
        return object.__getattribute__(self, '_label')


class FalsyThing(Thing):
    def __bool__(self):
        return False


class Group(Thing):
    def __iter__(self):
        return iter(self.__dict__['members'])


class LoggedClass(type):
    def __getattribute__(cls, name):
        if not name.startswith('__'):
            LOG.append(('cls', name))
        return type.__getattribute__(cls, name)


def called(label, value):
    def call(*args, **kwargs):
        LOG.append((label, 'called', args, tuple(sorted(kwargs.items()))))
        return value
    return call


class Calls:
    def __init__(self):
        self.yields = 0

    def yield_to_irq(self):
        self.yields += 1


def frozendict(first, second):
    LOG.append(('frozendict', tuple(sorted(first.items(), key=repr)), tuple(sorted(second.items(), key=repr))))
    merged = dict(first)
    merged.update(second)
    return merged


def get_carried_objects_gen(target):
    LOG.append(('get_carried_objects_gen', target))
    yield from target.carried


def game_module(calls, services, modulus=7):
    game = types.ModuleType('interactions.base.interaction')
    game.__dict__.update(
        __builtins__=__builtins__, ParticipantType=ParticipantType, ParticipantTypeSituationSims=SITUATION_SIMS, ParticipantTypeSavedActor=SAVED_ACTORS, DEFAULT=DEFAULT,
        services=services, frozendict=frozendict, get_carried_objects_gen=get_carried_objects_gen,
        Hand=Thing('Hand', LEFT='left', RIGHT='right', BACK='back'),
        TargetType=Thing('TargetType', **TARGET_TYPE), PipelineProgress=Thing('PipelineProgress', **PIPELINE),
        interaction_get_particpants_call_count=0, SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD=modulus, yield_to_irq=calls.yield_to_irq)
    return game


def ea_get_participants(game):
    code = ea.fp.find(ea.fp.module_code('interactions.base.interaction'), 'Interaction.get_participants')
    return types.FunctionType(code, game.__dict__, code.co_name, (DEFAULT, DEFAULT, DEFAULT, False, None))


def fixed(game, ea_function):
    module._game.clear()
    module._game.update(module=game, All=ParticipantType.All, AllSims=ParticipantType.AllSims, flexmethod=flexmethod)
    module.FIX.state = guard.ACTIVE
    return module._make(flexmethod(ea_function)).__wrapped_method__


class World:
    """One randomized situation: an interaction (class or running), its Sim, target, carried things, group and services."""

    def __init__(self, rng):
        self.rng = rng
        count = 0

        def label(kind):
            nonlocal count
            count += 1
            return '{}{}'.format(kind, count)

        def posture():
            roll = rng.random()
            if roll < 0.2:
                return None
            if roll < 0.3:
                return FalsyThing(label('posture'), surface_target=rng.choice([None, Thing(label('surface'))]))
            return Thing(label('posture'), surface_target=rng.choice([None, Thing(label('surface')), Thing(label('surface'))]))

        def sim():
            attributes = dict(is_sim=True, sim_id=rng.randrange(1, 6), ignore_group_socials=called(label('ignore'), rng.random() < 0.5),
                carried=[])
            if rng.random() < 0.9:
                attributes['posture_state'] = posture()
            return Thing(label('sim'), **attributes)

        def thing():
            roll = rng.random()
            if roll < 0.08:
                return Thing(label('odd'))
            attributes = dict(is_sim=False, parent=rng.choice([None, None, Thing(label('parent'), is_sim=False)]))
            return Thing(label('obj'), **attributes)

        self.sims = [sim() for _ in range(rng.randint(1, 5))]
        for carrier in self.sims:
            if carrier.__dict__.get('posture_state') is not None and rng.random() < 0.5:
                carrier.__dict__['carried'] = [(rng.choice(['left', 'right', 'back']), None, rng.choice(self.sims + [thing()])) for _ in range(rng.randint(1, 3))]
        actor = rng.choice(self.sims + [None])
        target = rng.choice([None, DEFAULT, thing(), thing()] + self.sims)
        carry = rng.choice([DEFAULT, DEFAULT, None, thing(), rng.choice(self.sims)])
        parameters = {}
        if rng.random() < 0.3:
            parameters['carry_target'] = carry if carry is not DEFAULT else None
        if rng.random() < 0.3:
            parameters['join_target_ref'] = called(label('join'), rng.choice([None, thing(), rng.choice(self.sims)]))
        if rng.random() < 0.2:
            parameters['saved_participants'] = (rng.choice(self.sims), None, None, None)
        self.parameters = parameters
        self.target_type = rng.choice([TARGET_TYPE['ACTOR'], TARGET_TYPE['TARGET'], TARGET_TYPE['GROUP'], TARGET_TYPE['TARGET'] | TARGET_TYPE['GROUP']])
        friends = set(rng.sample(range(1, 6), rng.randint(0, 2)))
        children = {friend: rng.randrange(1, 6) for friend in friends}
        friend_service = Thing('friends', is_imaginary_friend=lambda sim_id: sim_id in friends, get_child_sim=lambda sim_id: children[sim_id])
        zone = None if rng.random() < 0.03 else Thing('zone', inventory_manager=Thing('inventory'))
        self.services = Thing('services', object_manager=called('object_manager', Thing('objects')), current_zone=called('current_zone', zone),
            definition_manager=called('definition_manager', Thing('definitions')),
            get_imaginary_friend_service=called('get_imaginary_friend_service', rng.choice([None, friend_service, friend_service])))
        invalid = set(rng.sample(self.sims, rng.randint(0, 1)))
        self.cls = LoggedClass('Interaction', (), {
            'simless': rng.random() < 0.1, 'target_type': self.target_type,
            'invalid_imaginary_friend_target': classmethod(lambda cls, sim, target: LOG.append(('invalid_imaginary_friend_target', sim, target)) or target in invalid)})
        self.inst = None
        if rng.random() < 0.4:
            members = [member for member in self.sims if rng.random() < 0.6]
            registered = {member: [Thing(label('si'), pipeline_progress=rng.choice(list(PIPELINE.values())), is_finishing=rng.random() < 0.3)
                for _ in range(rng.randint(0, 2))] for member in members}
            group = None if rng.random() < 0.3 else Group(label('group'), members=members, get_sis_registered_for_sim=lambda other: registered[other])
            self.inst = Thing(label('inst'), interaction_parameters=rng.choice([{}, {'saved_participants': (None,) * 4}, dict(parameters)]),
                sim=actor, target=rng.choice([None, thing()] + self.sims), carry_target=rng.choice([None, thing()]), social_group=group,
                acquire_listeners_as_resource=rng.random() < 0.5, simless=rng.random() < 0.1, target_type=self.target_type,
                _required_sims=rng.choice([None, set(), set(rng.sample(self.sims, 1))]))
        self.actor, self.target, self.carry = actor, target, carry

    def call(self):
        """Arguments the way EA's callers pass them: positionally or by keyword, with and without each optional one."""
        rng = self.rng
        participant_type = rng.choice(EVERY)
        kwargs = dict(self.parameters)
        if rng.random() < 0.15:
            args = (participant_type, self.actor, self.target)
        else:
            args = (participant_type,)
            if rng.random() < 0.9:
                kwargs['sim'] = self.actor
            if rng.random() < 0.85:
                kwargs['target'] = self.target
            if rng.random() < 0.3:
                kwargs['carry_target'] = self.carry
        if rng.random() < 0.3:
            kwargs['listener_filtering_enabled'] = rng.random() < 0.5
        if rng.random() < 0.2:
            kwargs['target_type'] = rng.choice(list(TARGET_TYPE.values()))
        return args, kwargs


def run(function, cls, inst, args, kwargs):
    LOG.clear()
    try:
        outcome = ('result', function(cls, inst, *args, **kwargs))
    except Exception as e:
        outcome = ('raised', type(e), str(e))
    return outcome, list(LOG)


class AllParticipantsTests(unittest.TestCase):

    def setUp(self):
        module.stats.update(fast=0, checked=module._CHECKS)

    def test_real_participant_types_leave_all_and_all_sims_alone(self):
        self.assertEqual((int(ParticipantType.All), int(ParticipantType.AllSims)), (16, 32))
        self.assertGreater(len([name for name in dir(ParticipantType) if isinstance(getattr(ParticipantType, name), ParticipantType)]), 150)
        self.assertEqual(module._overlapping_types(ParticipantType), [])
        ParticipantType.Clash = ParticipantType(1 << 300 | 32)
        try:
            self.assertEqual(module._overlapping_types(ParticipantType), ['Clash'])
        finally:
            del ParticipantType.Clash

    def test_matches_the_game_on_random_worlds(self):
        rng = random.Random(11)
        outcomes = set()
        for _ in range(3000):
            world = World(rng)
            ea_calls, fixed_calls = Calls(), Calls()
            ea_game, fixed_game = game_module(ea_calls, world.services), game_module(fixed_calls, world.services)
            vanilla = ea_get_participants(ea_game)
            shortcut = fixed(fixed_game, ea_get_participants(fixed_game))
            for _ in range(4):
                args, kwargs = world.call()
                expected, expected_log = run(vanilla, world.cls, world.inst, args, kwargs)
                outcome, log = run(shortcut, world.cls, world.inst, args, kwargs)
                self.assertEqual(outcome, expected, (args, kwargs))
                self.assertEqual(log, expected_log, (args, kwargs))
                outcomes.add((expected[0], len(expected[1]) if expected[0] == 'result' else expected[1]))
            self.assertEqual(fixed_game.interaction_get_particpants_call_count, ea_game.interaction_get_particpants_call_count)
            self.assertEqual(fixed_calls.yields, ea_calls.yields)
        self.assertEqual(module.FIX.state, guard.ACTIVE)
        self.assertGreater(module.stats['fast'], 10000)
        sizes = {size for kind, size in outcomes if kind == 'result'}
        self.assertTrue({0, 1, 2, 3, 4} <= sizes, sizes)
        self.assertTrue(any(kind == 'raised' for kind, _ in outcomes), outcomes)

    def test_other_types_and_odd_calls_go_to_the_game(self):
        rng = random.Random(3)
        for _ in range(300):
            world = World(rng)
            game = game_module(Calls(), world.services)
            vanilla = ea_get_participants(game)
            shortcut = fixed(game, vanilla)
            participant_type = rng.choice(EVERY)
            other = rng.choice([ParticipantType.Actor, ParticipantType.Object, ParticipantType.TargetSim, ParticipantType.Listeners,
                ParticipantType.PickedSim, ParticipantType(int(ParticipantType.All) | int(ParticipantType.Actor)), 16, 32, None, 'All'])
            for args, kwargs in (
                    ((other,), {'sim': world.actor, 'target': world.target}),
                    ((), {'participant_type': participant_type, 'sim': world.actor}),
                    ((participant_type,), {'participant_type': participant_type}),
                    ((participant_type, world.actor), {'sim': world.actor}),
                    ((participant_type, world.actor, world.target, None, False, 1, 'extra'), {}),
                    ((), {})):
                before = module.stats['fast']
                self.assertEqual(run(shortcut, world.cls, world.inst, args, kwargs), run(vanilla, world.cls, world.inst, args, kwargs))
                self.assertEqual(module.stats['fast'], before, (args, kwargs))

    def test_first_lookups_are_checked_against_the_game(self):
        rng = random.Random(5)
        module.stats.update(fast=0, checked=0)
        for _ in range(400):
            world = World(rng)
            ea_calls, fixed_calls = Calls(), Calls()
            ea_game, fixed_game = game_module(ea_calls, world.services), game_module(fixed_calls, world.services)
            vanilla, shortcut = ea_get_participants(ea_game), fixed(fixed_game, ea_get_participants(fixed_game))
            args, kwargs = world.call()
            self.assertEqual(run(shortcut, world.cls, world.inst, args, kwargs)[0], run(vanilla, world.cls, world.inst, args, kwargs)[0])
            self.assertEqual(fixed_game.interaction_get_particpants_call_count, ea_game.interaction_get_particpants_call_count)
        self.assertEqual(module.stats['checked'], module._CHECKS)
        self.assertGreater(module.stats['fast'], 0)
        self.assertEqual(module.FIX.state, guard.ACTIVE)

    def test_a_difference_while_checking_switches_the_fix_off(self):
        module.stats.update(fast=0, checked=0)
        world = World(random.Random(8))
        game = game_module(Calls(), world.services)
        fixed(game, ea_get_participants(game))
        differs = module._make(flexmethod(lambda cls, inst, *args, **kwargs: ('the game',))).__wrapped_method__
        sim = world.sims[0]
        self.assertEqual(differs(world.cls, None, ParticipantType.All, sim=sim, target=None), ('the game',))
        self.assertEqual(module.FIX.state, guard.FAULTED)
        self.assertEqual(differs(world.cls, None, ParticipantType.All, sim=sim, target=None), ('the game',))
        self.assertEqual(module.stats, {'fast': 0, 'checked': 0})

    def test_inactive_fix_is_the_game(self):
        world = World(random.Random(9))
        game = game_module(Calls(), world.services)
        vanilla = ea_get_participants(game)
        shortcut = fixed(game, vanilla)
        module.FIX.state = guard.DISABLED
        args, kwargs = (ParticipantType.All,), {'sim': world.actor, 'target': world.target}
        self.assertEqual(run(shortcut, world.cls, world.inst, args, kwargs), run(vanilla, world.cls, world.inst, args, kwargs))
        self.assertEqual(module.stats['fast'], 0)

    def test_speed(self):
        class Plain:
            def __init__(self, **attributes):
                self.__dict__.update(attributes)

        class Interaction:
            simless = False
            target_type = TARGET_TYPE['TARGET']

            @classmethod
            def invalid_imaginary_friend_target(cls, sim, target):
                return False

        zone = Plain(inventory_manager=None)
        services = Plain(object_manager=lambda: None, current_zone=lambda: zone, definition_manager=lambda: None, get_imaginary_friend_service=lambda: None)
        sims = [Plain(is_sim=True, sim_id=i, posture_state=Plain(surface_target=None), carried=[], ignore_group_socials=lambda excluded_group: False) for i in range(5)]
        objects = [Plain(is_sim=False, parent=None) for _ in range(10)]
        calls = [((ParticipantType.All,), {'sim': sims[i % 5], 'target': (objects + sims)[i % 15]}) for i in range(60)]
        calls += [((ParticipantType.AllSims,), {'sim': sims[i % 5], 'target': sims[(i + 1) % 5]}) for i in range(20)]
        game = game_module(Calls(), services, modulus=1000)
        vanilla = ea_get_participants(game)
        shortcut = fixed(game, vanilla)

        def timed(function):
            started = time.perf_counter()
            for _ in range(500):
                for args, kwargs in calls:
                    function(Interaction, None, *args, **kwargs)
            return time.perf_counter() - started

        self.assertEqual([shortcut(Interaction, None, *a, **k) for a, k in calls], [vanilla(Interaction, None, *a, **k) for a, k in calls])
        before, after = timed(vanilla), timed(shortcut)
        lookups = 500 * len(calls)
        print('\nall participants, {} lookups: game {:.1f} ms ({:.2f} us each), fix {:.1f} ms ({:.2f} us each) ({:.3f}x)'.format(
            lookups, before * 1000, before / lookups * 1e6, after * 1000, after / lookups * 1e6, after / before))


if __name__ == '__main__':
    unittest.main()
