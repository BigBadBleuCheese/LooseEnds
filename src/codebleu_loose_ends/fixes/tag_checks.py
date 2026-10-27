"""
Answers "does this object have any of these tags?" with one set comparison instead of one lookup per tag.

Autonomy asks, for every object it scores, which interactions the Sim's traits and moods add to it. Most of those carry
an object filter of tags, checked with GameObject.has_any_tag. EA's version calls has_tag for each tag in the filter,
and has_tag calls Definition.has_build_buy_tag, which builds a set of that one tag and a new set of all of the object's
build/buy tags, then intersects them. Filters average dozens of tags, so one check rebuilds the object's tag set dozens
of times; a single autonomy decision made about two million of these calls in measured saves.

Each distinct build/buy tag array gets one frozenset, kept while the definition still holds that same array at the same
length (EA never edits these arrays in place; it assigns new ones). has_any_tag compares the filter against the object's local, persisted and build/buy tags in one step each, which
is exactly EA's answer for hashable tags. Objects whose class or definition answers has_tag or has_build_buy_tag some
other way, filters that aren't a set, frozenset, tuple or list (such as generators, which EA stops reading at the first
match), and filters that can't be compared as sets are asked the EA way.
"""

from codebleu_loose_ends.guard import Fix, Hook, Requirement

MAX_CACHED = 50000
_game = {}
_tag_sets = {}
stats = {'checks': 0, 'passed through': 0}


def _definition_tags(definition):
    raw = definition.build_buy_tags
    entry = _tag_sets.get(id(raw))
    if entry is None or entry[0] is not raw or entry[1] != len(raw):
        if len(_tag_sets) >= MAX_CACHED:
            _tag_sets.clear()
        entry = (raw, len(raw), frozenset(raw))
        _tag_sets[id(raw)] = entry
    return entry[2]


def _overlaps(owned, tags):
    if type(owned) is set or type(owned) is frozenset:
        return not owned.isdisjoint(tags)
    return any(tag in owned for tag in tags)


def _make_has_build_buy_tag(original):
    def has_build_buy_tag(self, *tags):
        if not FIX.active:
            return original(self, *tags)
        try:
            return not _definition_tags(self).isdisjoint(frozenset(tags))
        except (TypeError, AttributeError):
            return original(self, *tags)
        except Exception as e:
            FIX.fault(e)
            return original(self, *tags)
    has_build_buy_tag.__wrapped__ = original
    _game['has_build_buy_tag'] = has_build_buy_tag
    return has_build_buy_tag


def _make_has_any_tag(original):
    ea_has_tag = _game['has_tag']
    fast_has_build_buy_tag = _game['has_build_buy_tag']

    def has_any_tag(self, tags):
        if not FIX.active:
            return original(self, tags)
        kind = type(tags)
        if kind is not frozenset and kind is not set and kind is not tuple and kind is not list:
            stats['passed through'] += 1
            return original(self, tags)
        try:
            definition = self.definition
            if type(self).has_tag is not ea_has_tag or type(definition).has_build_buy_tag is not fast_has_build_buy_tag:
                stats['passed through'] += 1
                return original(self, tags)
            stats['checks'] += 1
            local = self._local_tags
            if local and _overlaps(local, tags):
                return True
            persisted = self._persisted_tags
            if persisted and _overlaps(persisted, tags):
                return True
            return not _definition_tags(definition).isdisjoint(tags)
        except (TypeError, AttributeError):
            stats['passed through'] += 1
            return original(self, tags)
        except Exception as e:
            FIX.fault(e)
            return original(self, tags)
    has_any_tag.__wrapped__ = original
    return has_any_tag


def _build():
    from objects.definition import Definition
    from objects.game_object import GameObject
    _game['has_tag'] = GameObject.__dict__.get('has_tag')
    return [
        Hook(Definition, 'has_build_buy_tag', 0xe62628fa3ae57f88, _make_has_build_buy_tag, stack_on_mods=False),
        Hook(GameObject, 'has_any_tag', 0x5ca230f0a7ac08ad, _make_has_any_tag, stack_on_mods=False)], [
        Requirement(GameObject, 'has_tag', 0xb276852d1d8200f0, stack_on_mods=False)]


FIX = Fix('tag_checks', 'Faster object tag checks for autonomy and interaction filters', _build, restore_when_disabled=True)
