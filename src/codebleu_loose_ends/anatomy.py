"""
looseends.anatomy: builds one real pie menu while timing the interactions, tests and pickers inside it.

Wrappers are put on the game functions a pie menu build goes through, only for the duration of the build, and removed
again before the command returns. Each records its own time minus the time of the recorded calls inside it, so the
report says which interaction, test type, participant lookup or picker spent the time, and how often. The wrappers
cost time themselves, so the absolute numbers are inflated; the proportions are what to read.
"""

import collections
import datetime
import io
import os
import time

from codebleu_loose_ends import guard

_perf = time.perf_counter


class _Recorder:
    def __init__(self):
        self.stack = []
        self.exclusive = collections.defaultdict(float)
        self.inclusive = collections.defaultdict(float)
        self.counts = collections.Counter()
        self.pickers = collections.defaultdict(lambda: collections.Counter())
        self.picker_stack = []

    def enter(self, key):
        self.stack.append([key, _perf(), 0.0])

    def leave(self):
        key, started, inner = self.stack.pop()
        elapsed = _perf() - started
        self.exclusive[key] += elapsed - inner
        if not any(frame[0] == key for frame in self.stack):
            self.inclusive[key] += elapsed
        self.counts[key] += 1
        if self.stack:
            self.stack[-1][2] += elapsed


_names = {}
_labels = {}


def _label(prefix, value):
    try:
        return _labels[(prefix, value)]
    except (KeyError, TypeError):
        pass
    text = '{} {}'.format(prefix, value)
    try:
        _labels[(prefix, value)] = text
    except TypeError:
        pass
    return text


def _name(affordance):
    try:
        return _names[affordance]
    except (KeyError, TypeError):
        pass
    name = getattr(affordance, '__name__', None) or type(affordance).__name__
    guid = getattr(affordance, 'guid64', None)
    text = '{} ({})'.format(name, guid) if guid else name
    try:
        _names[affordance] = text
    except TypeError:
        pass
    return text


def _test_name(test):
    if isinstance(test, type):
        return '[set] ' + test.__name__
    return type(test).__name__


class _Patches:
    def __init__(self):
        self.undo = []

    def set(self, owner, name, value):
        previous = owner.__dict__.get(name, _MISSING) if isinstance(owner, type) else getattr(owner, name, _MISSING)
        setattr(owner, name, value)
        if previous is not _MISSING:
            guard.temporary[id(value)] = previous
        self.undo.append((owner, name, previous, value))

    def restore(self):
        failures = []
        while self.undo:
            owner, name, previous, value = self.undo.pop()
            guard.temporary.pop(id(value), None)
            try:
                if previous is _MISSING:
                    delattr(owner, name)
                else:
                    setattr(owner, name, previous)
            except Exception as e:
                failures.append('{}.{}: {}'.format(getattr(owner, '__name__', owner), name, e))
        if failures:
            raise RuntimeError('could not restore ' + '; '.join(failures))


_MISSING = object()


def _timed(recorder, key_of, function):
    def wrapper(*args, **kwargs):
        recorder.enter(key_of(*args, **kwargs))
        try:
            return function(*args, **kwargs)
        finally:
            recorder.leave()
    return wrapper


def _timed_generator(recorder, key_of, function):
    def wrapper(*args, **kwargs):
        key = key_of(*args, **kwargs)
        iterator = iter(function(*args, **kwargs))
        while True:
            recorder.enter(key)
            try:
                item = next(iterator)
            except StopIteration:
                return
            finally:
                recorder.leave()
            yield item
    return wrapper


