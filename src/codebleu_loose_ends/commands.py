"""Cheat console commands: looseends.status reports every fix; looseends.profile profiles one real pie menu build; looseends.profile_autonomy profiles one full autonomy run."""

import datetime
import io
import marshal
import os
import time

import sims4.commands

from codebleu_loose_ends import guard
from codebleu_loose_ends.fixes import autonomous_sim_pickers, content_scoring, dynasty_rules, leave_lot, picked_sim_lookup, pie_menu_filters, social_picker_cooldown, tag_checks, travel_event_subscriptions


@sims4.commands.Command('looseends.status', command_type=sims4.commands.CommandType.Live)
def loose_ends_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    for fix in guard.fixes:
        output('Loose Ends: {}: {}: {}'.format(fix.key, fix.state, fix.detail))
    output('Loose Ends: pie menu Sim filter memo {}'.format(pie_menu_filters.stats))
    output('Loose Ends: content scoring {}'.format(content_scoring.stats))
    output('Loose Ends: picked Sim lookups {}'.format(picked_sim_lookup.stats))
    output('Loose Ends: dynasty rule checks {}'.format(dynasty_rules.stats))
    output('Loose Ends: tag checks {}'.format(tag_checks.stats))
    output('Loose Ends: leave lot {}'.format(leave_lot.stats))
    output('Loose Ends: autonomous Sim picker candidates {}'.format(autonomous_sim_pickers.stats))
    output('Loose Ends: social picker cooldown {}'.format(social_picker_cooldown.stats))
    output('Loose Ends: travel event subscriptions {}'.format(travel_event_subscriptions.stats))


