"""
Prevents orphaned hidden mood buffs ("far too Tense/Uncomfortable" while the mood panel is positive).

BuffComponent._update_current_mood stores the new hidden mood buff's handle from add_buff, but add_buff runs the buff's
loot synchronously and that loot can change mood again, re-entering _update_current_mood. The nested call stores its
handle, then the outer call overwrites it, so the nested buff is never removed until the Sim is rebuilt.

While a mood buff is being added without updating mood (only _update_current_mood does that), nested mood updates are
deferred and rerun after the outer update has stored its handle, reproducing vanilla's sequential remove-then-add order.
"""

from codebleu_loose_ends.guard import Fix, Hook, logger

MAXIMUM_DEFERRED_MOOD_UPDATES = 16


def _is_untracked_mood_buff_add(buff_type, args, kwargs):
    update_mood = args[1] if len(args) > 1 else kwargs.get('update_mood', True)
    return not update_mood and getattr(buff_type, 'is_mood_buff', False)


def _make_add_buff(original):
    def add_buff(self, buff_type, *args, **kwargs):
        if not FIX.active or not _is_untracked_mood_buff_add(buff_type, args, kwargs):
            return original(self, buff_type, *args, **kwargs)
        self._loose_ends_mood_buff_adds += 1
        try:
            return original(self, buff_type, *args, **kwargs)
        finally:
            self._loose_ends_mood_buff_adds -= 1
    add_buff.__wrapped__ = original
    return add_buff


def _make_update_current_mood(original):
    def _update_current_mood(self):
        if not FIX.active:
            return original(self)
        if self._loose_ends_mood_buff_adds:
            self._loose_ends_mood_update_deferred = True
            return
        original(self)
        for _ in range(MAXIMUM_DEFERRED_MOOD_UPDATES):
            if not self._loose_ends_mood_update_deferred:
                return
            self._loose_ends_mood_update_deferred = False
            original(self)
        if self._loose_ends_mood_update_deferred:
            self._loose_ends_mood_update_deferred = False
            logger.error('Mood for {} kept changing while its mood buff was being added; gave up after {} deferred updates.', self.owner, MAXIMUM_DEFERRED_MOOD_UPDATES)
    _update_current_mood.__wrapped__ = original
    return _update_current_mood


def _make_counter(value):
    return lambda _: value


def _build():
    from objects.components.buff_component import BuffComponent
    from codebleu_loose_ends.guard import ABSENT
    return [
        Hook(BuffComponent, '_loose_ends_mood_buff_adds', ABSENT, _make_counter(0)),
        Hook(BuffComponent, '_loose_ends_mood_update_deferred', ABSENT, _make_counter(False)),
        Hook(BuffComponent, 'add_buff', 0x02fb8ca179142ca3, _make_add_buff),
        Hook(BuffComponent, '_update_current_mood', 0x771628866f763664, _make_update_current_mood)], []


FIX = Fix('phantom_mood', 'Phantom "too Tense/Uncomfortable" mood fix', _build)
