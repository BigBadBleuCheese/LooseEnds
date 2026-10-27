"""looseends.profile_autonomy: full autonomy for one Sim, timed plain, then counted, then under the profiler. Nothing is pushed."""

import collections
import time

TAG_CHECK_STAGES = ('_satisfies_desire',)


class _Counts:

    def __init__(self):
        self.passes = 0
        self.objects = 0
        self.object_seconds = 0.0
        self.aops = 0
        self.aop_seconds = 0.0
        self.aops_by_object = collections.Counter()
        self.stages = collections.Counter()
        self.tag_drops_by_affordance = collections.Counter()


def _name(thing):
    return getattr(thing, '__name__', None) or type(thing).__name__


def _request(sim):
    from autonomy.autonomy_modes import FullAutonomy
    from autonomy.autonomy_request import AutonomyRequest
    return AutonomyRequest(sim, autonomy_mode=FullAutonomy, skipped_static_commodities=sim.autonomy_component.standard_static_commodity_skip_set, limited_autonomy_allowed=False)


def _instrument(request, counts):
    mode = request.autonomy_mode
    objects_to_score_gen = request.objects_to_score_gen
    get_potential_interactions = mode._get_potential_interactions

    def counted_objects_to_score_gen(*args, **kwargs):
        started = time.perf_counter()
        objects = list(objects_to_score_gen(*args, **kwargs))
        counts.object_seconds += time.perf_counter() - started
        counts.passes += 1
        counts.objects += len(objects)
        return iter(objects)

    def counted_get_potential_interactions(obj):
        started = time.perf_counter()
        aops = get_potential_interactions(obj)
        counts.aop_seconds += time.perf_counter() - started
        counts.aops += len(aops)
        counts.aops_by_object[_name(obj)] += len(aops)
        return aops

    def record_test_result(aop, stage, result):
        counts.stages[stage] += 1
        if stage in TAG_CHECK_STAGES and aop is not None:
            counts.tag_drops_by_affordance[_name(aop.affordance)] += 1

    request.objects_to_score_gen = counted_objects_to_score_gen
    mode._get_potential_interactions = counted_get_potential_interactions
    request.record_test_result = record_test_result


def _run(request):
    import caches
    import services
    caches.clear_all_caches()
    selected = None
    try:
        selected = services.autonomy_service().find_best_action(request, archive_if_enabled=False)
        return 'nothing' if selected is None else _name(selected.affordance)
    finally:
        request.valid = False
        if selected is not None:
            selected.invalidate()


def _timed(sim, counts=None):
    request = _request(sim)
    if counts is not None:
        _instrument(request, counts)
    started = time.perf_counter()
    chosen = _run(request)
    return time.perf_counter() - started, chosen


def _top(counter, count=25):
    return '\n'.join('  {:>7}  {}'.format(n, name) for name, n in counter.most_common(count)) or '  (none)'


def run(sim, runs, make_profiler, write_profile):
    from autonomy.autonomy_modes import FullAutonomy
    test = FullAutonomy.test(sim)

    plain = [_timed(sim) for _ in range(runs)]
    plain_seconds = sorted(seconds for seconds, _ in plain)
    median = plain_seconds[len(plain_seconds) // 2]

    counts = _Counts()
    counted_seconds, counted_chosen = _timed(sim, counts)

    profiler, kind = make_profiler()
    request = _request(sim)
    started = time.perf_counter()
    profiled_chosen = profiler.runcall(_run, request)
    profiled_seconds = time.perf_counter() - started
    profiler.create_stats()

    tag_drops = sum(counts.stages[stage] for stage in TAG_CHECK_STAGES)
    share = tag_drops / counts.aops if counts.aops else 0.0
    header = '\n'.join((
        'Loose Ends autonomy profile',
        'Sim: {} ({})'.format(sim, sim.id),
        'FullAutonomy.test: {}'.format(test),
        'Plain runs ({}): {} s; median {:.4f} s'.format(runs, ', '.join('{:.4f}'.format(s) for s in plain_seconds), median),
        'Chosen (not pushed): {}'.format(', '.join(chosen for _, chosen in plain)),
        'Counted run: {:.4f} s, chose {}'.format(counted_seconds, counted_chosen),
        'Profiled run: {:.4f} s with {}, chose {}'.format(profiled_seconds, kind, profiled_chosen),
        '',
        'Counted run:',
        '  motive passes: {}'.format(counts.passes),
        '  objects to score: {} ({:.4f} s choosing them)'.format(counts.objects, counts.object_seconds),
        '  interactions built: {} ({:.4f} s building them)'.format(counts.aops, counts.aop_seconds),
        '  dropped by the motive tag check: {} ({:.0%} of built)'.format(tag_drops, share),
        '  by stage:',
        _top(counts.stages, 50),
        '',
        'Interactions built, by object:',
        _top(counts.aops_by_object),
        '',
        'Dropped by the motive tag check, by affordance:',
        _top(counts.tag_drops_by_affordance)))
    base = write_profile('LooseEnds_autonomy_profile', header, profiler)
    summary = 'median {:.4f} s over {} plain runs ({:.4f} s profiled); {} passes, {} objects, {} interactions built, {} ({:.0%}) dropped by the motive tag check ({:.4f} s building interactions)'.format(
        median, runs, profiled_seconds, counts.passes, counts.objects, counts.aops, tag_drops, share, counts.aop_seconds)
    return summary, base
