"""Runs the game's real bytecode for each patched path against stubs, with and without the Loose Ends fix installed."""

import collections
import functools
import os
import random
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]

import ea
from codebleu_loose_ends import guard
from sims4.utils import flexmethod

PICKER = 'interactions.base.picker_interaction'


class TestResult:
    def __init__(self, ok, reason=''):
        self.ok, self.reason = ok, reason

    def __bool__(self):
        return self.ok


TestResult.TRUE = TestResult(True)


class ParticipantType:
    Actor = 1
    TargetSim = 2
    PickedSim = 16777216


def activate(fix):
    fix.state = guard.ACTIVE


class Sim:
    def __init__(self, name, household=1, asleep=False):
        self.name, self.household_id, self.asleep = name, household, asleep
        self.sim_id = self.id = id(self)
        self.sim_info = self
        self.queue = Queue()
        self.lockouts = set()
        self.can_instantiate_sim = True
        self.buffs = set()

    def __repr__(self):
        return self.name

    def get_sim_instance(self, **_):
        return self

    def is_instanced(self, **_):
        return True

    def has_lockout(self, obj):
        return obj in self.lockouts

    def add_lockout(self, obj, minutes):
        if obj is not self:
            self.lockouts.add(obj)

    def test_super_affordance(self, affordance, target, context, **kwargs):
        return affordance.test(self, target)


class Queue(list):
    def find_pushed_interaction_by_id(self, group_id):
        return types.SimpleNamespace(id=len(self)) if self else None

    def find_continuation_by_id(self, _):
        return None


class Affordance:
    is_super = True
    involves_carry = False

    def __init__(self, name, test):
        self.name, self.test = name, test


class Continuation:
    def __init__(self, affordance, target=ParticipantType.PickedSim):
        self.affordance = affordance
        self.si_affordance_override = None
        self.actor = ParticipantType.Actor
        self.target = target


class Context:
    def __init__(self, sim):
        self.sim, self.carry_target = sim, None

    def clone_for_sim(self, sim, **_):
        return Context(sim)


class FilterResult:
    def __init__(self, sim_info):
        self.sim_info, self.score = sim_info, 1.0


class AOP:
    def __init__(self, affordance, actor, target):
        self.affordance, self.actor, self.target = affordance, actor, target

    def test_and_execute(self, context):
        result = self.affordance.test(self.actor, self.target)
        if result:
            self.actor.queue.append((self.affordance.name, self.target))
        return result