def _mods_folder():
    path = os.path.abspath(__file__)
    while True:
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
        if os.path.basename(path).lower() == 'mods':
            return path
    return os.path.join(os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4', 'Mods')


def _profiler():
    try:
        import cProfile
        return cProfile.Profile(), 'cProfile'
    except ImportError:
        import profile
        return profile.Profile(), 'profile (pure Python; absolute times are inflated)'


def _build(target, connection):
    import caches
    from server.pick_info import PickType
    from server_commands import interaction_commands
    caches.clear_all_caches()
    position = target.position
    routing_surface = target.routing_surface
    level = routing_surface.secondary_id if routing_surface is not None else 0
    return interaction_commands.generate_choices(target_id=target.id, pick_type=PickType.PICK_SIM if target.is_sim else PickType.PICK_OBJECT,
        x=position.x, y=position.y, z=position.z, level=level, _connection=connection)


@sims4.commands.Command('looseends.profile', command_type=sims4.commands.CommandType.Live)
def loose_ends_profile(target_id: int = None, _connection=None):
    import services
    output = sims4.commands.CheatOutput(_connection)
    target = services.object_manager().get(target_id) if target_id is not None else None
    if target is None:
        output('Loose Ends: usage: looseends.profile <id of the Sim or object to click>')
        return
    try:
        started = time.perf_counter()
        choices = _build(target, _connection)
        unprofiled = time.perf_counter() - started

        tracked = {'filter memo': pie_menu_filters.stats, 'content scoring': content_scoring.stats, 'picked Sim lookups': picked_sim_lookup.stats, 'dynasty rule checks': dynasty_rules.stats}
        before = {name: dict(values) for name, values in tracked.items()}
        profiler, kind = _profiler()
        started = time.perf_counter()
        profiler.runcall(_build, target, _connection)
        profiled = time.perf_counter() - started
        profiler.create_stats()
        memo = '; '.join('{} {}'.format(name, {k: values[k] - before[name][k] for k in before[name]}) for name, values in tracked.items())

        import pstats
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        base = os.path.join(_mods_folder(), 'LooseEnds_profile_{}'.format(stamp))
        with open(base + '.prof', 'wb') as f:
            marshal.dump(profiler.stats, f)

        text = io.StringIO()
        text.write('Loose Ends pie menu profile\nTarget: {} ({})\nChoices: {}\nUnprofiled build: {:.4f} s\nProfiled build: {:.4f} s with {}\nCounters during profiled build: {}\n\n'.format(target, target.id, choices, unprofiled, profiled, kind, memo))
        stats = pstats.Stats(profiler, stream=text)
        stats.sort_stats('cumulative').print_stats(150)
        stats.sort_stats('tottime').print_stats(150)
        with open(base + '.txt', 'w', encoding='utf-8') as f:
            f.write(text.getvalue())

        output('Loose Ends: {} choices; build took {:.4f} s ({:.4f} s profiled with {}); {}. Wrote {}.txt and .prof'.format(choices, unprofiled, profiled, kind.split(' ')[0], memo, base))
    except Exception as e:
        guard.logger.exception('Loose Ends: profile failed')
        output('Loose Ends: profile failed: {}: {}'.format(type(e).__name__, e))


@sims4.commands.Command('looseends.anatomy', command_type=sims4.commands.CommandType.Live)
def loose_ends_anatomy(target_id: int = None, _connection=None):
    import services
    output = sims4.commands.CheatOutput(_connection)
    target = services.object_manager().get(target_id) if target_id is not None else None
    if target is None:
        output('Loose Ends: usage: looseends.anatomy <id of the Sim or object to click>')
        return
    try:
        from codebleu_loose_ends import anatomy
        choices, plain, instrumented, path = anatomy.run(target, _connection, _build, _mods_folder(), [(fix.key, fix.state) for fix in guard.fixes])
        output('Loose Ends: {} choices; build took {:.4f} s ({:.4f} s with instruments). Wrote {}'.format(choices, plain, instrumented, path))
    except Exception as e:
        guard.logger.exception('Loose Ends: anatomy failed')
        output('Loose Ends: anatomy failed: {}: {}'.format(type(e).__name__, e))


@sims4.commands.Command('looseends.profile_autonomy', command_type=sims4.commands.CommandType.Live)
def loose_ends_profile_autonomy(sim_id: int = None, runs: int = 3, _connection=None):
    import services
    output = sims4.commands.CheatOutput(_connection)
    sim = services.object_manager().get(sim_id) if sim_id is not None else None
    if sim is None or not getattr(sim, 'is_sim', False):
        output('Loose Ends: usage: looseends.profile_autonomy <sim id> [runs]')
        return
    try:
        from codebleu_loose_ends import autonomy_profile
        summary, base = autonomy_profile.run(sim, max(1, runs), _profiler, _write_profile)
        output('Loose Ends: {}. Wrote {}.txt and .prof'.format(summary, base))
    except Exception as e:
        guard.logger.exception('Loose Ends: autonomy profile failed')
        output('Loose Ends: autonomy profile failed: {}: {}'.format(type(e).__name__, e))


_next_picker = {'armed': False, 'connection': None, 'installed': False, 'timing': False, 'times': {}}


def _write_profile(name, header, profiler):
    import pstats
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    base = os.path.join(_mods_folder(), '{}_{}'.format(name, stamp))
    with open(base + '.prof', 'wb') as f:
        marshal.dump(profiler.stats, f)
    text = io.StringIO()
    text.write(header + '\n\n')
    stats = pstats.Stats(profiler, stream=text)
    stats.sort_stats('cumulative').print_stats(150)
    stats.sort_stats('tottime').print_stats(150)
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(text.getvalue())
    return base


def _profile_picker(original, interaction, args, kwargs):
    output = sims4.commands.CheatOutput(_next_picker['connection'])
    profiler, kind = _profiler()
    started = time.perf_counter()
    try:
        return profiler.runcall(original, interaction, *args, **kwargs)
    finally:
        profiled = time.perf_counter() - started
        try:
            profiler.create_stats()
            base = _write_profile('LooseEnds_picker_profile', 'Loose Ends picker profile\nInteraction: {}\nProfiled picker build and show: {:.4f} s with {}'.format(interaction, profiled, kind), profiler)
            output('Loose Ends: {} picker took {:.4f} s to build and send ({}). Wrote {}.txt and .prof'.format(type(interaction).__name__, profiled, kind.split(' ')[0], base))
        except Exception as e:
            guard.logger.exception('Loose Ends: picker profile failed')
            output('Loose Ends: picker profile failed: {}: {}'.format(type(e).__name__, e))


def _install_picker_profiler():
    from interactions.base.picker_interaction import PickerSuperInteractionMixin
    original = PickerSuperInteractionMixin.__dict__['_show_picker_dialog']

    def _show_picker_dialog(self, *args, **kwargs):
        if _next_picker['timing']:
            return _time_picker(original, self, args, kwargs)
        if not _next_picker['armed']:
            return original(self, *args, **kwargs)
        _next_picker['armed'] = False
        return _profile_picker(original, self, args, kwargs)
    _show_picker_dialog.__wrapped__ = original
    PickerSuperInteractionMixin._show_picker_dialog = _show_picker_dialog

    from server.client import Client
    select_original = Client.__dict__['select_interaction']

    def select_interaction(self, *args, **kwargs):
        if not _next_picker['timing']:
            return select_original(self, *args, **kwargs)
        times = _next_picker['times']
        times.clear()
        times['click received'] = time.perf_counter()
        try:
            return select_original(self, *args, **kwargs)
        finally:
            times['click handled'] = time.perf_counter()
            if 'picker sent' in times:
                _report_picker_times()
    select_interaction.__wrapped__ = select_original
    Client.select_interaction = select_interaction
    _next_picker['installed'] = True


def _time_picker(original, interaction, args, kwargs):
    times = _next_picker['times']
    times['picker started'] = time.perf_counter()
    times['picker'] = type(interaction).__name__
    try:
        return original(interaction, *args, **kwargs)
    finally:
        times['picker sent'] = time.perf_counter()
        if 'click received' not in times or 'click handled' in times:
            _report_picker_times()


def _report_picker_times():
    times = _next_picker['times']
    _next_picker['timing'] = False
    try:
        output = sims4.commands.CheatOutput(_next_picker['connection'])
        picker = times['picker sent'] - times['picker started']
        if 'click received' in times:
            start = times['click received']
            output('Loose Ends: {}: picker started {:.3f} s after the click; built and sent {:.3f} s after the click (picker itself {:.3f} s); click fully handled after {:.3f} s; no profiler'.format(
                times['picker'], times['picker started'] - start, times['picker sent'] - start, picker, times['click handled'] - start))
        else:
            output('Loose Ends: {}: picker built and sent in {:.3f} s (no profiler; no pie menu click was seen first)'.format(times['picker'], picker))
    except Exception:
        guard.logger.exception('Loose Ends: could not report picker timings')


@sims4.commands.Command('looseends.profile_next_picker', command_type=sims4.commands.CommandType.Live)
def loose_ends_profile_next_picker(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        if not _next_picker['installed']:
            _install_picker_profiler()
        _next_picker['armed'] = True
        _next_picker['connection'] = _connection
        output('Loose Ends: the next picker window opened (by anyone) will be profiled.')
    except Exception as e:
        guard.logger.exception('Loose Ends: could not arm the picker profiler')
        output('Loose Ends: could not arm the picker profiler: {}: {}'.format(type(e).__name__, e))


@sims4.commands.Command('looseends.time_next_picker', command_type=sims4.commands.CommandType.Live)
def loose_ends_time_next_picker(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        if not _next_picker['installed']:
            _install_picker_profiler()
        _next_picker['timing'] = True
        _next_picker['times'] = {}
        _next_picker['connection'] = _connection
        output('Loose Ends: the next pie menu click and picker window will be timed, without the profiler.')
    except Exception as e:
        guard.logger.exception('Loose Ends: could not arm the picker timer')
        output('Loose Ends: could not arm the picker timer: {}: {}'.format(type(e).__name__, e))


def _toggle(key, enabled, connection):
    output = sims4.commands.CheatOutput(connection)
    fix = guard.set_enabled(key, enabled)
    if fix is None:
        output('Loose Ends: no fix named {}. Keys: {}'.format(key, ', '.join(f.key for f in guard.fixes)))
        return
    output('Loose Ends: {}: {}'.format(fix.key, fix.state))


@sims4.commands.Command('looseends.disable', command_type=sims4.commands.CommandType.Live)
def loose_ends_disable(key: str = None, _connection=None):
    _toggle(key, False, _connection)


@sims4.commands.Command('looseends.enable', command_type=sims4.commands.CommandType.Live)
def loose_ends_enable(key: str = None, _connection=None):
    _toggle(key, True, _connection)
