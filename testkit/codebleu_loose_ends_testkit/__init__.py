"""Loose Ends test kit: cheat commands that set up the stuck states the fixes target. For testing only."""

import services
import sims4.commands
import sims4.resources

TOWEL_BUFF = 119404


def _sim(first, last, output):
    sim_info = services.sim_info_manager().get_sim_info_by_name(first, last)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        output('Loose Ends test: {} {} is not on this lot.'.format(first, last))
    return sim


@sims4.commands.Command('looseendstest.towel', command_type=sims4.commands.CommandType.Live)
def towel(first: str = '', last: str = '', _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        sim = _sim(first, last, output)
        if sim is None:
            return
        buff = services.get_instance_manager(sims4.resources.Types.BUFF).get(TOWEL_BUFF)
        added = sim.debug_add_buff_by_type(buff)
        output('Loose Ends test: towel buff {} {}.'.format('added to' if added else 'NOT added to', sim))
    except Exception as e:
        output('Loose Ends test: towel failed: {}: {}'.format(type(e).__name__, e))


@sims4.commands.Command('looseendstest.leave', command_type=sims4.commands.CommandType.Live)
def leave(first: str = '', last: str = '', _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        sim = _sim(first, last, output)
        if sim is None:
            return
        if not sim.sim_info.is_npc:
            output('Loose Ends test: {} is in your household; pick a visitor.'.format(sim))
            return
        services.get_zone_situation_manager().make_sim_leave(sim)
        output('Loose Ends test: told {} to leave (leaving soon, then leaving now within 5 sim minutes).'.format(sim))
    except Exception as e:
        output('Loose Ends test: leave failed: {}: {}'.format(type(e).__name__, e))