def _install(recorder, patches):
    from autonomy import content_sets
    from event_testing.resolver import InteractionResolver, Resolver
    from event_testing.tests import CompoundTestList
    from filters.sim_filter_service import SimFilterService
    from interactions.aop import AffordanceObjectPair
    from interactions.base.interaction import Interaction
    from interactions.base.picker_interaction import SimPickerMixin
    from interactions.base.super_interaction import SuperInteraction
    from interactions.choices import ChoiceMenu
    from interactions.utils.content_score_mixin import ContentScoreMixin
    from objects.base_interactions import ProxyInteraction
    from server_commands import interaction_commands
    from sims.sim import Sim
    from sims4.utils import flexmethod

    test = AffordanceObjectPair.__dict__['test']
    patches.set(AffordanceObjectPair, 'test', _timed(recorder, lambda aop, *a, **k: ('test', _name(aop.affordance)), test))

    score = ContentScoreMixin.__dict__['get_content_score'].__func__
    patches.set(ContentScoreMixin, 'get_content_score', classmethod(_timed(recorder, lambda cls, *a, **k: ('score', _name(cls)), score)))

    for owner in (Interaction, SuperInteraction, ProxyInteraction):
        raw = owner.__dict__.get('potential_pie_menu_sub_interactions_gen')
        if not isinstance(raw, classmethod):
            continue
        patches.set(owner, 'potential_pie_menu_sub_interactions_gen', classmethod(_timed_generator(recorder, lambda cls, *a, **k: ('mixers', _name(cls)), raw.__func__)))

    call = Resolver.__dict__['__call__']
    patches.set(Resolver, '__call__', _timed(recorder, lambda resolver, test, *a, **k: ('test type', _test_name(test)), call))

    participants = InteractionResolver.__dict__['get_participants']
    patches.set(InteractionResolver, 'get_participants', _timed(recorder, lambda resolver, participant_type, *a, **k: ('participant', _label('InteractionResolver', participant_type)), participants))

    interaction_participants = Interaction.__dict__['get_participants'].__wrapped_method__

    def participant_key(cls, inst, participant_type=None, *args, **kwargs):
        return ('participant', _label('Interaction.get_participants', participant_type))
    patches.set(Interaction, 'get_participants', flexmethod(_timed(recorder, participant_key, interaction_participants)))

    picker = SimPickerMixin.__dict__['_get_valid_sim_choices_gen'].__wrapped_method__

    def picker_gen(cls, inst, target, context, *args, **kwargs):
        key = ('picker', _name(cls))
        counts = recorder.pickers[key[1]]
        counts['searches'] += 1
        iterator = picker(cls, inst, target, context, *args, **kwargs)
        while True:
            recorder.enter(key)
            recorder.picker_stack.append((counts, (inst if inst is not None else cls).sim_tests))
            try:
                item = next(iterator)
            except StopIteration:
                return
            finally:
                recorder.picker_stack.pop()
                recorder.leave()
            counts['found'] += 1
            yield item
    patches.set(SimPickerMixin, '_get_valid_sim_choices_gen', flexmethod(picker_gen))

    submit_filter = SimFilterService.__dict__['submit_filter']

    def counted_filter(*args, **kwargs):
        if recorder.picker_stack:
            recorder.picker_stack[-1][0]['candidates filtered'] += 1
        recorder.enter(('filter', 'submit_filter'))
        try:
            return submit_filter(*args, **kwargs)
        finally:
            recorder.leave()
    patches.set(SimFilterService, 'submit_filter', counted_filter)

    run_tests = CompoundTestList.__dict__['run_tests']

    def counted_run_tests(self, *args, **kwargs):
        if recorder.picker_stack and recorder.picker_stack[-1][1] is self:
            recorder.picker_stack[-1][0]['candidates tested'] += 1
        return run_tests(self, *args, **kwargs)
    patches.set(CompoundTestList, 'run_tests', counted_run_tests)

    for owner, name, label in ((ChoiceMenu, 'add_potential_aops', 'add_potential_aops'), (Sim, 'fill_choices_menu_with_si_state_aops', 'mixers of running interactions')):
        raw = owner.__dict__.get(name)
        if raw is not None:
            patches.set(owner, name, _timed(recorder, lambda *a, label=label, **k: ('phase', label), raw))
    raw = Sim.__dict__.get('potential_interactions')
    if raw is not None:
        patches.set(Sim, 'potential_interactions', _timed_generator(recorder, lambda *a, **k: ('phase', 'potential_interactions (Sim)'), raw))
    patches.set(interaction_commands, 'create_pie_menu_message', _timed(recorder, lambda *a, **k: ('phase', 'create_pie_menu_message'), interaction_commands.create_pie_menu_message))
    from interactions.base import super_interaction
    original_generate = content_sets.generate_content_set
    generate = _timed(recorder, lambda *a, **k: ('phase', 'generate_content_set'), original_generate)
    patches.set(content_sets, 'generate_content_set', generate)
    if super_interaction.__dict__.get('generate_content_set') is original_generate:
        patches.set(super_interaction, 'generate_content_set', generate)

    from interactions.base.picker_interaction import AutonomousSimPickerSuperInteraction, PickerSuperInteractionMixin
    for owner in (PickerSuperInteractionMixin, AutonomousSimPickerSuperInteraction):
        raw = owner.__dict__.get('_test')
        if raw is not None:
            patches.set(owner, '_test', classmethod(_timed(recorder, lambda cls, *a, **k: ('picker check', _name(cls)), raw.__func__)))


