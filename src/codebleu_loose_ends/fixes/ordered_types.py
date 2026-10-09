"""
InstanceManager.get_ordered_types, remembering each answer once all tuning is loaded.

EA's version scans every instance in the manager on every call. Some mods call it from per-item hooks; Lot 51 Core
Library's tested pie menu categories call it for every pie menu entry, scanning all ~13,000 snippets each time. Once a
manager reports all instances loaded its contents no longer change in a release game, so the answer for a given
only_subclasses_of is reused while the manager's instance count is unchanged. Callers still get a new list each time.
"""

from codebleu_loose_ends.guard import Fix, Hook

_cache = {}


def _make(original):
    def get_ordered_types(self, only_subclasses_of=None):
        if not FIX.active or not self.all_instances_loaded:
            return original(self, only_subclasses_of)
        try:
            key = (id(self), only_subclasses_of)
            entry = _cache.get(key)
        except TypeError:
            return original(self, only_subclasses_of)
        count = len(self._tuned_classes)
        if entry is None or entry[0] != count:
            entry = (count, tuple(original(self, only_subclasses_of)))
            _cache[key] = entry
        return list(entry[1])
    get_ordered_types.__wrapped__ = original
    return get_ordered_types


def _build():
    from sims4.tuning.instance_manager import InstanceManager
    return [Hook(InstanceManager, 'get_ordered_types', 0xf8538d2118da745c, _make)], []


FIX = Fix('ordered_types', 'Faster snippet lookups for pie menus', _build)
