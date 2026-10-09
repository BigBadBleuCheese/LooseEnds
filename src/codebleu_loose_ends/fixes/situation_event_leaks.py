"""
Ended small business employee and restaurant chef situations stop receiving game events.

SmallBusinessEmployeeSituation.__init__ subscribes to InteractionComplete directly instead of through the situation's
tracked registrations, so SituationComplex._destroy never unsubscribes it. Every shift leaves a dead situation behind
that still handles every InteractionComplete on the lot, and still applies its end-of-shift loot (friendship loss and a
sentiment) when that employee is later sent home early: once per earlier shift this zone session. ChefSituation.__init__
likewise subscribes to OnSimReset and OnExitBuildBuy and only unsubscribes OnSimReset in _self_destruct.

After each situation is destroyed, those direct subscriptions are removed. A destroyed situation is never meant to
handle events, so live situations are unaffected.
"""

from codebleu_loose_ends.guard import ABSENT, Fix, Hook, Requirement

_game = {}


def _unsubscribe(situation, *event_names):
    event_manager = _game['services'].get_event_manager()
    if event_manager is None or getattr(event_manager, '_test_event_callback_map', None) is None:
        return
    for event_name in event_names:
        event_manager.unregister_single_event(situation, getattr(_game['TestEvent'], event_name))


def _make_employee_destroy(original):
    def _destroy(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        finally:
            if EMPLOYEE_FIX.active:
                try:
                    _unsubscribe(self, 'InteractionComplete')
                except Exception as e:
                    EMPLOYEE_FIX.fault(e)
    _destroy.__wrapped__ = original
    return _destroy


def _make_chef_destroy(_):
    owner = _game['ChefSituation']

    def _destroy(self, *args, **kwargs):
        try:
            return super(owner, self)._destroy(*args, **kwargs)
        finally:
            if CHEF_FIX.active:
                try:
                    _unsubscribe(self, 'OnSimReset', 'OnExitBuildBuy')
                except Exception as e:
                    CHEF_FIX.fault(e)
    return _destroy


def _common():
    import services
    from event_testing.test_events import TestEvent
    _game.update(services=services, TestEvent=TestEvent)


def _build_employee():
    from small_business.small_business_employee_situation import SmallBusinessEmployeeSituation
    _common()
    return [Hook(SmallBusinessEmployeeSituation, '_destroy', 0xa582eeac4362c35a, _make_employee_destroy)], [
        Requirement(SmallBusinessEmployeeSituation, '__init__', 0x8eb7dd56b6897466)]


def _build_chef():
    from restaurants.chef_situation import ChefSituation
    _common()
    _game['ChefSituation'] = ChefSituation
    return [Hook(ChefSituation, '_destroy', ABSENT, _make_chef_destroy)], [
        Requirement(ChefSituation, '__init__', 0x2063d59138c6d4cb),
        Requirement(ChefSituation, '_self_destruct', 0x58f64cc3a60ac1aa)]


EMPLOYEE_FIX = Fix('small_business_employee_events', 'Small business employees aren\'t penalized again for every past shift', _build_employee)
CHEF_FIX = Fix('chef_events', 'Ended restaurant chef shifts stop reacting to Build mode and resets', _build_chef)
