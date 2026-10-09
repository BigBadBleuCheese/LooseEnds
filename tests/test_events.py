"""Event subscription fixes, run against the game's real EventManagerService, service start() and situation bytecode."""

import collections
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'stubs'), os.path.join(HERE, '..', 'src')]

import ea
from codebleu_loose_ends import guard

EMS = 'event_testing.event_manager_service'
TestEvent = types.SimpleNamespace(OnSimReset='OnSimReset', SimDeathTypeSet='SimDeathTypeSet', NarrativesUpdated='NarrativesUpdated', InteractionComplete='InteractionComplete',
    OnExitBuildBuy='OnExitBuildBuy', HouseholdChanged='HouseholdChanged')


def event_manager_class():
    globals_ = dict(collections=collections, logger=types.SimpleNamespace(assert_raise=lambda *a, **k: None, error=lambda *a, **k: None))
    names = ('__init__', 'register', 'register_single_event', 'unregister', 'unregister_single_event', 'register_with_custom_key', 'unregister_with_custom_key', 'is_registered_for_event',
        'on_zone_unload', '_is_valid_handler', 'start')
    return type('EventManagerService', (), {name: ea.function(EMS, 'EventManagerService.' + name, globals_) for name in names})


class Service:
    def handle_event(self, *args):
        pass


def service_classes(services):
    globals_ = dict(services=services, TestEvent=TestEvent)
    RabbitHoleService = type('RabbitHoleService', (Service,), {'start': ea.function('services.rabbit_hole_service', 'RabbitHoleService.start', globals_)})
    CullingService = type('CullingService', (Service,), {'CULLING_EVENTS': ('SimDeathTypeSet', 'HouseholdChanged'),
        'start': ea.function('sims.culling.culling_service', 'CullingService.start', globals_)})
    ClanService = type('ClanService', (Service,), {'NARRATIVE_TO_ALLIANCE_STATE_MAP': {'war': 1, 'peace': 2},
        'start': ea.function('clans.clan_service', 'ClanService.start', globals_)})
    return RabbitHoleService, CullingService, ClanService


class TravelSubscriptionTests(unittest.TestCase):

    def setUp(self):
        from codebleu_loose_ends.fixes import travel_event_subscriptions as module
        self.module = module
        self.manager = event_manager_class()()
        self.manager.start()
        services = types.SimpleNamespace(get_event_manager=lambda: self.manager)
        RabbitHoleService, CullingService, ClanService = service_classes(services)
        self.rabbit_hole, self.culling, self.clan = RabbitHoleService(), CullingService(), ClanService()
        for service in (self.rabbit_hole, self.culling, self.clan):
            service.start()
        module._game.update(game_services=types.SimpleNamespace(service_manager=types.SimpleNamespace(services=[self.rabbit_hole, self.culling, self.clan])), TestEvent=TestEvent,
            subscriptions=(
                (RabbitHoleService, lambda manager, service, events: manager.register_single_event(service, events.OnSimReset)),
                (CullingService, lambda manager, service, _: manager.register(service, service.CULLING_EVENTS)),
                (ClanService, module._clan_subscribe)))
        module.FIX.state = guard.ACTIVE
        self.fresh = {key: set(handlers) for key, handlers in self.manager._test_event_callback_map.items()}

    def snapshot(self):
        return {key: set(handlers) for key, handlers in self.manager._test_event_callback_map.items() if handlers}

    def test_travel_loses_startup_subscriptions(self):
        self.manager.on_zone_unload()
        self.assertFalse(self.manager.is_registered_for_event(self.rabbit_hole, 'OnSimReset'))

    def test_fix_restores_exactly_the_fresh_load_state(self):
        do = self.module._make(lambda manager: None)
        do(self.manager)
        self.assertEqual(self.snapshot(), self.fresh, 'on a fresh load the fix changes nothing')
        self.assertEqual(self.module.stats['restored last load'], 0)
        self.manager.on_zone_unload()
        do(self.manager)
        self.assertEqual(self.snapshot(), self.fresh)
        self.assertIn(('NarrativesUpdated', 'war'), self.fresh)
        self.assertEqual(self.module.stats['restored last load'], 5)

    def test_inactive_fix_does_nothing(self):
        self.module.FIX.state = guard.GAME_CHANGED
        self.manager.on_zone_unload()
        self.module._make(lambda manager: None)(self.manager)
        self.assertEqual(self.snapshot(), {})


class SmallBusinessEmployeeTests(unittest.TestCase):

    def test_destroyed_shift_stops_listening(self):
        from codebleu_loose_ends.fixes import situation_event_leaks as module
        manager = event_manager_class()()
        manager.start()
        services = types.SimpleNamespace(get_event_manager=lambda: manager, business_service=lambda: types.SimpleNamespace(get_business_manager_for_zone=lambda: None))

        class SituationComplex:
            def __init__(self, seed):
                self._registered_test_events = set()

            def _register_test_event_for_keys(self, event, keys):
                for key in keys:
                    manager.register_with_custom_key(self, event, key)
                    self._registered_test_events.add((event, key))

            def _destroy(self):
                for event, key in self._registered_test_events:
                    manager.unregister_with_custom_key(self, event, key)

            def handle_event(self, *args):
                pass

        globals_ = dict(services=services, TestEvent=TestEvent, BusinessType=types.SimpleNamespace(SMALL_BUSINESS=1))
        Employee = type('SmallBusinessEmployeeSituation', (SituationComplex,), {'go_home_interaction': types.SimpleNamespace(custom_keys_gen=lambda: iter(['go_home']))})
        Employee.__init__ = ea.function('small_business.small_business_employee_situation', 'SmallBusinessEmployeeSituation.__init__', globals_, Employee)
        vanilla_destroy = ea.function('small_business.small_business_employee_situation', 'SmallBusinessEmployeeSituation._destroy', globals_, Employee)
        Employee._destroy = vanilla_destroy
        shifts = [Employee(None) for _ in range(5)]
        for shift in shifts:
            shift._destroy()
        self.assertEqual(len(manager._test_event_callback_map[('InteractionComplete', None)]), 5, 'vanilla leaks one handler per shift')

        module._game.update(services=services, TestEvent=TestEvent)
        module.EMPLOYEE_FIX.state = guard.ACTIVE
        manager.on_zone_unload()
        Employee._destroy = module._make_employee_destroy(vanilla_destroy)
        shifts = [Employee(None) for _ in range(5)]
        live = Employee(None)
        for shift in shifts:
            shift._destroy()
        self.assertEqual(manager._test_event_callback_map[('InteractionComplete', None)], {live})
        self.assertEqual(manager._test_event_callback_map[('InteractionComplete', 'go_home')], {live})


if __name__ == '__main__':
    unittest.main()
