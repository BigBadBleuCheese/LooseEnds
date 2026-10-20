"""
Scores interactions against a Sim's moodlet scoring modifiers without rescanning every moodlet for every interaction.

Every pie menu entry and social mixer gets a content score, and part of it is the actor's scoring modifiers
(Sim.get_actor_scoring_modifier). EA asks every active buff, for every scored interaction, to sum its affordance
modifiers; each modifier then checks whether the interaction is in its affordance list and in each of its affordance list
snippets by iterating them. With a few hundred buffs (common with mods) that is about 245,000 calls and 113,000 snippet
scans for one pie menu.

Whether a modifier applies to an interaction, before its tests, depends only on tuning: the interaction, the modifier's
affordances, affordance lists and category tags. So the modifiers of a Sim's current buffs are gathered once, each
modifier's affordances and lists are flattened into one set, and the modifiers that can apply are remembered per
interaction. A modifier that can apply still runs its tests every time, in EA's order, with EA's handling of a test
that raises. Modifiers worth 0 are skipped; they add 0 whatever their tests say. The gathering is redone whenever the
Sim's buffs change, and any buff or modifier of a type other than EA's own is asked the EA way.
"""

from codebleu_loose_ends.fingerprint import fingerprint
from codebleu_loose_ends.guard import Fix, Hook, Requirement, unpatched

_game = {}
_modifier_data = {}
_INDEX_ATTRIBUTE = '_loose_ends_scoring_index'
stats = {'fast': 0, 'rebuilt': 0, 'passed through': 0}

EXPORTED_COMPONENT_METHOD = 0x33ec1815b1c7dfae

_FAST = 0
_EFFECT = 1
_MODIFIER = 2


def _same(left, right):
    return len(left) == len(right) and all(a is b for a, b in zip(left, right))


def _flatten(modifier):
    affordances = modifier._affordances
    lists = tuple(modifier._affordance_lists)
    key = (affordances, modifier._interaction_category_tags, modifier._interaction_category_blacklist_tags, modifier._score_bonus, modifier._test) + lists + tuple(
        getattr(snippet, 'value', snippet) for snippet in lists)
    entry = _modifier_data.get(id(modifier))
    if entry is not None and entry[0] is modifier and _same(entry[1], key):
        return entry[2]
    members = set(affordances)
    for snippet in lists:
        members.update(snippet)
    blacklist = modifier._interaction_category_blacklist_tags
    tags = modifier._interaction_category_tags
    blacklist_only = bool(blacklist) and not affordances and not lists and not tags
    data = (frozenset(members), tags, blacklist, blacklist_only, modifier._score_bonus, modifier._test)
    _modifier_data[id(modifier)] = (modifier, key, data)
    return data


def _build_index(buffs):
    game_effect_modifiers = _game['GameEffectModifiers']
    scoring_modifier = _game['AffordanceReferenceScoringModifier']
    affordance_modifier = _game['AFFORDANCE_MODIFIER']
    items = []
    for buff in buffs:
        effects = getattr(buff, 'effect_modification', None)
        if type(effects) is not game_effect_modifiers:
            items.append((_EFFECT, effects))
            continue
        for modifier in effects._get_modifiers(affordance_modifier):
            if type(modifier) is not scoring_modifier:
                items.append((_MODIFIER, modifier))
                continue
            data = _flatten(modifier)
            if data[4]:
                items.append((_FAST, data))
    return {'items': items, 'affordances': {}}


def _candidates(index, affordance):
    found = index['affordances'].get(affordance)
    if found is not None:
        return found
    tags = affordance.interaction_category_tags
    found = []
    for kind, value in index['items']:
        if kind != _FAST:
            found.append((kind, value))
            continue
        members, category_tags, blacklist, blacklist_only, score, test = value
        if tags & blacklist:
            continue
        if affordance in members or tags & category_tags or blacklist_only:
            found.append((_FAST, (score, test)))
    found = tuple(found)
    index['affordances'][affordance] = found
    return found


def _routes_to_buffs(sim_info):
    """True when the Sim info's get_actor_scoring_modifier is still EA's component method for BuffComponent's version."""
    method = getattr(type(sim_info), 'get_actor_scoring_modifier', None)
    if method is not None and method is _game.get('verified'):
        return True
    code = getattr(method, '__code__', None)
    if code is None or getattr(method, '__wrapped__', None) is not _game['buff_method'] or fingerprint(code) != EXPORTED_COMPONENT_METHOD:
        return False
    _game['verified'] = method
    return True