def _table(text, title, rows, columns, limit):
    text.write('\n{}\n'.format(title))
    text.write('  '.join(columns) + '\n')
    for row in rows[:limit]:
        text.write('  '.join(row) + '\n')


def _ms(seconds):
    return '{:9.1f}'.format(seconds * 1000)


def run(target, connection, build, mods_folder, states):
    recorder = _Recorder()
    started = _perf()
    choices = build(target, connection)
    plain = _perf() - started

    from codebleu_loose_ends.fixes import content_scoring, dynasty_rules, picked_sim_lookup, pie_menu_filters
    before = {'memo': dict(pie_menu_filters.stats), 'scoring': dict(content_scoring.stats), 'picked': dict(picked_sim_lookup.stats), 'dynasty': dict(dynasty_rules.stats)}
    patches = _Patches()
    try:
        _install(recorder, patches)
        started = _perf()
        build(target, connection)
        instrumented = _perf() - started
    finally:
        patches.restore()
    after = {'memo': pie_menu_filters.stats, 'scoring': content_scoring.stats, 'picked': picked_sim_lookup.stats, 'dynasty': dynasty_rules.stats}
    deltas = {name: {key: after[name][key] - value for key, value in values.items()} for name, values in before.items()}

    text = io.StringIO()
    text.write('Loose Ends pie menu anatomy\nTarget: {} ({})\nChoices: {}\nBuild without instruments: {:.4f} s\nBuild with instruments: {:.4f} s\n'.format(target, target.id, choices, plain, instrumented))
    text.write('Fixes: {}\n'.format(', '.join('{} {}'.format(key, state) for key, state in states)))
    text.write('During the instrumented build: {}\n'.format('; '.join('{} {}'.format(name, values) for name, values in deltas.items())))
    text.write('Times are milliseconds with instruments. "Own" excludes recorded calls inside; "total" includes them.\n')

    kinds = collections.defaultdict(float)
    for (kind, _), seconds in recorder.exclusive.items():
        kinds[kind] += seconds
    _table(text, 'Own time by kind', sorted(([_ms(seconds), kind] for kind, seconds in kinds.items()), key=lambda row: -float(row[0])), ['     own', 'kind'], 50)

    def ranked(kind, by_total=True, limit=60):
        source = recorder.inclusive if by_total else recorder.exclusive
        rows = [(source[key], key) for key in recorder.counts if key[0] == kind]
        rows.sort(key=lambda row: -row[0])
        return [[_ms(recorder.inclusive[key]), _ms(recorder.exclusive[key]), '{:7d}'.format(recorder.counts[key]), key[1]] for _, key in rows[:limit]]

    columns = ['   total', '     own', '  calls', 'name']
    _table(text, 'Phases', ranked('phase'), columns, 20)
    _table(text, 'Interactions by test time (aop.test, including pickers and nested tests)', ranked('test'), columns, 80)
    _table(text, 'Interactions by content scoring time', ranked('score'), columns, 40)
    _table(text, 'Interactions by mixer (sub-interaction) generation time', ranked('mixers'), columns, 40)
    _table(text, 'Test types by own time (resolving participants is listed separately)', ranked('test type', by_total=False), columns, 50)
    _table(text, 'Participant lookups by own time', ranked('participant', by_total=False), columns, 30)

    rows = []
    for key in recorder.counts:
        if key[0] != 'picker':
            continue
        counts = recorder.pickers[key[1]]
        rows.append((recorder.inclusive[key], [_ms(recorder.inclusive[key]), '{:8d}'.format(counts['searches']), '{:9d}'.format(counts['candidates filtered']),
            '{:8d}'.format(counts['candidates tested']), '{:6d}'.format(counts['found']), key[1]]))
    rows.sort(key=lambda row: -row[0])
    _table(text, 'Sim pickers by search time', [row for _, row in rows], ['   total', 'searches', ' filtered', '  tested', ' found', 'picker'], 60)

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    path = os.path.join(mods_folder, 'LooseEnds_anatomy_{}.txt'.format(stamp))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.getvalue())
    return choices, plain, instrumented, path
