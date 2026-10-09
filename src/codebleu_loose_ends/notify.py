"""
Tells the player which fixes are switched off and why: once per session on first entering Live mode, and again later
only if a fix switches itself off mid-session.

The hook on Zone.on_loading_screen_animation_finished is deliberately unchecked: it always runs the game's code first
and only reads state afterwards, so it is safe on any game version, and it is what reports the other fixes being off.
"""

import functools
import sys

import services
import sims4.log

from codebleu_loose_ends import guard

logger = sims4.log.Logger('LooseEnds')

TITLE = 'Loose Ends'

_state = {'live': False, 'reported': set()}


def _show(text):
    from sims4.localization import LocalizationHelperTuning
    from ui.ui_dialog_notification import UiDialogNotification
    title = LocalizationHelperTuning.get_raw_text(TITLE)
    body = LocalizationHelperTuning.get_raw_text(text)
    notification = UiDialogNotification.TunableFactory().default(services.active_sim_info(), title=lambda *_, **__: title, text=lambda *_, **__: body)
    notification.show_dialog()


def _paragraph(heading, lines):
    return heading + '\n' + '\n'.join('• ' + line for line in lines) if lines else None


def compose(fixes, old_files):
    """The notification text for the given switched-off fixes and leftover predecessor files, or '' if nothing to say."""
    paragraphs = (
        _paragraph('This version of the game changed code these fixes depend on, so they are switched off to keep your game safe. EA may have fixed some of them. Check for a Loose Ends update:',
            [fix.title for fix in fixes if fix.state == guard.GAME_CHANGED]),
        _paragraph('These fixes are off because another mod changes the same game code:',
            ['{} ({})'.format(fix.title, fix.blocker) for fix in fixes if fix.state == guard.OTHER_MOD and fix.blocker not in guard.PREDECESSORS]),
        _paragraph('These fixes hit an error and switched themselves off until you restart the game:',
            [fix.title for fix in fixes if fix.state == guard.FAULTED]),
        _paragraph('Loose Ends already includes these older mods. Remove them from your Mods folder:', old_files))
    return '\n\n'.join(paragraph for paragraph in paragraphs if paragraph)


def _report(fixes):
    fixes = [fix for fix in fixes if not fix.active and fix.state != guard.DISABLED and fix.key not in _state['reported']]
    old = [(module, file_name) for module, file_name in guard.PREDECESSORS.items() if module in sys.modules and module not in _state['reported']]
    text = compose(fixes, [file_name for _, file_name in old])
    if not text:
        return
    _show(text)
    _state['reported'].update(fix.key for fix in fixes)
    _state['reported'].update(module for module, _ in old)


def _on_live_mode():
    _state['live'] = True
    _report(guard.fixes)


def _on_fault(fix):
    if _state['live']:
        try:
            _report([fix])
        except Exception:
            logger.exception('Loose Ends: could not show the fault notification')


def install():
    from zone import Zone
    original = Zone.__dict__.get('on_loading_screen_animation_finished')
    if original is None:
        logger.error('Loose Ends: Zone.on_loading_screen_animation_finished is gone; switched-off fixes only show in looseends.status')
        return

    @functools.wraps(original)
    def on_loading_screen_animation_finished(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            _on_live_mode()
        except Exception:
            logger.exception('Loose Ends: could not report switched-off fixes')
        return result

    Zone.on_loading_screen_animation_finished = on_loading_screen_animation_finished
    guard.fault_listeners.append(_on_fault)
