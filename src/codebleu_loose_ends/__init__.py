"""Loose Ends: fixes for EA game state that is left dangling and makes the game slower or misbehave."""

import importlib

from codebleu_loose_ends import guard

FIX_MODULES = (
    'ordered_types',
    'pie_menu_filters',
    'phantom_mood',
    'autonomous_sim_pickers',
    'content_scoring',
    'picked_sim_lookup',
    'dynasty_rules',
    'social_picker_cooldown',
    'leave_lot',
    'travel_event_subscriptions',
    'situation_event_leaks')

for _name in FIX_MODULES:
    try:
        importlib.import_module('codebleu_loose_ends.fixes.' + _name)
    except Exception:
        guard.logger.exception('Loose Ends: could not load fix module {}', _name)

guard.install_all()

try:
    from codebleu_loose_ends import notify
    notify.install()
except Exception:
    guard.logger.exception('Loose Ends: could not install the notifier')

try:
    from codebleu_loose_ends import commands
except Exception:
    guard.logger.exception('Loose Ends: could not register cheat commands')
