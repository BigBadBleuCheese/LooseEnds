"""
Answers "every participant" and "every Sim participant" lookups without checking every participant type EA knows.

Every time a super interaction is tested, EA asks the interaction for ParticipantType.All just to see whether any of them
is locked out by build mode, and social and multi-Sim tests ask for ParticipantType.AllSims. Interaction.get_participants
answers by checking the request against more than a hundred and fifty participant types one after another, and only a
dozen of those checks can ever apply to All or AllSims. At a busy high school this was about half of all the time spent
looking up participants.

For exactly ParticipantType.All or ParticipantType.AllSims, a copy of EA's method with only the checks those two can
reach runs instead, in the game's own module so it reads the same game state, services and helpers EA's does, in the same
order. EA's call counter and periodic yield to the game's message pump are kept. Everything else goes to EA. The fix
stays off if any other participant type shares a bit with All or AllSims. The first 200 lookups each session are
answered EA's way and also computed the short way for comparison; any difference switches the fix off.
"""

import types

from codebleu_loose_ends.guard import Fix, Hook

_CHECKS = 200
_POSITIONAL = ('participant_type', 'sim', 'target', 'carry_target', 'listener_filtering_enabled', 'target_type')
_game = {}
stats = {'fast': 0, 'checked': 0}


def get_participants(cls, inst, participant_type, sim=None, target=None, carry_target=None, listener_filtering_enabled=False, target_type=None, **interaction_parameters):
    """EA's Interaction.get_participants with only the checks All and AllSims reach; runs with the game module's globals."""
    participant_type = int(participant_type)
    if inst is not None:
        if inst.interaction_parameters and interaction_parameters:
            interaction_parameters = frozendict(inst.interaction_parameters, interaction_parameters)
        else:
            interaction_parameters = inst.interaction_parameters or interaction_parameters
    inst_or_cls = inst if inst is not None else cls
    if inst_or_cls.simless:
        sim = None
    else:
        sim = inst.sim if sim is DEFAULT else sim
    target = inst.target if target is DEFAULT else target
    object_manager = services.object_manager()
    inventory_manager = services.current_zone().inventory_manager
    definition_manager = services.definition_manager()
    if inst is not None:
        carry_target = inst.carry_target if carry_target is DEFAULT else carry_target
    is_all = participant_type & ParticipantType.All
    all_sims = participant_type & ParticipantType.AllSims
    if target_type is None:
        target_type = inst_or_cls.target_type
    result = set()
    if is_all:
        all_sims = True
    target_is_sim = target is not DEFAULT and target is not None and hasattr(target, 'is_sim') and target.is_sim
    if all_sims or participant_type & ParticipantType.Actor:
        result.add(sim)
    if is_all or participant_type & ParticipantType.Object:
        result.add(target)
    if (is_all or participant_type & ParticipantType.ObjectParent) and target is not None and not target.is_sim:
        result.add(target.parent)
    if is_all or participant_type & ParticipantType.CarriedObject:
        if carry_target is not None and carry_target is not DEFAULT:
            result.add(carry_target)
        elif 'carry_target' in interaction_parameters and target is not None:
            result.add(target)
    if all_sims or participant_type & ParticipantType.CarriedSim:
        if carry_target is not None and carry_target is not DEFAULT and carry_target.is_sim:
            result.add(carry_target)
        elif 'carry_target' in interaction_parameters and target is not None and target.is_sim:
            result.add(target)
    if (all_sims or participant_type & ParticipantType.TargetSimFrontCarriedSim) and target_is_sim and target.posture_state is not None:
        for hand, _, obj in get_carried_objects_gen(target):
            if obj.is_sim and (hand == Hand.LEFT or hand == Hand.RIGHT):
                result.add(obj)
                break
    if (all_sims or participant_type & ParticipantType.TargetSimBackCarriedSim) and target_is_sim and target.posture_state is not None:
        for hand, _, obj in get_carried_objects_gen(target):
            if obj.is_sim and hand == Hand.BACK:
                result.add(obj)
                break
    if (all_sims or participant_type & ParticipantType.TargetSim) and target_is_sim and not cls.invalid_imaginary_friend_target(sim, target):
        result.add(target)
    if all_sims or participant_type & ParticipantType.JoinTarget:
        join_target_ref = interaction_parameters.get('join_target_ref')
        if join_target_ref is not None:
            result.add(join_target_ref())
    if all_sims or participant_type & ParticipantType.Listeners:
        social_group = inst.social_group if inst is not None else None
        if target_type & TargetType.TARGET and target is not None and target_is_sim and (
                not target.ignore_group_socials(excluded_group=social_group) or not listener_filtering_enabled):
            result.add(target)
        if inst is not None and target_type & TargetType.GROUP and social_group is not None:
            for other_sim in social_group:
                if other_sim is sim:
                    continue
                for si in social_group.get_sis_registered_for_sim(other_sim):
                    if si.pipeline_progress >= PipelineProgress.RUNNING and not si.is_finishing:
                        break
                else:
                    continue
                if not inst.acquire_listeners_as_resource and listener_filtering_enabled and other_sim.ignore_group_socials(excluded_group=social_group):
                    continue
                if inst._required_sims is not None and listener_filtering_enabled and other_sim not in inst._required_sims:
                    continue
                result.add(other_sim)
    if sim is not None and hasattr(sim, 'posture_state') and sim.posture_state is not None:
        if is_all or participant_type & ParticipantType.ActorSurface:
            result.add(sim.posture_state.surface_target)
    if target is not None and target_is_sim and hasattr(target, 'posture_state'):
        target_posture_state = target.posture_state
    else:
        target_posture_state = None
    if target_posture_state and (is_all or participant_type & ParticipantType.TargetSurface):
        result.add(target_posture_state.surface_target)
    result.discard(None)
    if all_sims:
        imaginary_friend_service = services.get_imaginary_friend_service()
        if imaginary_friend_service is not None:
            for participant in list(result):
                if not hasattr(participant, 'sim_id') or not imaginary_friend_service.is_imaginary_friend(participant.sim_id) or not (
                        sim is not None and not participant.sim_id == sim.sim_id):
                    continue
                if imaginary_friend_service.get_child_sim(participant.sim_id) != sim.sim_id:
                    result.remove(participant)
    return tuple(result)


