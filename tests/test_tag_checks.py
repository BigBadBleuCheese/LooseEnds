"""
Runs the game's real bytecode for GameObject.has_any_tag, GameObject.has_tag and Definition.has_build_buy_tag against
randomized objects and tag filters, and checks that the tag_checks fix gives exactly the vanilla answers, then times both.
"""

import array
import enum
import os
import random
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]

import ea
from codebleu_loose_ends import guard
from codebleu_loose_ends.fixes import tag_checks as module

Tag = enum.IntEnum('Tag', [('TAG_{}'.format(i), 1000 + i) for i in range(600)])
ALL_TAGS = list(Tag)


def build_classes():
    has_build_buy_tag = ea.function('objects.definition', 'Definition.has_build_buy_tag', {})
    has_tag = ea.function('objects.game_object', 'GameObject.has_tag', {})
    has_any_tag = ea.function('objects.game_object', 'GameObject.has_any_tag', {})

    class VanillaDefinition:
        def __init__(self, tags):
            self.build_buy_tags = tags

    VanillaDefinition.has_build_buy_tag = has_build_buy_tag

    class VanillaObject:
        def __init__(self, definition, local=None, persisted=None):
            self.definition, self._local_tags, self._persisted_tags = definition, local, persisted

    VanillaObject.has_tag = has_tag
    VanillaObject.has_any_tag = has_any_tag

    module._game.clear()
    module._tag_sets.clear()
    module.stats.update({key: 0 for key in module.stats})
    module._game['has_tag'] = has_tag

    class FixedDefinition(VanillaDefinition):
        pass

    FixedDefinition.has_build_buy_tag = module._make_has_build_buy_tag(has_build_buy_tag)

    class FixedObject(VanillaObject):
        pass

    FixedObject.has_any_tag = module._make_has_any_tag(has_any_tag)
    module.FIX.state = guard.ACTIVE
    return VanillaDefinition, VanillaObject, FixedDefinition, FixedObject


def outcome(call, *args):
    try:
        return 'result', call(*args)
    except Exception as e:
        return 'raised', type(e)


def random_tags(rng, low, high):
    return array.array('L', (int(tag) for tag in rng.sample(ALL_TAGS, rng.randint(low, high))))


def random_owned(rng):
    kind = rng.random()
    if kind < 0.6:
        return None
    if kind < 0.7:
        return set()
    if kind < 0.8:
        return set(rng.sample(ALL_TAGS, rng.randint(1, 4)))
    if kind < 0.9:
        return frozenset(rng.sample(ALL_TAGS, rng.randint(1, 4)))
    return tuple(rng.sample(ALL_TAGS, rng.randint(1, 4)))


def random_filter(rng):
    tags = rng.sample(ALL_TAGS, rng.choice((1, 3, 12, 77, 150)))
    kind = rng.randrange(5)
    if kind == 0:
        return frozenset(tags)
    if kind == 1:
        return set(tags)
    if kind == 2:
        return tuple(tags)
    if kind == 3:
        return list(tags)
    return (tag for tag in tags)


