"""
Runs the game's real bytecode for content scoring, dynasty rule checks and picked Sim lookups against randomized stubs, and checks that the
content_scoring, dynasty_rules and picked_sim_lookup fixes give exactly the vanilla answers.
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
from sims4.utils import flexmethod

SCORING = 'game_effect_modifier.affordance_reference_scoring_modifier'
EFFECTS = 'game_effect_modifier.game_effect_modifiers'


class TestResult:
    def __init__(self, ok=True, reason='', *args, tooltip=None, icon=None, influence_by_active_mood=False, **kwargs):
        self.ok, self.reason, self.tooltip = ok, reason, tooltip
        self.icon, self.influence_by_active_mood = icon, influence_by_active_mood

    def __bool__(self):
        return self.ok

    def __and__(self, other):
        return TestResult(self.ok and other.ok)


TestResult.TRUE = TestResult(True)
RESULTS = types.SimpleNamespace(results=types.SimpleNamespace(TestResult=TestResult))


def activate(fix):
    fix.state = guard.ACTIVE


class SnippetMeta(type):
    def __iter__(cls):
        return iter(cls.value)


def snippet(affordances):
    return SnippetMeta('AffordanceList', (), {'value': tuple(affordances)})


class Tests:
    """A test set as EA's affordance modifiers hold it: falsy when empty, and run_tests may pass, fail or raise."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = 0

    def __bool__(self):
        return bool(self.outcomes)

    def run_tests(self, resolver):
        self.calls += 1
        outcome = self.outcomes[(id(resolver.affordance) // 16 + id(self) // 16) % len(self.outcomes)]
        if outcome == 'raise':
            raise RuntimeError('mod test exploded')
        return TestResult(outcome == 'pass')


def _cell(value):
    return (lambda: value).__closure__[0]


def exported_component_method(func, instance_attr):
    """EA's own component method forwarder (ComponentMetaclass builds one per component method), around func."""
    import fp
    code = fp.find(fp.module_code('objects.components'), 'ComponentMetaclass.__new__.build_exported_func.exported_func')
    cells = {'component_name': _cell(types.SimpleNamespace(instance_attr=instance_attr)), 'func': _cell(func)}
    method = types.FunctionType(code, {'__builtins__': __builtins__, 'ComponentContainer': object}, code.co_name, None, tuple(cells[name] for name in code.co_freevars))
    method.__wrapped__ = func
    return method


def build_scoring_classes():
    globals_ = {}
    modifier_type = 'AFFORDANCE_MODIFIER'

    class AffordanceReferenceScoringModifier:
        def __init__(self, score, affordances, lists, tags, blacklist, test):
            self._score_bonus, self._affordances, self._affordance_lists = score, affordances, lists
            self._interaction_category_tags, self._interaction_category_blacklist_tags = tags, blacklist
            self._pie_menu_parent_name = self._new_pie_menu_icon = None
            self._test = test

    AffordanceReferenceScoringModifier.is_type = ea.function(SCORING, 'AffordanceReferenceScoringModifier.is_type', globals_)
    AffordanceReferenceScoringModifier.get_score_for_type = ea.function(SCORING, 'AffordanceReferenceScoringModifier.get_score_for_type', globals_)

    class OtherModifier(AffordanceReferenceScoringModifier):
        pass

    effect_globals = dict(GameEffectType=types.SimpleNamespace(AFFORDANCE_MODIFIER=modifier_type))

    class GameEffectModifiers:
        def __init__(self, modifiers):
            self._modifier_map = {modifier_type: [(modifier, None) for modifier in modifiers]} if modifiers else {}

    GameEffectModifiers._get_modifiers = ea.function(EFFECTS, 'GameEffectModifiers._get_modifiers', effect_globals)
    GameEffectModifiers.get_affordance_scoring_modifier = ea.function(EFFECTS, 'GameEffectModifiers.get_affordance_scoring_modifier', effect_globals)

    class OtherEffects(GameEffectModifiers):
        pass

    class BuffComponent:
        def __init__(self):
            self._active_buffs = {}

    BuffComponent.get_actor_scoring_modifier = ea.function('objects.components.buff_component', 'BuffComponent.get_actor_scoring_modifier', {})

    class SimInfo:
        def __init__(self):
            self.buffs_component = BuffComponent()

    SimInfo.get_actor_scoring_modifier = exported_component_method(BuffComponent.__dict__['get_actor_scoring_modifier'], 'buffs_component')

    class Sim:
        def __init__(self):
            self.sim_info = SimInfo()

    Sim.get_actor_scoring_modifier = ea.function('sims.sim_info_mixin', 'HasSimInfoMixin.get_actor_scoring_modifier', {})
    return types.SimpleNamespace(modifier=AffordanceReferenceScoringModifier, other_modifier=OtherModifier, effects=GameEffectModifiers, other_effects=OtherEffects,
        component=BuffComponent, sim=Sim, modifier_type=modifier_type)


def install_scoring(classes):
    from codebleu_loose_ends.fixes import content_scoring as module
    module.clear()
    module._game.update(GameEffectModifiers=classes.effects, AffordanceReferenceScoringModifier=classes.modifier, AFFORDANCE_MODIFIER=classes.modifier_type,
        BuffComponent=classes.component, buffs_attribute='buffs_component', buff_method=classes.component.__dict__['get_actor_scoring_modifier'])
    module._game.pop('verified', None)
    module._game['bypassed'] = tuple((owner, name, owner.__dict__.get(name)) for owner, name in (
        (classes.effects, 'get_affordance_scoring_modifier'), (classes.effects, '_get_modifiers'), (classes.modifier, 'get_score_for_type'), (classes.modifier, 'is_type')))
    module.stats.update({key: 0 for key in module.stats})
    activate(module.FIX)
    return module, module._make(classes.sim.__dict__['get_actor_scoring_modifier'])


class Resolver:
    def __init__(self, affordance):
        self.affordance = affordance


class ContentScoringTests(unittest.TestCase):

    def world(self, rng, classes, affordance_count=60, buff_count=40):
        tags = list(range(12))
        affordances = [type('affordance_{}'.format(i), (), {'interaction_category_tags': frozenset(rng.sample(tags, rng.randint(0, 3)))}) for i in range(affordance_count)]
        snippets = [snippet(rng.sample(affordances, rng.randint(0, 15))) for _ in range(10)]
        outcomes = [[], ['pass'], ['fail'], ['pass', 'fail'], ['raise'], ['pass', 'raise', 'fail']]

        def modifier():
            kind = classes.other_modifier if rng.random() < 0.05 else classes.modifier
            return kind(rng.choice([0, 0, 1, 2, 5, -3]), tuple(rng.sample(affordances, rng.randint(0, 6))), tuple(rng.sample(snippets, rng.randint(0, 3))),
                frozenset(rng.sample(tags, rng.randint(0, 2))), frozenset(rng.sample(tags, rng.randint(0, 2)) if rng.random() < 0.4 else ()),
                Tests(rng.choice(outcomes)))

        def buff():
            kind = classes.other_effects if rng.random() < 0.05 else classes.effects
            return types.SimpleNamespace(effect_modification=kind([modifier() for _ in range(rng.choice([0, 0, 1, 1, 1, 2, 3]))]))

        sim = classes.sim()
        for i in range(buff_count):
            sim.sim_info.buffs_component._active_buffs[i] = buff()
        return sim, affordances, buff

    def test_scores_match_vanilla_on_random_worlds(self):
        classes = build_scoring_classes()
        module, fast = install_scoring(classes)
        rng = random.Random(11)
        compared = 0
        for _ in range(40):
            sim, affordances, buff = self.world(rng, classes)
            for round_ in range(4):
                for affordance in affordances:
                    resolver = Resolver(affordance)
                    vanilla = classes.sim.get_actor_scoring_modifier(sim, affordance, resolver)
                    self.assertEqual(fast(sim, affordance, resolver), vanilla, affordance.__name__)
                    compared += 1
                buffs = sim.sim_info.buffs_component._active_buffs
                if buffs and rng.random() < 0.5:
                    del buffs[rng.choice(list(buffs))]
                buffs[1000 + round_] = buff()
        self.assertGreater(module.stats['fast'], compared * 0.9)
        self.assertGreater(module.stats['rebuilt'], 100)

    def test_snippet_contents_are_rechecked_when_buffs_change(self):
        classes = build_scoring_classes()
        module, fast = install_scoring(classes)
        a, b = (type(name, (), {'interaction_category_tags': frozenset()}) for name in 'ab')
        listing = snippet([a])
        sim = classes.sim()
        sim.sim_info.buffs_component._active_buffs[1] = types.SimpleNamespace(effect_modification=classes.effects([classes.modifier(4, (), (listing,), frozenset(), frozenset(), Tests([]))]))
        self.assertEqual((fast(sim, a, Resolver(a)), fast(sim, b, Resolver(b))), (4, 0))
        listing.value = (b,)
        sim.sim_info.buffs_component._active_buffs[2] = types.SimpleNamespace(effect_modification=classes.effects([]))
        self.assertEqual((fast(sim, a, Resolver(a)), fast(sim, b, Resolver(b))), (0, 4))

    def test_unusual_calls_and_inactive_fix_pass_through(self):
        classes = build_scoring_classes()
        module, fast = install_scoring(classes)
        sim, affordances, _ = self.world(random.Random(5), classes)
        affordance = affordances[0]
        vanilla = classes.sim.get_actor_scoring_modifier(sim, affordance, Resolver(affordance))
        before = module.stats['passed through']
        self.assertEqual(fast(sim, affordance, resolver=Resolver(affordance)), vanilla)
        module.FIX.state = guard.DISABLED
        self.assertEqual(fast(sim, affordance, Resolver(affordance)), vanilla)
        self.assertEqual(module.stats['passed through'], before + 2)

    def test_component_method_fingerprint(self):
        from codebleu_loose_ends.fixes import content_scoring
        import fp
        actual, _ = fp.fp('objects.components', 'ComponentMetaclass.__new__.build_exported_func.exported_func')
        self.assertEqual('{:016x}'.format(actual), '{:016x}'.format(content_scoring.EXPORTED_COMPONENT_METHOD))

    def test_replaced_sim_info_method_passes_through(self):
        classes = build_scoring_classes()
        module, fast = install_scoring(classes)
        sim, affordances, _ = self.world(random.Random(9), classes)
        affordance = affordances[0]
        vanilla = classes.sim.get_actor_scoring_modifier(sim, affordance, Resolver(affordance))
        type(sim.sim_info).get_actor_scoring_modifier = lambda self, *args, **kwargs: 12345
        before = module.stats['passed through']
        self.assertEqual(fast(sim, affordance, Resolver(affordance)), 12345)
        self.assertEqual(module.stats['passed through'], before + 1)
        self.assertNotEqual(vanilla, 12345)

    def test_speed(self):
        classes = build_scoring_classes()
        module, fast = install_scoring(classes)
        rng = random.Random(3)
        sim, affordances, _ = self.world(rng, classes, affordance_count=400, buff_count=240)
        resolvers = [Resolver(affordance) for affordance in affordances]
        started = time.perf_counter()
        for affordance, resolver in zip(affordances, resolvers):
            classes.sim.get_actor_scoring_modifier(sim, affordance, resolver)
        vanilla = time.perf_counter() - started
        started = time.perf_counter()
        for affordance, resolver in zip(affordances, resolvers):
            fast(sim, affordance, resolver)
        cold = time.perf_counter() - started
        started = time.perf_counter()
        for affordance, resolver in zip(affordances, resolvers):
            fast(sim, affordance, resolver)
        warm = time.perf_counter() - started
        print('\ncontent scoring, 400 interactions x 240 buffs: vanilla {:.1f} ms, fix cold {:.1f} ms, fix warm {:.1f} ms'.format(vanilla * 1000, cold * 1000, warm * 1000))



def enum_values(module, qualname, known=None):
    """Member values of a game enum class, read from its class body bytecode (constants or other enums' members)."""
    import dis
    import fp
    values = {}
    instructions = list(dis.get_instructions(fp.find(fp.module_code(module), qualname)))
    for i, instruction in enumerate(instructions):
        if instruction.opname != 'STORE_NAME' or instruction.argval.startswith('_'):
            continue
        previous = instructions[i - 1]
        if previous.opname == 'LOAD_CONST' and isinstance(previous.argval, int):
            values[instruction.argval] = previous.argval
        elif previous.opname == 'BINARY_LSHIFT' and instructions[i - 2].opname == instructions[i - 3].opname == 'LOAD_CONST':
            values[instruction.argval] = instructions[i - 3].argval << instructions[i - 2].argval
        elif previous.opname == 'LOAD_ATTR' and known is not None and instructions[i - 2].argval == 'ParticipantType':
            values[instruction.argval] = known[previous.argval]
    return values


class Group:
    """A club interaction group class shaped like EA's (affordances, affordance_lists, EA's __iter__)."""


def build_dynasty(rng):
    group_iter = ea.function('clubs.club_tuning', 'ClubInteractionGroup.__iter__', {})
    Group.__iter__ = group_iter
    status = types.SimpleNamespace(ENCOURAGED='encouraged', DISCOURAGED='discouraged', NO_EFFECT='no effect')

    class Dynasty:
        def __init__(self, aligned, misaligned):
            self._aligned_activities, self._misaligned_activities = aligned, misaligned

    Dynasty.activities_gen = ea.function('dynasty.dynasty', 'Dynasty.activities_gen', {})
    Dynasty.is_interaction_encouraged_by_dynasty_rules = ea.function('dynasty.dynasty', 'Dynasty.is_interaction_encouraged_by_dynasty_rules', {'ClubRuleEncouragementStatus': status})
    return Dynasty, status, group_iter


def install_dynasty(Dynasty, status, group_iter):
    from codebleu_loose_ends.fixes import dynasty_rules as module
    module._entries.clear()
    module._game.update(ClubInteractionGroup=Group, ClubRuleEncouragementStatus=status, group_iter=group_iter,
        relied_on=((Group, '__iter__', group_iter), (Dynasty, 'activities_gen', Dynasty.__dict__['activities_gen'])))
    module.stats.update({key: 0 for key in module.stats})
    activate(module.FIX)
    return module, module._make(Dynasty.__dict__['is_interaction_encouraged_by_dynasty_rules'])


class Interacting:
    def __init__(self, affordance):
        self.affordance = affordance


class DynastyRuleTests(unittest.TestCase):

    def world(self, rng, Dynasty):
        affordances = [type('affordance_{}'.format(i), (), {}) for i in range(80)]
        for affordance in affordances:
            affordance.get_interaction_type = classmethod(lambda cls: cls)
        snippets = [snippet(rng.sample(affordances, rng.randint(0, 12))) for _ in range(8)]

        def group():
            kind = type('group', (Group,), {'affordances': tuple(rng.sample(affordances, rng.randint(0, 6))), 'affordance_lists': tuple(rng.sample(snippets, rng.randint(0, 3)))})
            return types.SimpleNamespace(action=kind)

        def rules():
            return {value: [group() for _ in range(rng.randint(0, 4))] for value in range(rng.randint(0, 4))}
        return Dynasty(rules(), rules()), affordances, rules

    def test_matches_vanilla_on_random_dynasties(self):
        rng = random.Random(21)
        Dynasty, status, group_iter = build_dynasty(rng)
        module, fast = install_dynasty(Dynasty, status, group_iter)
        seen = set()
        for _ in range(60):
            dynasty, affordances, rules = self.world(rng, Dynasty)
            for round_ in range(3):
                for affordance in affordances:
                    expected = Dynasty.is_interaction_encouraged_by_dynasty_rules(dynasty, Interacting(affordance))
                    self.assertEqual(fast(dynasty, Interacting(affordance)), expected)
                    seen.add(expected)
                dynasty._aligned_activities = rules()
        self.assertEqual(seen, {'encouraged', 'discouraged', 'no effect'})
        self.assertGreater(module.stats['rebuilt'], 60)

    def test_group_contents_replaced_are_noticed(self):
        rng = random.Random(23)
        Dynasty, status, group_iter = build_dynasty(rng)
        module, fast = install_dynasty(Dynasty, status, group_iter)
        a, b = (type(name, (), {'get_interaction_type': classmethod(lambda cls: cls)}) for name in 'ab')
        group = type('group', (Group,), {'affordances': (a,), 'affordance_lists': ()})
        dynasty = Dynasty({0: [types.SimpleNamespace(action=group)]}, {})
        self.assertEqual((fast(dynasty, Interacting(a)), fast(dynasty, Interacting(b))), ('encouraged', 'no effect'))
        group.affordances = (b,)
        self.assertEqual((fast(dynasty, Interacting(a)), fast(dynasty, Interacting(b))), ('no effect', 'encouraged'))

    def test_other_group_kinds_and_inactive_fix_pass_through(self):
        rng = random.Random(22)
        Dynasty, status, group_iter = build_dynasty(rng)
        module, fast = install_dynasty(Dynasty, status, group_iter)
        dynasty, affordances, _ = self.world(rng, Dynasty)
        special = type('special', (Group,), {'affordances': (), 'affordance_lists': (), '__iter__': lambda self: iter(affordances)})
        dynasty._aligned_activities = {0: [types.SimpleNamespace(action=special)]}
        self.assertEqual(fast(dynasty, Interacting(affordances[5])), 'encouraged')
        self.assertEqual(module.stats['passed through'], 1)
        module.FIX.state = guard.DISABLED
        self.assertEqual(fast(dynasty, Interacting(affordances[5])), 'encouraged')


class PickedSimInfo:
    def __init__(self, n, instanced, baby=False):
        self.sim_id = self.id = 5000 + n
        self.is_baby = baby
        self.sim_info = self
        self.instance = PickedSimObject(self) if instanced else None

    def get_sim_instance(self, **_):
        return self.instance


class PickedSimObject:
    is_sim = True

    def __init__(self, sim_info):
        self.sim_info, self.id = sim_info, sim_info.id


def build_resolver(world):
    """EA's InteractionResolver.get_participants, Resolver._get_participants_base/get_particpants_shared and
    Interaction.get_participants over stubs, with the game's real ParticipantType values."""
    import importlib
    participant_values = enum_values('interactions', 'ParticipantType')
    participant_type = type('ParticipantType', (), dict(participant_values))
    situation = list(enum_values('interactions', 'ParticipantTypeSituationSims', participant_values).values())
    saved = list(enum_values('interactions', 'ParticipantTypeSavedActor', participant_values).values())
    yields = []
    manager = types.SimpleNamespace(get=lambda sim_id: next((s for s in world if s.sim_id == sim_id), None))
    services = types.SimpleNamespace(sim_info_manager=lambda: manager, object_manager=lambda: None, definition_manager=lambda: None,
        current_zone=lambda: types.SimpleNamespace(inventory_manager=None))
    interaction_module = types.ModuleType('interaction_stub')
    interaction_module.__dict__.update(interaction_get_particpants_call_count=0, SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD=7, yield_to_irq=lambda: yields.append(1),
        ParticipantType=participant_type, ParticipantTypeSituationSims=situation, ParticipantTypeSavedActor=saved, services=services, DEFAULT=object(),
        frozendict=lambda *a: dict(a[0], **a[1]), __builtins__=__builtins__)
    get_participants = ea.function('interactions.base.interaction', 'Interaction.get_participants', interaction_module.__dict__)

    class Interaction:
        simless = False
        target_type = 1

    Interaction.get_participants = flexmethod(get_participants)
    test_constants = types.SimpleNamespace(SIM_INSTANCE='sim_instance', FROM_DATA_OBJECT='from_data_object', OBJECTIVE_GUID64='objective_guid64', FROM_EVENT_DATA='from_event_data')
    resolver_module = types.ModuleType('resolver_stub')
    resolver_module.__dict__.update(ParticipantType=participant_type, ParticipantTypeSituationSims=situation, event_testing=types.SimpleNamespace(test_constants=test_constants),
        RESOLVER_PARTICIPANT='resolver', services=services, __builtins__=__builtins__)
    resolver_module._to_sim_info = ea.function('event_testing.resolver', '_to_sim_info', resolver_module.__dict__)

    class Resolver:
        pass

    resolver_module.Resolver = Resolver
    Resolver._get_participants_base = ea.function('event_testing.resolver', 'Resolver._get_participants_base', resolver_module.__dict__)
    Resolver.get_particpants_shared = staticmethod(ea.function('event_testing.resolver', 'Resolver.get_particpants_shared', resolver_module.__dict__))

    class InteractionResolver(Resolver):
        def __init__(self, affordance, interaction, target=None, context=None, custom_sim=None, super_interaction=None, **interaction_parameters):
            self.affordance, self._interaction, self.target, self.context = affordance, interaction, target, context
            self.custom_sim, self.super_interaction, self.interaction_parameters = custom_sim, super_interaction, interaction_parameters

        interaction = property(lambda self: self._interaction)

    InteractionResolver.get_participants = ea.function('event_testing.resolver', 'InteractionResolver.get_participants', resolver_module.__dict__)
    return types.SimpleNamespace(Interaction=Interaction, InteractionResolver=InteractionResolver, Resolver=Resolver, resolver_module=resolver_module,
        interaction_module=interaction_module, services=services, ParticipantType=participant_type, yields=yields)


def install_picked(stubs):
    from codebleu_loose_ends.fixes import picked_sim_lookup as module
    module._routes.clear()
    module._game.update(services=stubs.services, resolver_module=stubs.resolver_module, interaction_module=stubs.interaction_module, PickedSim=stubs.ParticipantType.PickedSim,
        interaction_lookup=stubs.Interaction.__dict__['get_participants'],
        relied_on=((stubs.Interaction.__dict__, 'get_participants', stubs.Interaction.__dict__['get_participants']),
            (stubs.Resolver.__dict__, '_get_participants_base', stubs.Resolver.__dict__['_get_participants_base']),
            (stubs.Resolver.__dict__, 'get_particpants_shared', stubs.Resolver.__dict__['get_particpants_shared'])))
    module.stats.update({key: 0 for key in module.stats})
    activate(module.FIX)
    return module, module._make(stubs.InteractionResolver.__dict__['get_participants'])


class PickedSimLookupTests(unittest.TestCase):

    def test_matches_vanilla_including_yields(self):
        rng = random.Random(31)
        world = [PickedSimInfo(i, instanced=rng.random() < 0.5, baby=rng.random() < 0.1) for i in range(40)]
        vanilla_stubs, fixed_stubs = build_resolver(world), build_resolver(world)
        module, fast = install_picked(fixed_stubs)
        actor = PickedSimObject(world[0])
        for trial in range(3000):
            ids = set(rng.sample([s.sim_id for s in world] + [1, 2, 3], rng.randint(0, 3)))
            parameters = {'picked_item_ids': ids} if rng.random() < 0.95 else {}
            target = rng.choice([None, PickedSimObject(world[1])])
            context = types.SimpleNamespace(sim=actor, carry_target=None)
            vanilla = vanilla_stubs.InteractionResolver(vanilla_stubs.Interaction, None, target=target, context=context, **parameters)
            fixed = fixed_stubs.InteractionResolver(fixed_stubs.Interaction, None, target=target, context=context, **parameters)
            expected = vanilla.get_participants(vanilla_stubs.ParticipantType.PickedSim, event_key='subject')
            actual = fast(fixed, fixed_stubs.ParticipantType.PickedSim, event_key='subject')
            self.assertEqual(actual, expected, 'trial {}'.format(trial))
        self.assertEqual(module.FIX.state, guard.ACTIVE)
        self.assertEqual(module.stats['fast'], 2800)
        self.assertEqual(module.stats['checked'], 200)
        self.assertEqual(fixed_stubs.interaction_module.interaction_get_particpants_call_count, vanilla_stubs.interaction_module.interaction_get_particpants_call_count)
        self.assertEqual(len(fixed_stubs.yields), len(vanilla_stubs.yields))
        self.assertGreater(len(fixed_stubs.yields), 400)

    def test_other_requests_pass_through(self):
        world = [PickedSimInfo(i, instanced=True) for i in range(3)]
        stubs = build_resolver(world)
        module, fast = install_picked(stubs)
        context = types.SimpleNamespace(sim=PickedSimObject(world[0]), carry_target=None)
        resolver = stubs.InteractionResolver(stubs.Interaction, None, target=PickedSimObject(world[1]), context=context, picked_item_ids={world[2].sim_id})
        self.assertEqual(fast(resolver, stubs.ParticipantType.Actor), (world[0],))
        running = stubs.InteractionResolver(stubs.Interaction, types.SimpleNamespace(get_participants=lambda **_: (PickedSimObject(world[2]),)), target=None, context=context)
        self.assertEqual(fast(running, stubs.ParticipantType.PickedSim), (world[2],))
        clashing = stubs.InteractionResolver(stubs.Interaction, None, target=None, context=context, picked_item_ids={world[2].sim_id}, inst=None)
        with self.assertRaises(TypeError):
            fast(clashing, stubs.ParticipantType.PickedSim)
        other = type('Other', (stubs.Interaction,), {'get_participants': classmethod(lambda cls, **_: ())})
        self.assertEqual(fast(stubs.InteractionResolver(other, None, target=None, context=context, picked_item_ids={world[2].sim_id}), stubs.ParticipantType.PickedSim), ())
        self.assertEqual(module.stats['fast'], 0)

    def test_inherited_lookup_is_fast_and_no_zone_is_vanilla(self):
        world = [PickedSimInfo(i, instanced=True) for i in range(3)]
        stubs = build_resolver(world)
        module, fast = install_picked(stubs)
        module.stats['checked'] = 200
        subclass = type('Picker', (stubs.Interaction,), {})
        context = types.SimpleNamespace(sim=PickedSimObject(world[0]), carry_target=None)
        resolver = stubs.InteractionResolver(subclass, None, target=None, context=context, picked_item_ids={world[2].sim_id})
        self.assertEqual(fast(resolver, stubs.ParticipantType.PickedSim), (world[2],))
        self.assertEqual(module.stats['fast'], 1)
        stubs.services.current_zone = lambda: None
        with self.assertRaises(AttributeError):
            fast(resolver, stubs.ParticipantType.PickedSim)

    def test_disagreement_switches_off(self):
        world = [PickedSimInfo(i, instanced=True) for i in range(3)]
        stubs = build_resolver(world)
        module, fast = install_picked(stubs)
        module._game['resolver_module'] = types.SimpleNamespace(_to_sim_info=lambda participant: 'wrong')
        context = types.SimpleNamespace(sim=PickedSimObject(world[0]), carry_target=None)
        resolver = stubs.InteractionResolver(stubs.Interaction, None, target=None, context=context, picked_item_ids={world[2].sim_id})
        self.assertEqual(fast(resolver, stubs.ParticipantType.PickedSim), (world[2],))
        self.assertEqual(module.FIX.state, guard.FAULTED)

if __name__ == '__main__':
    unittest.main()
