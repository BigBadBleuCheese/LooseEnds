"""
looseends.count_participants: for a stretch of real time, counts every call to Interaction.get_participants by
participant type and by the function that asked, with the time each call spent in itself, and writes the counts to the
Mods folder.

Interaction.get_participants is wrapped only while counting, and put back when the time is up or on
looseends.count_participants stop (unless another mod has replaced it since). Calls pass through unchanged.
"""

import collections
import datetime
import os
import sys
import time

from codebleu_loose_ends import guard

EARLY_RETURNS = ('Actor', 'Object', 'TargetSim')

_state = {'counting': False}


def _say(text):
    """Writes to the console that started counting, or after travel (which ends that console session) to the current one."""
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


def _zone_id():
    try:
        import services
        return services.current_zone_id()
    except Exception:
        return None


def start(seconds, output, mods_folder, logger):
    from interactions.base.interaction import Interaction
    from sims4.utils import flexmethod
    if _state['counting']:
        output('Loose Ends: already counting participant lookups. Stop early with looseends.count_participants stop.')
        return
    current = Interaction.__dict__.get('get_participants')
    inner = getattr(current, '__wrapped_method__', None)
    if inner is None:
        output('Loose Ends: Interaction.get_participants is not the kind of method this counter can wrap (another mod may have replaced it); nothing was changed.')
        return
    calls = collections.Counter()
    own = collections.defaultdict(float)
    stack = []
    getframe = sys._getframe
    perf = time.perf_counter

    def counted(cls, inst, *args, **kwargs):
        if not _state['counting'] or _state['wrapper'] is not wrapper:
            return inner(cls, inst, *args, **kwargs)
        participant_type = args[0] if args else kwargs.get('participant_type')
        key = (int(participant_type) if isinstance(participant_type, int) else type(participant_type).__name__, getframe(1).f_code)
        frame = [0.0]
        stack.append(frame)
        started = perf()
        try:
            return inner(cls, inst, *args, **kwargs)
        finally:
            elapsed = perf() - started
            stack.pop()
            own[key] += elapsed - frame[0]
            calls[key] += 1
            if stack:
                stack[-1][0] += elapsed
            elif started >= _state['deadline'] and _state['counting'] and _state['wrapper'] is wrapper:
                _finish('the time was up')

    wrapper = flexmethod(counted)
    _state.update(counting=True, owner=Interaction, original=current, wrapper=wrapper, calls=calls, own=own, output=output, mods_folder=mods_folder,
        logger=logger, started=time.perf_counter(), deadline=time.perf_counter() + seconds, zone_id=_zone_id(), clock=time.strftime('%H:%M:%S'))
    guard.temporary[id(wrapper)] = current
    Interaction.get_participants = wrapper
    output('Loose Ends: counting participant lookups for {} real seconds. The counts are written to the Mods folder when the time is up '
        '(or on looseends.count_participants stop).'.format(seconds))


def _restore():
    _state['counting'] = False
    owner, wrapper = _state['owner'], _state['wrapper']
    guard.temporary.pop(id(wrapper), None)
    if owner.__dict__.get('get_participants') is wrapper:
        owner.get_participants = _state['original']
        return True
    return False


def _finish(reason):
    try:
        restored = _restore()
        path, summary = _write(reason, restored)
        _say('Loose Ends: {}. Wrote {}'.format(summary, path))
    except Exception:
        _state['logger'].exception('Loose Ends: could not finish counting participant lookups')
        _say('Loose Ends: counting participant lookups failed; see the Loose Ends log.')


def stop():
    if not _state['counting']:
        return False
    _finish('looseends.count_participants stop')
    return True


def _type_names():
    from interactions import ParticipantType
    names = {}
    for name in dir(ParticipantType):
        value = getattr(ParticipantType, name, None)
        if isinstance(value, ParticipantType):
            names.setdefault(int(value), name)
    return names


def _type_label(value, names):
    if not isinstance(value, int):
        return '(not a number: {})'.format(value)
    if value in names:
        return names[value]
    bits = [names.get(1 << bit, 'bit {}'.format(bit)) for bit in range(value.bit_length()) if value >> bit & 1]
    return ' | '.join(bits) if bits else str(value)


def _caller_label(code):
    path = code.co_filename.replace('\\', '/')
    parts = path.split('/')
    return '{}:{} {}'.format('/'.join(parts[-2:]), code.co_firstlineno, code.co_name)


def _write(reason, restored):
    elapsed = time.perf_counter() - _state['started']
    calls, own = _state['calls'], _state['own']
    try:
        names = _type_names()
    except Exception:
        names = {}
    by_type_calls = collections.Counter()
    by_type_own = collections.defaultdict(float)
    for (value, code), count in calls.items():
        by_type_calls[value] += count
        by_type_own[value] += own[(value, code)]
    total_calls = sum(calls.values())
    total_own = sum(own.values())
    early = {value for value, name in names.items() if name in EARLY_RETURNS}

    lines = [
        'Loose Ends participant lookup count',
        'Started at {} on zone {}; ended on zone {} because {}'.format(_state['clock'], _state['zone_id'], _zone_id(), reason),
        'Real time counted: {:.1f} s'.format(elapsed),
        'Calls to Interaction.get_participants: {} ({:.0f} per real second)'.format(total_calls, total_calls / elapsed if elapsed else 0),
        'Time inside them: {:.1f} ms ({:.1f} ms per real second; {:.1f} us per call)'.format(
            1000 * total_own, 1000 * total_own / elapsed if elapsed else 0, 1e6 * total_own / total_calls if total_calls else 0),
        'Times are each call\'s own time (nested get_participants calls are counted separately) and include about a microsecond of counting per call.',
        'Actor, Object and TargetSim return early; every other type runs the whole chain of participant checks.']
    if not restored:
        lines.append('Another mod replaced Interaction.get_participants while counting, so the counter was left in place but switched off.')
    lines += [
        '',
        'By participant type',
        '   calls     own ms  us/call  share  path   type']
    for value, count in sorted(by_type_calls.items(), key=lambda item: -by_type_own[item[0]]):
        seconds = by_type_own[value]
        lines.append('{:8d} {:10.1f} {:8.2f} {:5.0%}  {:5}  {}'.format(
            count, 1000 * seconds, 1e6 * seconds / count, seconds / total_own if total_own else 0, 'early' if value in early else 'chain', _type_label(value, names)))
    lines += ['', 'By participant type and caller (top 80 by time)', '   calls     own ms  us/call  type / caller']
    for (value, code), seconds in sorted(own.items(), key=lambda item: -item[1])[:80]:
        count = calls[(value, code)]
        lines.append('{:8d} {:10.1f} {:8.2f}  {}  <-  {}'.format(count, 1000 * seconds, 1e6 * seconds / count, _type_label(value, names), _caller_label(code)))

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    path = os.path.join(_state['mods_folder'](), 'LooseEnds_participants_{}.txt'.format(stamp))
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    summary = 'counted {} participant lookups in {:.0f} s ({:.1f} ms of every real second)'.format(total_calls, elapsed, 1000 * total_own / elapsed if elapsed else 0)
    return path, summary