def _intact():
    """True while the EA functions the index stands in for are still the ones checked at install (no later mod wrapped them)."""
    return all(unpatched(owner.__dict__.get(name)) is function for owner, name, function in _game['bypassed'])


def _index_for(sim_info):
    if not _routes_to_buffs(sim_info):
        return None
    component = getattr(sim_info, _game['buffs_attribute'], None)
    if type(component) is not _game['BuffComponent']:
        return None
    buffs = tuple(component._active_buffs.values())
    entry = component.__dict__.get(_INDEX_ATTRIBUTE)
    if entry is not None and _same(entry[0], buffs):
        return entry[1]
    if not _intact():
        return None
    index = _build_index(buffs)
    setattr(component, _INDEX_ATTRIBUTE, (buffs, index))
    stats['rebuilt'] += 1
    return index


def _make(original):
    def get_actor_scoring_modifier(self, *args, **kwargs):
        if not FIX.active or kwargs or len(args) != 2 or args[0] is None:
            stats['passed through'] += 1
            return original(self, *args, **kwargs)
        try:
            index = _index_for(self.sim_info)
        except Exception as e:
            FIX.fault(e)
            return original(self, *args, **kwargs)
        if index is None:
            stats['passed through'] += 1
            return original(self, *args, **kwargs)
        affordance, resolver = args
        try:
            candidates = _candidates(index, affordance)
        except Exception as e:
            FIX.fault(e)
            return original(self, *args, **kwargs)
        stats['fast'] += 1
        return _score_candidates(candidates, affordance, resolver)
    get_actor_scoring_modifier.__wrapped__ = original
    return get_actor_scoring_modifier


def _score_candidates(candidates, affordance, resolver):
    total = 0
    for kind, value in candidates:
        if kind == _FAST:
            score, test = value
            if test:
                try:
                    passed = test.run_tests(resolver)
                except:
                    passed = False
                if not passed:
                    continue
            total += score
        elif kind == _EFFECT:
            total += value.get_affordance_scoring_modifier(affordance, resolver)
        else:
            total += value.get_score_for_type(affordance, resolver)
    return total


def clear():
    _modifier_data.clear()


def _build():
    from game_effect_modifier.affordance_reference_scoring_modifier import AffordanceReferenceScoringModifier
    from game_effect_modifier.game_effect_modifiers import GameEffectModifiers
    from game_effect_modifier.game_effect_type import GameEffectType
    from objects.components.buff_component import BuffComponent
    from objects.components.types import BUFF_COMPONENT
    from sims.sim import Sim
    from sims.sim_info_mixin import HasSimInfoMixin
    if Sim.get_actor_scoring_modifier is not HasSimInfoMixin.__dict__.get('get_actor_scoring_modifier'):
        raise AttributeError('Sim.get_actor_scoring_modifier is not the one HasSimInfoMixin defines')
    _game.update(GameEffectModifiers=GameEffectModifiers, AffordanceReferenceScoringModifier=AffordanceReferenceScoringModifier, AFFORDANCE_MODIFIER=GameEffectType.AFFORDANCE_MODIFIER,
        BuffComponent=BuffComponent, buffs_attribute=BUFF_COMPONENT.instance_attr, buff_method=BuffComponent.__dict__.get('get_actor_scoring_modifier'))
    _game.pop('verified', None)
    _game['bypassed'] = tuple((owner, name, owner.__dict__.get(name)) for owner, name in (
        (GameEffectModifiers, 'get_affordance_scoring_modifier'), (GameEffectModifiers, '_get_modifiers'),
        (AffordanceReferenceScoringModifier, 'get_score_for_type'), (AffordanceReferenceScoringModifier, 'is_type')))
    return [
        Hook(HasSimInfoMixin, 'get_actor_scoring_modifier', 0x64b443ece16b0532, _make, stack_on_mods=False)], [
        Requirement(BuffComponent, 'get_actor_scoring_modifier', 0xec2acd7abe43ae72, stack_on_mods=False),
        Requirement(GameEffectModifiers, 'get_affordance_scoring_modifier', 0xcfa33c3c51ff1b14, stack_on_mods=False),
        Requirement(GameEffectModifiers, '_get_modifiers', 0xd233b175065f7d49, stack_on_mods=False),
        Requirement(AffordanceReferenceScoringModifier, 'get_score_for_type', 0xf19f92a2fb9dcee0, stack_on_mods=False),
        Requirement(AffordanceReferenceScoringModifier, 'is_type', 0x7656757db50215a3, stack_on_mods=False)]


FIX = Fix('content_scoring', 'Score pie menu entries without rescanning every moodlet', _build)