_TEMPLATE = get_participants
del get_participants

GLOBALS = ('frozendict', 'DEFAULT', 'services', 'ParticipantType', 'get_carried_objects_gen', 'Hand', 'TargetType', 'PipelineProgress',
    'interaction_get_particpants_call_count', 'SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD', 'yield_to_irq')


def _shortcut(module_globals, ea_function):
    """The trimmed copy, bound to the game module's globals and EA's defaults so it resolves every name exactly as EA's does."""
    code = _TEMPLATE.__code__
    return types.FunctionType(code, module_globals, code.co_name, ea_function.__defaults__)


def _overlapping_types(participant_type):
    """Names of participant types other than All and AllSims that share a bit with them."""
    shared = int(participant_type.All) | int(participant_type.AllSims)
    found = []
    for name in dir(participant_type):
        value = getattr(participant_type, name, None)
        if isinstance(value, participant_type) and value is not participant_type.All and value is not participant_type.AllSims and int(value) & shared:
            found.append(name)
    return found


def _same(answer, expected):
    return len(answer) == len(expected) and set(answer) == set(expected)


def _make(original):
    ea_function = original.__wrapped_method__
    module = _game['module']
    shortcut = _shortcut(module.__dict__, ea_function)
    every, every_sim = _game['All'], _game['AllSims']

    def get_participants(cls, inst, *args, **kwargs):
        if not args or (args[0] is not every and args[0] is not every_sim) or 'participant_type' in kwargs or not FIX.active:
            return ea_function(cls, inst, *args, **kwargs)
        if len(args) > 1 and (len(args) > len(_POSITIONAL) or any(name in kwargs for name in _POSITIONAL[1:len(args)])):
            return ea_function(cls, inst, *args, **kwargs)
        if stats['checked'] < _CHECKS:
            expected = ea_function(cls, inst, *args, **kwargs)
            try:
                answer = shortcut(cls, inst, *args, **kwargs)
                if not _same(answer, expected):
                    raise AssertionError('all participants lookup gave {} where the game gives {}'.format(answer, expected))
            except Exception as e:
                FIX.fault(e)
                return expected
            stats['checked'] += 1
            return expected
        module.interaction_get_particpants_call_count += 1
        if module.interaction_get_particpants_call_count % module.SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD == 0:
            module.yield_to_irq()
        stats['fast'] += 1
        return shortcut(cls, inst, *args, **kwargs)
    get_participants.__wrapped__ = ea_function
    return _game['flexmethod'](get_participants)


def _build():
    from interactions import ParticipantType
    from interactions.base import interaction as module
    from interactions.base.interaction import Interaction
    from sims4.utils import flexmethod
    missing = [name for name in GLOBALS if name not in module.__dict__]
    if missing:
        raise AttributeError('interactions.base.interaction no longer has ' + ', '.join(missing))
    if int(ParticipantType.All) != 16 or int(ParticipantType.AllSims) != 32:
        raise AttributeError('ParticipantType.All or AllSims changed value')
    overlapping = _overlapping_types(ParticipantType)
    if overlapping:
        raise AttributeError('participant types share bits with All or AllSims: ' + ', '.join(overlapping))
    _game.update(module=module, All=ParticipantType.All, AllSims=ParticipantType.AllSims, flexmethod=flexmethod)
    return [
        Hook(Interaction, 'get_participants', 0xf7090d9c5bc3048a, _make, stack_on_mods=False)], []


FIX = Fix('all_participants', 'Answer "every participant" lookups without checking every participant type', _build, restore_when_disabled=True)
