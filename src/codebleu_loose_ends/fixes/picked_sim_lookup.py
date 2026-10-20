"""
Looks up a Sim picker's candidate (the picked Sim) for its tests without walking every participant type EA knows.

To decide whether a Sim picker interaction has any valid choice, EA tests candidates one by one with the candidate as the
picked Sim. Most candidate tests ask the interaction resolver for the picked Sim. The resolver checks the request
against a long list of participant types, then hands it to the interaction's get_participants, which checks it against
more than a hundred participant types before reaching the one that reads picked_item_ids. In a busy pie menu that is
about 16,000 lookups and one of the largest costs left.

For a picked Sim request on a resolver built from an interaction class (no running interaction), with EA's own
get_participants, the answer is computed directly the way EA's code computes it: each picked id is looked up in the Sim
info manager, its instanced Sim (or the Sim info) is collected, and the resolver turns those back into Sim infos.
EA's periodic yield to the game's message pump inside get_participants is kept. The first 200 lookups each session are
answered EA's way and also computed directly for comparison; any difference switches the fix off.
"""

import weakref

from codebleu_loose_ends.guard import Fix, Hook, Requirement, unpatched

_game = {}
_routes = weakref.WeakKeyDictionary()
stats = {'fast': 0, 'checked': 0}

_CHECKS = 200
_EXPLICIT = frozenset(('cls', 'inst', 'participant_type', 'sim', 'target', 'carry_target', 'listener_filtering_enabled', 'target_type'))


def _uses_ea_lookup(affordance):
    try:
        return _routes[affordance]
    except KeyError:
        pass
    found = None
    for klass in getattr(affordance, '__mro__', ()):
        if 'get_participants' in klass.__dict__:
            found = klass.__dict__['get_participants']
            break
    result = found is not None and unpatched(found) is _game['interaction_lookup']
    _routes[affordance] = result
    return result


def _picked_sims(resolver, count=True):
    if count:
        interaction_module = _game['interaction_module']
        interaction_module.interaction_get_particpants_call_count += 1
        if interaction_module.interaction_get_particpants_call_count % interaction_module.SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD == 0:
            interaction_module.yield_to_irq()
    result = set()
    picked_item_ids = resolver.interaction_parameters.get('picked_item_ids')
    if picked_item_ids is not None:
        services = _game['services']
        for picked_item_id in picked_item_ids:
            sim_info = services.sim_info_manager().get(picked_item_id)
            if sim_info is not None:
                result.add(sim_info.get_sim_instance() or sim_info)
    result.discard(None)
    participants = tuple(result)
    to_sim_info = _game['resolver_module']._to_sim_info
    resolved = set()
    for participant in participants:
        resolved.add(to_sim_info(participant))
    return tuple(resolved)


def _intact():
    (first, first_name, first_function), (second, second_name, second_function), (third, third_name, third_function) = _game['relied_on']
    return unpatched(first.get(first_name)) is first_function and unpatched(second.get(second_name)) is second_function and unpatched(third.get(third_name)) is third_function


def _make(original):
    picked_sim = _game['PickedSim']

    def get_participants(self, participant_type, **kwargs):
        if participant_type is not picked_sim or not FIX.active or self._interaction is not None or self.super_interaction is not None:
            return original(self, participant_type, **kwargs)
        try:
            affordance = self.affordance
            usable = affordance is not None and self.context is not None and _EXPLICIT.isdisjoint(self.interaction_parameters) and \
                _game['services'].current_zone() is not None and _uses_ea_lookup(affordance) and _intact()
        except Exception as e:
            FIX.fault(e)
            usable = False
        if not usable:
            return original(self, participant_type, **kwargs)
        if stats['checked'] < _CHECKS:
            expected = original(self, participant_type, **kwargs)
            try:
                answer = _picked_sims(self, count=False)
                if answer != expected:
                    raise AssertionError('picked Sim lookup gave {} where the game gives {}'.format(answer, expected))
            except Exception as e:
                FIX.fault(e)
                return expected
            stats['checked'] += 1
            return expected
        try:
            answer = _picked_sims(self)
        except Exception as e:
            FIX.fault(e)
            return original(self, participant_type, **kwargs)
        stats['fast'] += 1
        return answer
    get_participants.__wrapped__ = original
    return get_participants


def _build():
    import services
    from event_testing import resolver as resolver_module
    from event_testing.resolver import InteractionResolver, Resolver
    from interactions import ParticipantType
    from interactions.base import interaction as interaction_module
    from interactions.base.interaction import Interaction
    for name in ('interaction_get_particpants_call_count', 'SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD', 'yield_to_irq'):
        getattr(interaction_module, name)
    getattr(resolver_module, '_to_sim_info')
    _game.update(services=services, resolver_module=resolver_module, interaction_module=interaction_module, PickedSim=ParticipantType.PickedSim,
        interaction_lookup=Interaction.__dict__.get('get_participants'))
    _game['relied_on'] = tuple((owner.__dict__, name, owner.__dict__.get(name)) for owner, name in (
        (Interaction, 'get_participants'), (Resolver, '_get_participants_base'), (Resolver, 'get_particpants_shared')))
    return [
        Hook(InteractionResolver, 'get_participants', 0x783a41bb91fc65b4, _make, stack_on_mods=False)], [
        Requirement(Interaction, 'get_participants', 0xf7090d9c5bc3048a, stack_on_mods=False),
        Requirement(Resolver, '_get_participants_base', 0x7f08b6be8eb3ba5f, stack_on_mods=False),
        Requirement(Resolver, 'get_particpants_shared', 0x4205dcd6e399b5f2, stack_on_mods=False)]


FIX = Fix('picked_sim_lookup', 'Find a Sim picker\'s candidate for its tests without the long lookup', _build)