class TagCheckTests(unittest.TestCase):

    def pair(self, rng, classes):
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        tags = random_tags(rng, 0, 40)
        local, persisted = random_owned(rng), random_owned(rng)
        return VanillaObject(VanillaDefinition(tags), local, persisted), FixedObject(FixedDefinition(tags), local, persisted)

    def test_matches_vanilla_on_random_objects_and_filters(self):
        rng = random.Random(5)
        classes = build_classes()
        seen = set()
        for _ in range(400):
            vanilla, fixed = self.pair(rng, classes)
            for _ in range(15):
                state = rng.getstate()
                expected = outcome(vanilla.has_any_tag, random_filter(rng))
                rng.setstate(state)
                self.assertEqual(outcome(fixed.has_any_tag, random_filter(rng)), expected)
                seen.add(expected)
                tag = rng.choice(ALL_TAGS)
                self.assertEqual(outcome(fixed.has_tag, tag), outcome(vanilla.has_tag, tag))
                many = rng.sample(ALL_TAGS, rng.randint(0, 5))
                self.assertEqual(outcome(fixed.definition.has_build_buy_tag, *many), outcome(vanilla.definition.has_build_buy_tag, *many))
        self.assertEqual(seen, {('result', True), ('result', False)})
        self.assertGreater(module.stats['checks'], 4000)
        self.assertGreater(module.stats['passed through'], 500)

    def test_empty_filters_and_plain_int_tags(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        tags = array.array('L', (int(Tag.TAG_1), int(Tag.TAG_2)))
        vanilla, fixed = VanillaObject(VanillaDefinition(tags)), FixedObject(FixedDefinition(tags))
        for tag_filter in ((), frozenset(), [], (int(Tag.TAG_2),), {Tag.TAG_1}, (Tag.TAG_3,)):
            self.assertEqual(outcome(fixed.has_any_tag, tag_filter), outcome(vanilla.has_any_tag, tag_filter))

    def test_iterators_are_read_the_ea_way(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        tags = array.array('L', (int(Tag.TAG_1),))
        vanilla, fixed = VanillaObject(VanillaDefinition(tags)), FixedObject(FixedDefinition(tags))

        def match_then_explode():
            yield Tag.TAG_1
            raise ValueError('read past the match')

        def endless_after_match():
            yield Tag.TAG_1
            while True:
                yield Tag.TAG_2

        for make in (match_then_explode, endless_after_match):
            self.assertEqual(outcome(fixed.has_any_tag, make()), outcome(vanilla.has_any_tag, make()))
        self.assertEqual(module.stats['passed through'], 2)
        self.assertEqual(module.FIX.state, guard.ACTIVE)

    def test_tags_replaced_or_appended_are_noticed(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        definition = FixedDefinition(array.array('L', (int(Tag.TAG_1),)))
        fixed = FixedObject(definition)
        self.assertEqual((fixed.has_any_tag({Tag.TAG_1}), fixed.has_any_tag({Tag.TAG_2})), (True, False))
        definition.build_buy_tags.append(int(Tag.TAG_2))
        self.assertTrue(fixed.has_any_tag({Tag.TAG_2}))
        definition.build_buy_tags = array.array('L', (int(Tag.TAG_3),))
        self.assertEqual((fixed.has_any_tag({Tag.TAG_1}), fixed.has_any_tag({Tag.TAG_3})), (False, True))
        definition.build_buy_tags = (int(Tag.TAG_4),)
        self.assertTrue(definition.has_build_buy_tag(Tag.TAG_4))

    def test_shared_tag_arrays_are_stored_once(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        shared = array.array('L', (int(Tag.TAG_1), int(Tag.TAG_2)))
        for _ in range(50):
            FixedObject(FixedDefinition(shared)).has_any_tag({Tag.TAG_9})
        self.assertEqual(len(module._tag_sets), 1)

    def test_other_answers_and_odd_filters_pass_through(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        tags = array.array('L', (int(Tag.TAG_1),))

        class CustomObject(FixedObject):
            def has_tag(self, tag):
                return tag == Tag.TAG_7

        class CustomDefinition(FixedDefinition):
            def has_build_buy_tag(self, *tags):
                return Tag.TAG_8 in tags

        self.assertTrue(CustomObject(FixedDefinition(tags)).has_any_tag({Tag.TAG_7}))
        self.assertTrue(FixedObject(CustomDefinition(tags)).has_any_tag({Tag.TAG_8}))
        self.assertFalse(FixedObject(CustomDefinition(tags)).has_any_tag({Tag.TAG_1}))
        self.assertEqual(module.stats['passed through'], 3)

        vanilla, fixed = VanillaObject(VanillaDefinition(tags)), FixedObject(FixedDefinition(tags))
        for tag_filter in ([Tag.TAG_1, []], [[], Tag.TAG_1], [Tag.TAG_2, []], None, 5):
            self.assertEqual(outcome(fixed.has_any_tag, tag_filter), outcome(vanilla.has_any_tag, tag_filter))
        for args in (([],), (Tag.TAG_1, [])):
            self.assertEqual(outcome(fixed.definition.has_build_buy_tag, *args), outcome(vanilla.definition.has_build_buy_tag, *args))

        missing = FixedObject(None, local={Tag.TAG_5})
        self.assertEqual(outcome(missing.has_any_tag, {Tag.TAG_5}), outcome(VanillaObject(None, local={Tag.TAG_5}).has_any_tag, {Tag.TAG_5}))
        self.assertTrue(missing.has_any_tag({Tag.TAG_5}))
        self.assertEqual(module.FIX.state, guard.ACTIVE)

    def test_inactive_fix_is_vanilla_and_own_errors_switch_it_off(self):
        classes = build_classes()
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = classes
        tags = array.array('L', (int(Tag.TAG_1),))
        module.FIX.state = guard.DISABLED
        fixed = FixedObject(FixedDefinition(tags))
        self.assertTrue(fixed.has_any_tag({Tag.TAG_1}))
        self.assertEqual(module.stats['checks'], 0)

        class ExplodingTags(tuple):
            def __len__(self):
                raise RuntimeError('mod tags exploded')

        module.FIX.state = guard.ACTIVE
        exploding = FixedObject(FixedDefinition(ExplodingTags((int(Tag.TAG_1),))))
        self.assertTrue(exploding.has_any_tag({Tag.TAG_1}))
        self.assertEqual(module.FIX.state, guard.FAULTED)
        self.assertFalse(fixed.has_any_tag({Tag.TAG_2}))

    def test_speed(self):
        rng = random.Random(9)
        VanillaDefinition, VanillaObject, FixedDefinition, FixedObject = build_classes()
        arrays = [random_tags(rng, 5, 40) for _ in range(120)]
        vanilla_objects, fixed_objects = [], []
        for _ in range(450):
            tags, local = rng.choice(arrays), random_owned(rng)
            vanilla_objects.append(VanillaObject(VanillaDefinition(tags), local))
            fixed_objects.append(FixedObject(FixedDefinition(tags), local))
        filters = [frozenset(rng.sample(ALL_TAGS, rng.choice((3, 12, 77, 77, 77, 150)))) for _ in range(60)]

        def run(objects):
            started = time.perf_counter()
            hits = 0
            for tag_filter in filters:
                for obj in objects:
                    hits += obj.has_any_tag(tag_filter)
            return time.perf_counter() - started, hits

        vanilla, vanilla_hits = run(vanilla_objects)
        cold, cold_hits = run(fixed_objects)
        warm, warm_hits = run(fixed_objects)
        self.assertEqual((cold_hits, warm_hits), (vanilla_hits, vanilla_hits))
        checks = len(filters) * len(fixed_objects)
        print('\ntag checks, {} filters x {} objects ({} has_any_tag calls): vanilla {:.1f} ms, fix cold {:.1f} ms, fix warm {:.1f} ms ({:.3f}x)'.format(
            len(filters), len(fixed_objects), checks, vanilla * 1000, cold * 1000, warm * 1000, warm / vanilla))


if __name__ == '__main__':
    unittest.main()