def build_picker(world, continuations, filter_test=lambda requester, candidate: True):
    """A picker class hierarchy shaped like EA's, with EA's real methods from the game's bytecode."""
    services = types.SimpleNamespace(
        sim_info_manager=lambda: types.SimpleNamespace(get_all=lambda: list(world), get=lambda sim_id: next((s for s in world if s.sim_id == sim_id), None)),
        sim_filter_service=lambda: types.SimpleNamespace(submit_filter=lambda sim_filter, callback, sim_constraints=(), requesting_sim_info=None, **_: [
            FilterResult(s) for s in world if s.sim_id in sim_constraints and filter_test(requesting_sim_info, s)]),
        relationship_service=lambda: types.SimpleNamespace(is_hidden=lambda a, b: False))
    pick = lambda weights: random.choice(weights)[1] if weights else None
    globals_ = dict(services=services, functools=functools, event_testing=types.SimpleNamespace(results=types.SimpleNamespace(TestResult=TestResult)),
        singletons=types.SimpleNamespace(EMPTY_SET=frozenset()), sims4=types.SimpleNamespace(random=types.SimpleNamespace(pop_weighted=pick)),
        QueueInsertStrategy=types.SimpleNamespace(LAST='LAST', NEXT='NEXT'), SimPickerLinkContinuation=types.SimpleNamespace(NEITHER=0, ACTOR=1, TARGET=2, PICKED=3, ALL=4),
        ParticipantType=ParticipantType, collections=collections, DEFAULT=object(), sims=types.SimpleNamespace(sim_info=types.SimpleNamespace(SimInfo=type('SimInfo', (), {}))))

    class Mixin:
        sim_filter = object()
        sim_filter_household_override = None
        include_actor_sim = False
        include_target_sim = False
        include_uninstantiated_sims = False
        include_instantiated_sims = True
        include_rabbithole_sims = False
        include_missing_pets = False
        radius = None
        sim_tests = None
        create_sim_if_no_valid_choices = False
        get_sim_filter_gsi_name = None

        @classmethod
        def _get_requesting_sim_info_for_picker(cls, context, **_):
            return context.sim.sim_info

        @classmethod
        def _get_actor_for_picker(cls, context, **_):
            return context.sim.sim_info

    Mixin.sim_filter = types.SimpleNamespace(get_pre_filtered_sim_infos=lambda requesting_sim_info: None)
    Mixin._get_valid_sim_choices_gen = flexmethod(ea.function(PICKER, 'SimPickerMixin._get_valid_sim_choices_gen', globals_, defaults=(None, 1, set(), set())))
    Mixin._push_continuation = ea.function(PICKER, 'SimPickerMixin._push_continuation', globals_)
    Mixin._push_continuations = ea.function(PICKER, 'SimPickerMixin._push_continuations', globals_, defaults=(None,))

    class Base:
        @classmethod
        def _test(cls, target, context, **_):
            return TestResult.TRUE

    class Owner(Mixin, Base):
        test_compatibility = False
        order_by_proximity = None
        multi_select = False
        actor_continuation = tuple(continuations)
        target_continuation = ()
        picked_continuation = ()
        continuations_are_multi_push = True
        continuation_linking = types.SimpleNamespace(continuations_to_cancel=0)
        group_id = 0

        def __init__(self, sim):
            self.sim, self.target, self.context = sim, None, Context(sim)
            self.interaction_parameters = {}

        def _apply_loot(self, _):
            pass

        def get_participants(self, participant):
            return (self.sim,)

        def get_name(self):
            return 'picker'

        def get_icon_info(self):
            return None

        def get_continuation_aop_and_context(self, continuation, actor, picked_item_ids=(), **_):
            target = next(s for s in world if s.sim_id in picked_item_ids)
            return AOP(continuation.affordance, actor, target), Context(actor)

    Owner._test = classmethod(ea.function(PICKER, 'AutonomousSimPickerSuperInteraction._test', globals_, Owner))
    Owner.has_valid_choice = classmethod(ea.function(PICKER, 'AutonomousSimPickerSuperInteraction.has_valid_choice', globals_))
    Owner._run_interaction_gen = ea.function(PICKER, 'AutonomousSimPickerSuperInteraction._run_interaction_gen', globals_)
    Owner.find_best_sim_id = ea.function(PICKER, 'AutonomousSimPickerSuperInteraction.find_best_sim_id', globals_)
    Owner.find_best_sim_id_base = ea.function(PICKER, 'AutonomousSimPickerSuperInteraction.find_best_sim_id_base', globals_)
    Owner.push_tunable_continuation = ea.function('interactions.base.interaction', 'Interaction.push_tunable_continuation', globals_, defaults=(True, 'NEXT', globals_['DEFAULT'], False, None))
    Owner.are_affordances_linked = classmethod(lambda cls, affordance, context, sim: True)

    class Tuned(Owner):
        pass

    return Owner, Tuned


def install_picker_fix(owner):
    from codebleu_loose_ends.fixes import autonomous_sim_pickers as module
    module._game.update(ParticipantType=ParticipantType, AutonomousSimPickerSuperInteraction=owner, flexmethod=flexmethod)
    owner._get_valid_sim_choices_gen = module._make(None)
    activate(module.FIX)
    return module


def autonomy(picker, actor, pings=200):
    """Pings autonomy like an idle Sim: whenever the picker tests valid it runs; stops once something gets pushed."""
    runs = 0
    for _ in range(pings):
        if not picker._test(None, Context(actor)):
            break
        runs += 1
        ea.drive(picker(actor)._run_interaction_gen(None))
        if actor.queue:
            break
    return runs, list(actor.queue)


def wake_up(actor, target):
    if 'RecentlyDisciplined' in actor.buffs:
        return TestResult(False, 'recently disciplined')
    if not target.asleep:
        return TestResult(False, 'target awake')
    return TestResult.TRUE


