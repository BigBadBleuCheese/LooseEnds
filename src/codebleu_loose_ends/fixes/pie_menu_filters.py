"""
Reuses identical Sim filter queries within one pie menu build.

To decide whether a Sim picker interaction has any valid choice, EA runs the picker's Sim filter once per candidate Sim
(sim_filter_service.submit_filter with a single-Sim constraint). A pie menu build can do this tens of thousands of
times, and different pickers often run the same filter against the same candidates for the same requesting Sim.

The build scope opens when EA's generate_choices resolves its pick targets and closes once the pie menu message is built
(or right away if there is nothing to pick). has_choices, the hover query, resolves pick targets too but never builds a
message, so a pick from anything other than generate_choices opens nothing and closes any scope a failed build left
open. Within a scope, a non-aggregate, synchronous, callback-free filter query
is answered from the first identical query made under the same token, which also changes with EA's own cache version
(bumped by any statistic change or test event). Scoring a non-aggregate filter is deterministic, and nothing in the
build changes Sim state. Callers get a fresh list each time.
"""

import sys

from codebleu_loose_ends.guard import Fix, Hook, Requirement, _ea_original

_game = {}
_scope = {'generation': 0, 'open': False}
_memo = {'token': None, 'entries': {}}
stats = {'hits': 0, 'misses': 0, 'bypassed': 0}


def _token():
    if not _scope['open']:
        return None
    return _scope['generation'], _game['caches'].global_cache_version


def _open_scope():
    _scope['generation'] += 1
    _scope['open'] = True


def _close_scope():
    _scope['open'] = False
    _memo['token'] = None
    _memo['entries'] = {}


def _make_get_targets_from_pick(original):
    def _get_targets_from_pick(*args, **kwargs):
        if not FIX.active:
            return original(*args, **kwargs)
        if sys._getframe(1).f_code is not _game['generate_choices']:
            _close_scope()
            return original(*args, **kwargs)
        _open_scope()
        result = original(*args, **kwargs)
        if result is None or result[0] is None:
            _close_scope()
        return result
    _get_targets_from_pick.__wrapped__ = original
    return _get_targets_from_pick


def _make_create_pie_menu_message(original):
    def create_pie_menu_message(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            _close_scope()
    create_pie_menu_message.__wrapped__ = original
    return create_pie_menu_message


def _make_submit_filter(original):
    from singletons import EMPTY_SET

    def submit_filter(self, sim_filter, callback, callback_event_data=None, sim_constraints=None, requesting_sim_info=None, blacklist_sim_ids=EMPTY_SET, required_story_progression_arc=None,
            allow_yielding=True, start_time=None, end_time=None, household_id=None, club=None, additional_filter_terms=(), gsi_source_fn=None, include_rabbithole_sims=False,
            include_missing_pets=False):
        token = _token() if FIX.active else None
        if token is None or callback is not None or allow_yielding or (sim_filter is not None and sim_filter.is_aggregate_filter()):
            stats['bypassed'] += 1
            return original(self, sim_filter, callback, callback_event_data=callback_event_data, sim_constraints=sim_constraints, requesting_sim_info=requesting_sim_info,
                blacklist_sim_ids=blacklist_sim_ids, required_story_progression_arc=required_story_progression_arc, allow_yielding=allow_yielding, start_time=start_time,
                end_time=end_time, household_id=household_id, club=club, additional_filter_terms=additional_filter_terms, gsi_source_fn=gsi_source_fn,
                include_rabbithole_sims=include_rabbithole_sims, include_missing_pets=include_missing_pets)
        if _memo['token'] != token:
            _memo['token'] = token
            _memo['entries'] = {}
        try:
            key = (sim_filter, None if sim_constraints is None else tuple(sim_constraints), requesting_sim_info, frozenset(blacklist_sim_ids), required_story_progression_arc,
                start_time, end_time, household_id, club, tuple(additional_filter_terms), include_rabbithole_sims, include_missing_pets)
            cached = _memo['entries'].get(key)
        except TypeError:
            stats['bypassed'] += 1
            return original(self, sim_filter, callback, callback_event_data=callback_event_data, sim_constraints=sim_constraints, requesting_sim_info=requesting_sim_info,
                blacklist_sim_ids=blacklist_sim_ids, required_story_progression_arc=required_story_progression_arc, allow_yielding=allow_yielding, start_time=start_time,
                end_time=end_time, household_id=household_id, club=club, additional_filter_terms=additional_filter_terms, gsi_source_fn=gsi_source_fn,
                include_rabbithole_sims=include_rabbithole_sims, include_missing_pets=include_missing_pets)
        if cached is None:
            stats['misses'] += 1
            results = original(self, sim_filter, callback, callback_event_data=callback_event_data, sim_constraints=sim_constraints, requesting_sim_info=requesting_sim_info,
                    blacklist_sim_ids=blacklist_sim_ids, required_story_progression_arc=required_story_progression_arc, allow_yielding=allow_yielding, start_time=start_time,
                    end_time=end_time, household_id=household_id, club=club, additional_filter_terms=additional_filter_terms, gsi_source_fn=gsi_source_fn,
                    include_rabbithole_sims=include_rabbithole_sims, include_missing_pets=include_missing_pets)
            if results is None:
                return results
            cached = tuple(results)
            _memo['entries'][key] = cached
        else:
            stats['hits'] += 1
        return list(cached)
    submit_filter.__wrapped__ = original
    return submit_filter


def _build():
    import caches
    from filters.sim_filter_service import SimFilterService
    from server_commands import interaction_commands
    _game['caches'] = caches
    _game['generate_choices'] = getattr(_ea_original(interaction_commands.__dict__.get('generate_choices')), '__code__', None)
    return [
        Hook(interaction_commands, '_get_targets_from_pick', 0xe604bec287f1fb69, _make_get_targets_from_pick),
        Hook(interaction_commands, 'create_pie_menu_message', 0x8e247ce28d204905, _make_create_pie_menu_message),
        Hook(SimFilterService, 'submit_filter', 0x4d62074b61d58953, _make_submit_filter, stack_on_mods=False)], [
        Requirement(interaction_commands, 'generate_choices', 0xec7ae78fb8f5023f)]


FIX = Fix('pie_menu_filters', 'Reuse Sim filter results while building a pie menu', _build)
