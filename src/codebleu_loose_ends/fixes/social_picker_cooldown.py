"""
An autonomous SocialPickerSI that finds no social to run makes chat pickers skip that target for a while.

SocialPickerSuperInteraction asks social autonomy for a mixer on the target Sim and returns EnqueueResult.NONE when there
is none, recording nothing, so autonomy (often through aggregate_SocialObservation_Chat) picks the same Sim again
seconds later. When that happens, the pair is remembered for AutonomyModesTuning.LOCKOUT_TIME, the duration EA uses
after a failed autonomous push. The memory is this mod's own, not EA's lockouts: it is only consulted by the
autonomous Sim picker fix, and only for pickers whose follow-up is a SocialPickerSI, so everything else the actor
might do with that Sim autonomously is unaffected.
"""

from codebleu_loose_ends.guard import Fix, Hook

MAXIMUM_TRACKED_PAIRS = 1024

_game = {}
_failures = {}
stats = {'no social found': 0}


def _now():
    return _game['services'].time_service().sim_now


def _forget_expired(now):
    for pair in [pair for pair, until in _failures.items() if until <= now]:
        del _failures[pair]


def is_cooling_down(actor, target, affordance):
    """Whether the autonomous Sim picker fix should skip target as a picked Sim for this follow-up affordance."""
    if not FIX.active or not _failures:
        return False
    if not issubclass(affordance if isinstance(affordance, type) else type(affordance), _game['SocialPickerSuperInteraction']):
        return False
    until = _failures.get((actor.sim_id, target.sim_id))
    if until is None:
        return False
    if until <= _now():
        del _failures[(actor.sim_id, target.sim_id)]
        return False
    return True


def _remember(interaction):
    if interaction.context.source != _game['InteractionContext'].SOURCE_AUTONOMY:
        return
    target_sim = interaction.get_participant(_game['ParticipantType'].TargetSim)
    sim = interaction.sim
    if target_sim is None or sim is None or target_sim is sim:
        return
    now = _now()
    if len(_failures) >= MAXIMUM_TRACKED_PAIRS:
        _forget_expired(now)
    stats['no social found'] += 1
    _failures[(sim.sim_id, target_sim.sim_id)] = now + _game['clock'].interval_in_sim_minutes(_game['AutonomyModesTuning'].LOCKOUT_TIME)


def _make(original):
    def _run_interaction_gen(self, timeline):
        result = yield from original(self, timeline)
        if not result and FIX.active:
            try:
                _remember(self)
            except Exception as e:
                FIX.fault(e)
        return result
    _run_interaction_gen.__wrapped__ = original
    return _run_interaction_gen


def _build():
    import clock
    import services
    from autonomy.autonomy_modes_tuning import AutonomyModesTuning
    from interactions import ParticipantType
    from interactions.context import InteractionContext
    from interactions.social.social_picker_super_interaction import SocialPickerSuperInteraction
    _game.update(clock=clock, services=services, AutonomyModesTuning=AutonomyModesTuning, ParticipantType=ParticipantType, InteractionContext=InteractionContext,
        SocialPickerSuperInteraction=SocialPickerSuperInteraction)
    return [Hook(SocialPickerSuperInteraction, '_run_interaction_gen', 0x46f97a35133344e5, _make)], []


FIX = Fix('social_picker_cooldown', 'Autonomous chats that find nothing to say stop retrying the same Sim', _build)
