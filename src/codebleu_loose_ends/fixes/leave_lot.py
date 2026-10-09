"""
NPCs told to leave the lot who can't start leaving are eventually made to leave the way EA forces it elsewhere.

Sims in a leave-now role get buff_role_LeaveLotNow, which leaves autonomy only Push_Leave_Lot to choose. Its basic extra
PushNpcLeaveLotNowInteraction._do_behavior skips every leave interaction that can_push rejects (any guaranteed,
incompatible interaction the Sim is in) or whose push fails its tests (WaveGoodBye refuses Sims wearing a towel, among
others), then returns having pushed nothing, with no log and no fallback. The role stays, so the Sim reruns
Push_Leave_Lot every few seconds for as long as the blocker lasts, sometimes for days.

After the original runs, if the NPC has no leave interaction queued or running, the attempt counts as failed. Once a
streak has at least MINIMUM_FAILED_ATTEMPTS failures spanning ESCALATE_AFTER_MINUTES, situation_manager.
make_sim_leave_now_must_run is called: the same escalation EA uses when an NPC's leave route fails or the lot is over
its NPC cap. A successful attempt clears the streak. A streak is only forgotten after FORGET_AFTER_MINUTES without a
failed attempt, longer than other mods (Queue Guard suppresses repeated autonomy for up to 240 sim minutes) may hold
the attempts back, so a throttled Sim still escalates on its next attempt instead of starting over.
"""

from codebleu_loose_ends.guard import Fix, Hook, Requirement, logger

ESCALATE_AFTER_MINUTES = 10
MINIMUM_FAILED_ATTEMPTS = 3
FORGET_AFTER_MINUTES = 360
MAXIMUM_TRACKED_SIMS = 256

_game = {}
_streaks = {}
stats = {'failed attempts': 0, 'escalations': 0}


def _leave_affordances(element, sim_info):
    owner = _game['PushNpcLeaveLotNowInteraction']
    affordances = set(owner.NPC_LEAVE_LOT_NOW_AFFORDANCES)
    affordances.update(owner.NPC_LEAVE_LOT_NOW_MUST_RUN_AFFORDANCE)
    affordances.update(sim_info.trait_tracker.get_leave_lot_now_interactions(False))
    affordances.update(sim_info.trait_tracker.get_leave_lot_now_interactions(True))
    return affordances


def _is_leaving(sim, affordances):
    for interaction in sim.queue:
        if interaction.affordance in affordances:
            return True
    for interaction in sim.si_state:
        if interaction.affordance in affordances:
            return True
    return False


def _forget_stale(now, forget):
    for sim_id in [sim_id for sim_id, (_, last, _) in _streaks.items() if now - last > forget]:
        del _streaks[sim_id]


def _after_attempt(element):
    if element.must_run:
        return
    sim = element.interaction.get_participant(element.participant)
    if sim is None or not getattr(sim, 'is_sim', False):
        return
    sim_info = sim.sim_info
    if not sim_info.is_npc or sim_info.lives_here:
        return
    if _is_leaving(sim, _leave_affordances(element, sim_info)):
        _streaks.pop(sim.sim_id, None)
        return
    stats['failed attempts'] += 1
    now = _game['services'].time_service().sim_now
    forget = _game['clock'].interval_in_sim_minutes(FORGET_AFTER_MINUTES)
    if len(_streaks) >= MAXIMUM_TRACKED_SIMS:
        _forget_stale(now, forget)
    streak = _streaks.get(sim.sim_id)
    if streak is None or now - streak[1] > forget:
        _streaks[sim.sim_id] = (now, now, 1)
        return
    first, _, count = streak
    count += 1
    _streaks[sim.sim_id] = (first, now, count)
    if count < MINIMUM_FAILED_ATTEMPTS or now - first < _game['clock'].interval_in_sim_minutes(ESCALATE_AFTER_MINUTES):
        return
    del _streaks[sim.sim_id]
    stats['escalations'] += 1
    logger.info('Loose Ends: {} failed to start leaving {} times; making them leave.', sim, count)
    _game['services'].get_zone_situation_manager().make_sim_leave_now_must_run(sim)


def _make(original):
    def _do_behavior(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if FIX.active:
            try:
                _after_attempt(self)
            except Exception as e:
                FIX.fault(e)
        return result
    _do_behavior.__wrapped__ = original
    return _do_behavior


def _build():
    import clock
    import services
    from interactions.push_npc_leave_lot_now import PushNpcLeaveLotNowInteraction
    from situations.situation_manager import SituationManager
    _game.update(clock=clock, services=services, PushNpcLeaveLotNowInteraction=PushNpcLeaveLotNowInteraction)
    return [Hook(PushNpcLeaveLotNowInteraction, '_do_behavior', 0x93bb9a145634c6f6, _make)], [
        Requirement(PushNpcLeaveLotNowInteraction, 'can_push', 0x18b483bcf28f72f3),
        Requirement(SituationManager, 'make_sim_leave_now_must_run', 0xd2ccddee4f4b55c5)]


FIX = Fix('leave_lot', 'Visitors stuck trying to leave the lot are sent home', _build)