class AutonomousSimPickerTests(unittest.TestCase):

    def household(self, owner_asleep):
        wolf = Sim('Wolf')
        return wolf, [wolf, Sim('Owner A', asleep=owner_asleep), Sim('Owner B'), Sim('Angel')]

    def run_pet(self, fixed, owner_asleep, wolf_buffs=()):
        random.seed(3)
        wolf, world = self.household(owner_asleep)
        wolf.buffs.update(wolf_buffs)
        owner, tuned = build_picker(world, [Continuation(Affordance('dog_Misbehavior_WakeUpSim', wake_up))])
        if fixed:
            install_picker_fix(owner)
        return autonomy(tuned, wolf)

    def test_pet_vanilla_loops_when_everyone_is_awake(self):
        runs, pushed = self.run_pet(False, owner_asleep=False)
        self.assertEqual((runs, pushed), (200, []))

    def test_pet_fixed_stops_when_everyone_is_awake(self):
        runs, pushed = self.run_pet(True, owner_asleep=False)
        self.assertEqual((runs, pushed), (0, []))

    def test_pet_fixed_stops_when_recently_disciplined(self):
        self.assertEqual(self.run_pet(False, True, {'RecentlyDisciplined'})[0], 200)
        self.assertEqual(self.run_pet(True, True, {'RecentlyDisciplined'}), (0, []))

    def test_pet_fixed_still_wakes_a_sleeping_owner_first_try(self):
        runs, pushed = self.run_pet(True, owner_asleep=True)
        self.assertEqual(runs, 1)
        self.assertEqual([(name, target.name) for name, target in pushed], [('dog_Misbehavior_WakeUpSim', 'Owner A')])

    def test_lockout_and_untested_continuations(self):
        actor = Sim('Whitaker')
        guest = Sim('Guest')
        world = [actor, guest]
        chat = Continuation(Affordance('SocialPickerSI', lambda a, t: TestResult.TRUE))
        owner, tuned = build_picker(world, [chat])
        install_picker_fix(owner)
        self.assertTrue(tuned.has_valid_choice(None, Context(actor)))
        actor.lockouts.add(guest)
        self.assertFalse(tuned.has_valid_choice(None, Context(actor)))
        actor.lockouts.clear()
        owner, tuned = build_picker(world, [Continuation(Affordance('x', lambda a, t: TestResult(False)), target=ParticipantType.TargetSim)])
        install_picker_fix(owner)
        self.assertTrue(tuned.has_valid_choice(None, Context(actor)), 'continuations not aimed at the picked Sim keep vanilla results')

    def test_included_override_and_inactive_fix_are_vanilla(self):
        actor, awake = Sim('Wolf'), Sim('Owner')
        world = [actor, awake]
        owner, tuned = build_picker(world, [Continuation(Affordance('wake', wake_up))])
        module = install_picker_fix(owner)
        self.assertEqual([r.sim_id for r in tuned._get_valid_sim_choices_gen(None, Context(actor), included_override={awake.sim_id})], [awake.sim_id])
        self.assertFalse(tuned.has_valid_choice(None, Context(actor)))
        module.FIX.state = guard.FAULTED
        self.assertTrue(tuned.has_valid_choice(None, Context(actor)))

    def test_fault_in_filter_keeps_candidate_and_switches_off(self):
        actor, awake = Sim('Wolf'), Sim('Owner')
        world = [actor, awake]

        def broken(a, t):
            raise RuntimeError('mod tuning exploded')
        owner, tuned = build_picker(world, [Continuation(Affordance('wake', broken))])
        module = install_picker_fix(owner)
        self.assertTrue(tuned.has_valid_choice(None, Context(actor)))
        self.assertEqual(module.FIX.state, guard.FAULTED)


