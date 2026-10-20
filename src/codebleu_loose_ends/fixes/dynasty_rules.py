"""
Checks pie menu entries against the active Sim's dynasty rules without rebuilding every rule's interaction list.

While building the pie menu message, EA asks the Sim's dynasty, for every entry, whether its values encourage or
discourage that interaction (the aligned/misaligned icon). For each entry it walks every aligned rule, then every
misaligned rule, and for each rule creates the rule's club interaction group and searches it with "in". The group has no
fast membership test, so every search rebuilds a set of all of the group's interactions and walks it. With a few dozen
rules and a few hundred entries, that is over a million steps per menu.

The dynasty's rules are gathered once, and every aligned rule's interactions and every misaligned rule's interactions are
each merged into one set; an entry is then encouraged if its interaction type is in the aligned set, otherwise
discouraged if it is in the misaligned set, as EA decides. The sets are rebuilt whenever the dynasty's rules, their groups or the groups' lists change.
A rule whose group isn't EA's own kind is asked the EA way.
"""

import weakref

from codebleu_loose_ends.guard import Fix, Hook, Requirement, unpatched

_game = {}
_entries = weakref.WeakKeyDictionary()
stats = {'fast': 0, 'rebuilt': 0, 'passed through': 0}


def _same(left, right):
    return len(left) == len(right) and all(a is b for a, b in zip(left, right))


def _merged(rules):
    """One set of every interaction the rules' groups contain, or None if any group isn't a plain EA club interaction group."""
    group_iter = _game['group_iter']
    members = set()
    for rule in rules:
        group = rule.action
        if not isinstance(group, type) or not issubclass(group, _game['ClubInteractionGroup']) or getattr(group, '__iter__', None) is not group_iter or \
                getattr(group, '__contains__', None) is not None:
            return None
        members.update(group.affordances)
        for affordance_list in group.affordance_lists:
            members.update(affordance_list)
    return frozenset(members)


def _intact():
    return all(unpatched(owner.__dict__.get(name)) is function for owner, name, function in _game['relied_on'])


def _contents(rules):
    """Every rule with the group and group contents it had, compared by identity to notice rules or groups changing."""
    contents = []
    for rule in rules:
        group = rule.action
        lists = tuple(getattr(group, 'affordance_lists', ()))
        contents.extend((rule, group, getattr(group, 'affordances', None)))
        contents.extend(lists)
        contents.extend(getattr(affordance_list, 'value', affordance_list) for affordance_list in lists)
    return tuple(contents)


def _sets_for(dynasty):
    aligned = _contents(dynasty.activities_gen(True))
    misaligned = _contents(dynasty.activities_gen(False))
    entry = _entries.get(dynasty)
    if entry is not None and _same(entry[0], aligned) and _same(entry[1], misaligned):
        return entry[2], entry[3]
    if not _intact():
        return None, None
    entry = (aligned, misaligned, _merged(dynasty.activities_gen(True)), _merged(dynasty.activities_gen(False)))
    _entries[dynasty] = entry
    stats['rebuilt'] += 1
    return entry[2], entry[3]


def _make(original):
    def is_interaction_encouraged_by_dynasty_rules(self, interaction):
        if not FIX.active:
            return original(self, interaction)
        interaction_type = interaction.affordance.get_interaction_type()
        try:
            encouraged, discouraged = _sets_for(self)
            if encouraged is None or discouraged is None:
                stats['passed through'] += 1
                return original(self, interaction)
            in_encouraged = interaction_type in encouraged
            in_discouraged = not in_encouraged and interaction_type in discouraged
        except TypeError:
            stats['passed through'] += 1
            return original(self, interaction)
        except Exception as e:
            FIX.fault(e)
            return original(self, interaction)
        stats['fast'] += 1
        status = _game['ClubRuleEncouragementStatus']
        if in_encouraged:
            return status.ENCOURAGED
        if in_discouraged:
            return status.DISCOURAGED
        return status.NO_EFFECT
    is_interaction_encouraged_by_dynasty_rules.__wrapped__ = original
    return is_interaction_encouraged_by_dynasty_rules


def _build():
    from clubs.club_tuning import ClubInteractionGroup, ClubRuleEncouragementStatus
    from dynasty.dynasty import Dynasty
    _game.update(ClubInteractionGroup=ClubInteractionGroup, ClubRuleEncouragementStatus=ClubRuleEncouragementStatus, group_iter=ClubInteractionGroup.__dict__.get('__iter__'))
    _game['relied_on'] = ((ClubInteractionGroup, '__iter__', ClubInteractionGroup.__dict__.get('__iter__')), (Dynasty, 'activities_gen', Dynasty.__dict__.get('activities_gen')))
    return [
        Hook(Dynasty, 'is_interaction_encouraged_by_dynasty_rules', 0x0dea5a1fc2873b71, _make, stack_on_mods=False)], [
        Requirement(Dynasty, 'activities_gen', 0x00419b7baeb12f7c, stack_on_mods=False),
        Requirement(ClubInteractionGroup, '__iter__', 0x2e63da37f1d9d59d, stack_on_mods=False)]


FIX = Fix('dynasty_rules', 'Check pie menu entries against dynasty rules without rebuilding every rule', _build)
