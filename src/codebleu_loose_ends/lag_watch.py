"""
looseends.watch_lag: times every simulation tick (Zone.update) until stopped, and profiles a window of ticks by itself
when watching starts, when a lot finishes loading (including after travel) or when a tick runs slower than a threshold. Each capture is written to the Mods folder
with the tick statistics from just before it started and during it.

Zone.update is wrapped while watching and put back by looseends.watch_lag stop (unless another mod has replaced it since).
"""

import collections
import time

MAX_CAPTURES = 8
COOLDOWN_SECONDS = 30
HISTORY_SECONDS = 30

_state = {'watching': False}


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def _summary(label, durations, elapsed):
    busy = sum(durations)
    return '\n'.join((
        '{}: {} ticks in {:.1f} real seconds'.format(label, len(durations), elapsed),
        '  time inside ticks: {:.2f} s ({:.0%} of real time)'.format(busy, busy / elapsed if elapsed else 0),
        '  per tick: mean {:.1f} ms, median {:.1f} ms, 95th percentile {:.1f} ms, worst {:.1f} ms'.format(
            1000 * busy / len(durations) if durations else 0, 1000 * _percentile(durations, 0.5), 1000 * _percentile(durations, 0.95), 1000 * max(durations or [0])),
        '  ticks over 33 ms: {}, over 100 ms: {}, over 250 ms: {}'.format(
            sum(1 for d in durations if d > 0.033), sum(1 for d in durations if d > 0.1), sum(1 for d in durations if d > 0.25))))


def _say(text):
    """Writes to the console that started watching, or after travel (which ends that console session) to the current one."""
    try:
        _state['output'](text)
        return
    except Exception:
        pass
    try:
        import services
        import sims4.commands
        client = services.client_manager().get_first_client()
        if client is not None:
            _state['output'] = sims4.commands.CheatOutput(client.id)
            _state['output'](text)
    except Exception:
        pass


def start(seconds, threshold_ms, output, make_profiler, write_profile, logger):
    from zone import Zone
    if _state['watching']:
        output('Loose Ends: already watching for lag. Stop with looseends.watch_lag stop.')
        return
    original = Zone.__dict__['update']

    def update(self, *args, **kwargs):
        if not _state['watching']:
            return original(self, *args, **kwargs)
        capture = _state['capture']
        profiler = capture['profiler'] if capture is not None else None
        started = time.perf_counter()
        try:
            if profiler is not None:
                profiler.enable()
            return original(self, *args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
            try:
                _after_tick(self, started, time.perf_counter())
            except Exception:
                logger.exception('Loose Ends: lag watch failed; stopping')
                stop()

    update.__wrapped__ = original
    _state.update(watching=True, original=original, wrapper=update, output=output, logger=logger, make_profiler=make_profiler,
        write_profile=write_profile, seconds=seconds, threshold=threshold_ms / 1000, zone=None, capture=None, captures=0,
        cooldown_until=0.0, history=collections.deque())
    Zone.update = update
    output('Loose Ends: watching for lag, including after travel. Right away, each time a lot finishes loading, and whenever a tick takes over {} ms, '
        'the next {} real seconds are profiled (at most {} captures). Stop with looseends.watch_lag stop.'.format(threshold_ms, seconds, MAX_CAPTURES))


def _after_tick(zone, started, ended):
    duration = ended - started
    capture = _state['capture']
    if capture is not None:
        if zone is capture['zone']:
            capture['ticks'].append(duration)
            if ended - capture['started'] >= _state['seconds']:
                _write(capture, ended)
            return
        _write(capture, ended, ' (cut short by leaving the lot)')
    if not zone.is_zone_running:
        return
    history = _state['history']
    if zone is not _state['zone']:
        reason = 'watching started on this lot' if _state['zone'] is None else 'loading onto a lot finished'
        _state['zone'] = zone
        history.clear()
        _begin(reason, zone, ended, duration)
        return
    history.append((ended, duration))
    while history and ended - history[0][0] > HISTORY_SECONDS:
        history.popleft()
    if duration > _state['threshold'] and ended >= _state['cooldown_until']:
        _begin('a tick took {:.0f} ms'.format(1000 * duration), zone, ended, duration)


def _begin(reason, zone, now, duration):
    if _state['captures'] >= MAX_CAPTURES:
        return
    profiler, kind = _state['make_profiler']()
    history = list(_state['history'])
    _state['history'].clear()
    zone_id = None
    try:
        import services
        zone_id = services.current_zone_id()
    except Exception:
        pass
    _state['capture'] = {'reason': reason, 'zone': zone, 'started': now, 'profiler': profiler, 'kind': kind, 'ticks': [], 'trigger': duration,
        'before': [d for _, d in history], 'before_elapsed': (history[-1][0] - history[0][0]) if len(history) > 1 else 0.0, 'zone_id': zone_id,
        'clock': time.strftime('%H:%M:%S')}
    _state['captures'] += 1


def _write(capture, now, note=''):
    _state['capture'] = None
    _state['cooldown_until'] = now + COOLDOWN_SECONDS
    profiler = capture['profiler']
    profiler.create_stats()
    lines = ['Loose Ends lag capture', 'Started at {} because {}{}'.format(capture['clock'], capture['reason'], note), 'Zone: {}'.format(capture['zone_id'])]
    if capture['before']:
        lines.append(_summary('Before the capture (no profiler)', capture['before'], capture['before_elapsed']))
    lines.append(_summary('During the capture ({})'.format(capture['kind']), capture['ticks'], now - capture['started']))
    lines.append('Only time inside Zone.update (the simulation tick) is profiled; the tick that started the capture is not in the profile.')
    base = _state['write_profile']('LooseEnds_lag', '\n'.join(lines), profiler)
    ticks = capture['ticks']
    _say('Loose Ends: lag capture {} of {} ({}): {} ticks, worst {:.0f} ms. Wrote {}.txt and .prof'.format(
        _state['captures'], MAX_CAPTURES, capture['reason'], len(ticks), 1000 * max(ticks or [0]), base))
    if _state['captures'] >= MAX_CAPTURES:
        _say('Loose Ends: that was the last capture; still timing ticks until looseends.watch_lag stop.')


def stop():
    from zone import Zone
    if not _state['watching']:
        return False
    capture = _state['capture']
    if capture is not None and capture['ticks']:
        try:
            _write(capture, time.perf_counter())
        except Exception:
            _state['logger'].exception('Loose Ends: could not write the last lag capture')
    _state['capture'] = None
    _state['watching'] = False
    if Zone.__dict__.get('update') is _state['wrapper']:
        Zone.update = _state['original']
    return True