class SocialPickerCooldownTests(unittest.TestCase):

    def build(self, mixer_found):
        from codebleu_loose_ends.fixes import social_picker_cooldown as module
        no_result = TestResult(False)
        autonomy_service = types.SimpleNamespace(find_best_action=lambda request: (types.SimpleNamespace(super_interaction=types.SimpleNamespace(running=True)) if mixer_found else None))
        globals_ = dict(interactions=types.SimpleNamespace(ParticipantType=ParticipantType), logger=types.SimpleNamespace(assert_log=lambda *a, **k: None),
            InteractionBucketType=types.SimpleNamespace(BASED_ON_SOURCE=0), AutonomyRequest=lambda *a, **k: types.SimpleNamespace(interactions_to_invalidate=[]),
            autonomy=types.SimpleNamespace(autonomy_modes=types.SimpleNamespace(SocialAutonomy=0)), services=types.SimpleNamespace(autonomy_service=lambda: autonomy_service),
            AffordanceObjectPair=types.SimpleNamespace(execute_interaction=lambda mixer: TestResult.TRUE),
            event_testing=types.SimpleNamespace(results=types.SimpleNamespace(EnqueueResult=types.SimpleNamespace(NONE=no_result))))
        original = ea.function('interactions.social.social_picker_super_interaction', 'SocialPickerSuperInteraction._run_interaction_gen', globals_)
        self.social_picker = type('SocialPickerSuperInteraction', (Affordance,), {})
        module._game.update(ParticipantType=ParticipantType, InteractionContext=types.SimpleNamespace(SOURCE_AUTONOMY='autonomy'),
            AutonomyModesTuning=types.SimpleNamespace(LOCKOUT_TIME=15), clock=Clock, SocialPickerSuperInteraction=self.social_picker,
            services=types.SimpleNamespace(time_service=lambda: types.SimpleNamespace(sim_now=Clock.now)))
        module._failures.clear()
        activate(module.FIX)
        actor, target = Sim('Whitaker'), Sim('Guest')

        class Interaction:
            SOCIAL_STATIC_COMMODITY = None
            sim = actor
            context = types.SimpleNamespace(source='autonomy', clone_for_sim=lambda *a, **k: None)

            def get_participant(self, participant):
                return target
        return module, original, Interaction(), actor, target

    def test_no_mixer_cools_down_only_social_pickers(self):
        Clock.now = 0
        module, original, interaction, actor, target = self.build(mixer_found=False)
        self.assertFalse(ea.drive(module._make(original)(interaction, None)))
        self.assertEqual(actor.lockouts, set(), 'EA lockouts are untouched')
        self.assertTrue(module.is_cooling_down(actor, target, self.social_picker))
        self.assertFalse(module.is_cooling_down(actor, target, Affordance), 'other follow-ups are unaffected')
        Clock.now = 15
        self.assertFalse(module.is_cooling_down(actor, target, self.social_picker))

    def test_picker_skips_cooling_down_target(self):
        Clock.now = 0
        module, original, interaction, actor, target = self.build(mixer_found=False)
        world = [actor, target]
        chat = Continuation(self.social_picker('SocialPickerSI', lambda a, t: TestResult.TRUE))
        owner, tuned = build_picker(world, [chat])
        install_picker_fix(owner)
        self.assertTrue(tuned.has_valid_choice(None, Context(actor)))
        ea.drive(module._make(original)(interaction, None))
        self.assertFalse(tuned.has_valid_choice(None, Context(actor)))

    def test_vanilla_records_nothing(self):
        module, original, interaction, actor, target = self.build(mixer_found=False)
        ea.drive(original(interaction, None))
        self.assertEqual((actor.lockouts, module._failures), (set(), {}))

    def test_success_and_user_directed_are_untouched(self):
        module, original, interaction, actor, target = self.build(mixer_found=True)
        self.assertTrue(ea.drive(module._make(original)(interaction, None)))
        self.assertEqual(module._failures, {})
        module, original, interaction, actor, target = self.build(mixer_found=False)
        interaction.context = types.SimpleNamespace(source='pie menu', clone_for_sim=lambda *a, **k: None)
        ea.drive(module._make(original)(interaction, None))
        self.assertEqual(module._failures, {})


class PieMenuScopeTests(unittest.TestCase):

    def test_scope_opens_only_for_generate_choices(self):
        from codebleu_loose_ends.fixes import pie_menu_filters as module
        module._game['caches'] = types.SimpleNamespace(global_cache_version=7)
        activate(module.FIX)
        pick = module._make_get_targets_from_pick(lambda *a: ('target', 0, ()))
        message = module._make_create_pie_menu_message(lambda *a: 'message')
        seen = []

        def generate_choices():
            pick()
            seen.append(module._token())
            message()
            seen.append(module._token())

        def has_choices():
            pick()
            seen.append(module._token())
        module._game['generate_choices'] = generate_choices.__code__
        generate_choices()
        has_choices()
        self.assertIsNotNone(seen[0])
        self.assertEqual(seen[1:], [None, None])
        module._scope['open'] = True
        has_choices()
        self.assertIsNone(seen[-1], 'a hover closes a scope a failed build left open')


