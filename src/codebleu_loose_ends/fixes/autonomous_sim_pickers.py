"""
Autonomous Sim pickers only offer Sims their follow-up interaction can actually run on.

AutonomousSimPickerSuperInteraction decides whether it has a valid choice, and later which Sim to pick, from the Sim
filter and candidate tests alone. Unlike AutonomousObjectPickerInteraction, it never checks lockouts or tests the
follow-up it will push on the picked Sim, and when that push fails nothing is recorded. Autonomy keeps choosing the
picker, it ends instantly having pushed nothing, and autonomy picks it again on the next tick: pets with the Wake Up
Sims misbehavior picking awake Sims thousands of times an hour, aggregate_SocialObservation_Chat picking Sims nobody
can chat with, and so on.

Candidates are filtered the way EA already filters object picker candidates: locked-out Sims are dropped, and when a
follow-up targets the picked Sim, a candidate is kept only if at least one such follow-up passes its tests on it. When
the follow-up doesn't depend on the picked Sim or involves carrying something (its carry target comes from the running
picker), when choices are forced through included_override, or for Sims who aren't instanced, results are exactly
vanilla's. The follow-up is tested with the carry target cleared, as Interaction.get_continuation_aop_and_context does
for follow-ups that don't involve carrying. Social follow-ups also skip Sims the social picker cooldown fix remembers.
"""

from codebleu_loose_ends.fixes import social_picker_cooldown
from codebleu_loose_ends.guard import ABSENT, Fix, Hook, Requirement

_game = {}
stats = {'kept': 0, 'dropped': 0}


def _keeps(inst_or_cls, context, result):
    sim_info = getattr(result, 'sim_info', None)
    actor = context.sim
    if sim_info is None or actor is None:
        return True
    candidate = sim_info.get_sim_instance()
    if candidate is None:
        return True
    if actor.has_lockout(candidate):
        return False
    continuations = inst_or_cls.actor_continuation
    if not continuations:
        return True
    picked_sim = _game['ParticipantType'].PickedSim
    picked_item_ids = {sim_info.sim_id}
    local_context = context.clone_for_sim(actor)
    local_context.carry_target = None
    for continuation in continuations:
        affordance = continuation.affordance
        if continuation.target != picked_sim or affordance is None or not affordance.is_super or affordance.involves_carry:
            return True
        if social_picker_cooldown.is_cooling_down(actor, candidate, affordance):
            continue
        if actor.test_super_affordance(affordance, candidate, local_context, picked_item_ids=picked_item_ids):
            return True
    return False


def _make(_):
    flexmethod = _game['flexmethod']
    owner = _game['AutonomousSimPickerSuperInteraction']

    @flexmethod
    def _get_valid_sim_choices_gen(cls, inst, target, context, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        choices = super(owner, inst_or_cls)._get_valid_sim_choices_gen(target, context, **kwargs)
        if not FIX.active or kwargs.get('included_override'):
            yield from choices
            return
        for result in choices:
            if FIX.active:
                try:
                    keep = _keeps(inst_or_cls, context, result)
                except Exception as e:
                    FIX.fault(e)
                    keep = True
                if not keep:
                    stats['dropped'] += 1
                    continue
                stats['kept'] += 1
            yield result

    return _get_valid_sim_choices_gen


def _build():
    from interactions import ParticipantType
    from interactions.base.picker_interaction import AutonomousSimPickerSuperInteraction, SimPickerMixin
    from sims4.utils import flexmethod
    _game.update(ParticipantType=ParticipantType, AutonomousSimPickerSuperInteraction=AutonomousSimPickerSuperInteraction, flexmethod=flexmethod)
    return [Hook(AutonomousSimPickerSuperInteraction, '_get_valid_sim_choices_gen', ABSENT, _make)], [
        Requirement(SimPickerMixin, '_get_valid_sim_choices_gen', 0x3c3eeabebaddf896),
        Requirement(AutonomousSimPickerSuperInteraction, 'has_valid_choice', 0x9d0f21532ba41c3e),
        Requirement(AutonomousSimPickerSuperInteraction, '_run_interaction_gen', 0x52f3c815bc7ed408)]


FIX = Fix('autonomous_sim_pickers', 'Autonomous Sim pickers skip Sims their follow-up can\'t run on (pet and chat loops)', _build)