class Clock:
    now = 0

    @staticmethod
    def interval_in_sim_minutes(minutes):
        return minutes


class LeaveLotTests(unittest.TestCase):

    def build(self, blocked):
        from codebleu_loose_ends.fixes import leave_lot as module
        Affordance = type('Affordance', (), {'super_affordance_klobberers': None, '__init__': lambda self, name: setattr(self, 'name', name)})
        wave = Affordance('WaveGoodBye')
        must_run_affordance = Affordance('MustRun_WaveGoodBye')
        must_run_calls = []

        class Element:
            NPC_LEAVE_LOT_NOW_AFFORDANCES = {wave}
            NPC_LEAVE_LOT_NOW_MUST_RUN_AFFORDANCE = {must_run_affordance}
            must_run = False
            participant = 'Actor'

        sim = Sim('Beatrice', household=2)
        sim.is_sim = True
        sim.is_npc = True
        sim.lives_here = False
        sim.trait_tracker = types.SimpleNamespace(get_leave_lot_now_interactions=lambda must: set())
        class SimState(list):
            def all_guaranteed_si_gen(self, *a, **k):
                return iter([types.SimpleNamespace(affordance='bonfire', si_state=types.SimpleNamespace(test_non_constraint_compatibility=lambda *a: not blocked))])
        sim.si_state = SimState()

        def push(affordance, target, context):
            sim.queue.append(types.SimpleNamespace(affordance=affordance))
            return True
        sim.push_super_affordance = push
        element = Element()
        element.interaction = types.SimpleNamespace(get_participant=lambda participant: sim, context=types.SimpleNamespace(run_priority=None, group_id=None))
        globals_ = dict(PushNpcLeaveLotNowInteraction=Element, logger=types.SimpleNamespace(error=lambda *a, **k: None))
        Element.can_push = ea.function('interactions.push_npc_leave_lot_now', 'PushNpcLeaveLotNowInteraction.can_push', globals_)
        original = ea.function('interactions.push_npc_leave_lot_now', 'PushNpcLeaveLotNowInteraction._do_behavior', globals_)
        situation_manager = types.SimpleNamespace(make_sim_leave_now_must_run=lambda s: (must_run_calls.append(s), push(must_run_affordance, None, None)))
        module._game.update(clock=Clock, PushNpcLeaveLotNowInteraction=Element, services=types.SimpleNamespace(
            time_service=lambda: types.SimpleNamespace(sim_now=Clock.now), get_zone_situation_manager=lambda: situation_manager))
        module._streaks.clear()
        activate(module.FIX)
        return module, original, element, sim, must_run_calls

    def attempts(self, do_behavior, element, sim, minutes):
        runs = 0
        for minute in range(0, minutes, 1):
            Clock.now = minute
            if sim.queue:
                break
            do_behavior(element)
            runs += 1
        return runs

    def test_vanilla_never_leaves_while_blocked(self):
        module, original, element, sim, calls = self.build(blocked=True)
        self.assertEqual(self.attempts(original, element, sim, 120), 120)
        self.assertEqual((list(sim.queue), calls), ([], []))

    def test_fixed_escalates_after_ten_minutes_of_failures(self):
        module, original, element, sim, calls = self.build(blocked=True)
        runs = self.attempts(module._make(original), element, sim, 120)
        self.assertEqual(runs, 11)
        self.assertEqual(calls, [sim])
        self.assertEqual(sim.queue[0].affordance.name, 'MustRun_WaveGoodBye')

    def test_unblocked_is_vanilla(self):
        module, original, element, sim, calls = self.build(blocked=False)
        self.assertEqual(self.attempts(module._make(original), element, sim, 120), 1)
        self.assertEqual((sim.queue[0].affordance.name, calls), ('WaveGoodBye', []))

    def test_queue_guard_throttling_still_escalates(self):
        module, original, element, sim, calls = self.build(blocked=True)
        do_behavior = module._make(original)
        for minute in (0, 1, 2, 3, 4):
            Clock.now = minute
            do_behavior(element)
        self.assertEqual(calls, [], 'five attempts in five minutes are not yet ten minutes of failure')
        Clock.now = 4 + 240
        do_behavior(element)
        self.assertEqual(calls, [sim], 'the first attempt after a 240-minute suppression escalates')

    def test_two_attempts_are_not_enough(self):
        module, original, element, sim, calls = self.build(blocked=True)
        do_behavior = module._make(original)
        for minute in (0, 30):
            Clock.now = minute
            do_behavior(element)
        self.assertEqual(calls, [])

    def test_streak_forgotten_after_six_hours(self):
        module, original, element, sim, calls = self.build(blocked=True)
        do_behavior = module._make(original)
        for minute in (0, 1, 400, 401):
            Clock.now = minute
            do_behavior(element)
        self.assertEqual(calls, [])
        Clock.now = 411
        do_behavior(element)
        self.assertEqual(calls, [sim])


class PhantomMoodTests(unittest.TestCase):

    def component(self, fixed):
        from codebleu_loose_ends.fixes import phantom_mood as module
        globals_ = dict(caches=types.SimpleNamespace(clear_all_caches=lambda: None), BuffUpdateType=types.SimpleNamespace(UPDATE=0),
            gsi_handlers=types.SimpleNamespace(buff_handlers=types.SimpleNamespace(sim_mood_log_archiver=types.SimpleNamespace(enabled=False))))
        update = ea.function('objects.components.buff_component', 'BuffComponent._update_current_mood', globals_)
        Mood = collections.namedtuple('Mood', 'name buffs')
        MoodBuff = type('MoodBuff', (str,), {'is_mood_buff': True})
        tense = Mood('Tense', (None, types.SimpleNamespace(buff_type=MoodBuff('Hidden_Tense'))))
        uncomfortable = Mood('Uncomfortable', (None, types.SimpleNamespace(buff_type=MoodBuff('Hidden_Uncomfortable'))))

        class Component:
            _active_mood = None
            _active_mood_intensity = 0
            _active_mood_buff_handle = None
            _active_buffs = {}
            owner = 'Daniel'

            def __init__(self):
                self.buffs = {}
                self.next_handle = 1
                self.weights = {'Tense': 5, 'Uncomfortable': 0}

            def _get_largest_mood(self):
                mood = max((tense, uncomfortable), key=lambda m: self.weights[m.name])
                return mood, self.weights[mood.name], []

            def _get_intensity_from_mood(self, mood, weight):
                return 1

            def _should_update_mood(self, mood, intensity, changeable):
                return mood is not self._active_mood or intensity != self._active_mood_intensity

            def add_buff(self, buff_type, update_mood=True):
                handle = self.next_handle
                self.next_handle += 1
                self.buffs[handle] = buff_type
                if buff_type == 'Hidden_Tense':
                    self.weights['Uncomfortable'] = 9
                    self._update_current_mood()
                return handle

            def remove_buff(self, handle, update_mood=True):
                self.buffs.pop(handle, None)

            def on_mood_changed(self, **_):
                pass

        Component._update_current_mood = update
        if fixed:
            module.FIX.state = guard.ACTIVE
            Component._loose_ends_mood_buff_adds = 0
            Component._loose_ends_mood_update_deferred = False
            Component.add_buff = module._make_add_buff(Component.add_buff)
            Component._update_current_mood = module._make_update_current_mood(update)
        return Component()

    def test_vanilla_orphans_a_hidden_mood_buff(self):
        component = self.component(fixed=False)
        component._update_current_mood()
        self.assertEqual(sorted(component.buffs.values()), ['Hidden_Tense', 'Hidden_Uncomfortable'])
        self.assertEqual(component._active_mood.name, 'Uncomfortable')

    def test_fixed_keeps_only_the_current_hidden_mood_buff(self):
        component = self.component(fixed=True)
        component._update_current_mood()
        self.assertEqual(list(component.buffs.values()), ['Hidden_Uncomfortable'])
        self.assertEqual(component._active_mood.name, 'Uncomfortable')


if __name__ == '__main__':
    unittest.main()
