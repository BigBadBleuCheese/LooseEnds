"""
Game services keep receiving the game events they subscribed to at startup after the household travels.

EventManagerService.on_zone_unload clears every event subscription on every zone teardown. On travel, game services are
not restarted (game_services.start_services returns early because the service manager survives), so services that
subscribe only in start() or on_all_households_and_sim_infos_loaded are deaf after the first travel until the save is
reloaded: rabbit holes don't release Sims reset inside them, dead roommates aren't removed, the culling service misses
deaths and household changes, clubs aren't revalidated, relationship, satisfaction, matchmaking and clan updates are
missed. Services that subscribe in on_zone_load (attraction, dynasty, kingdom and others) already do this correctly.

After EA re-registers objectives at the end of every zone spin-up, each affected service's startup subscriptions are
registered again. Subscriptions are sets, so on a fresh load this changes nothing; after travel it restores exactly the
fresh-load state.
"""

from codebleu_loose_ends.guard import Fix, Hook, Requirement

_game = {}
stats = {'zone loads': 0, 'restored last load': 0, 'restored total': 0}


def _services_of(service_type):
    manager = _game['game_services'].service_manager
    if manager is None:
        return
    for service in manager.services:
        if isinstance(service, service_type):
            yield service


def _subscription_count(event_manager):
    return sum(len(handlers) for handlers in event_manager._test_event_callback_map.values())


def _resubscribe(event_manager):
    test_event = _game['TestEvent']
    before = _subscription_count(event_manager)
    for service_type, subscribe in _game['subscriptions']:
        for service in _services_of(service_type):
            subscribe(event_manager, service, test_event)
    restored = _subscription_count(event_manager) - before
    stats['zone loads'] += 1
    stats['restored last load'] = restored
    stats['restored total'] += restored


def _make(original):
    def register_events_for_objectives(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if FIX.active:
            try:
                _resubscribe(self)
            except Exception as e:
                FIX.fault(e)
        return result
    register_events_for_objectives.__wrapped__ = original
    return register_events_for_objectives


def _clan_subscribe(event_manager, service, test_event):
    for narrative in service.NARRATIVE_TO_ALLIANCE_STATE_MAP.keys():
        event_manager.register_with_custom_key(service, test_event.NarrativesUpdated, narrative)


def _build():
    import game_services
    from clans.clan_service import ClanService
    from clubs.club_service import ClubService
    from event_testing.event_manager_service import EventManagerService
    from event_testing.test_events import TestEvent
    from relationships.relationship_service import RelationshipService
    from relationships.satisfaction_tuning import SatisfactionService
    from services.matchmaking_service import MatchmakingService
    from services.rabbit_hole_service import RabbitHoleService
    from services.roommate_service import RoommateService
    from sims.culling.culling_service import CullingService
    _game.update(game_services=game_services, TestEvent=TestEvent, subscriptions=(
        (RelationshipService, lambda manager, service, _: manager.register(service, service.ALL_EVENTS)),
        (SatisfactionService, lambda manager, service, _: manager.register(service, service.ALL_EVENTS)),
        (RabbitHoleService, lambda manager, service, events: manager.register_single_event(service, events.OnSimReset)),
        (MatchmakingService, lambda manager, service, _: manager.register(service, service.EVENTS)),
        (RoommateService, lambda manager, service, events: manager.register_single_event(service, events.SimDeathTypeSet)),
        (CullingService, lambda manager, service, _: manager.register(service, service.CULLING_EVENTS)),
        (ClubService, lambda manager, service, _: manager.register(service, service.CLUB_VALIDATION_EVENTS)),
        (ClanService, _clan_subscribe)))
    return [Hook(EventManagerService, 'register_events_for_objectives', 0x6b424136bddfa8b3, _make)], [
        Requirement(EventManagerService, 'on_zone_unload', 0x55e877f022c1ff16),
        Requirement(game_services, 'start_services', 0xfcfcdc4206c44a53),
        Requirement(RelationshipService, 'start', 0xc7a8c56482ef53ed),
        Requirement(SatisfactionService, 'start', 0xa66630875ff84bcd),
        Requirement(RabbitHoleService, 'start', 0x5ca0a04731494c1f),
        Requirement(MatchmakingService, 'start', 0xdac6e2c0388ff2bf),
        Requirement(RoommateService, 'on_all_households_and_sim_infos_loaded', 0x40ccbb97051239e7),
        Requirement(CullingService, 'start', 0xf6ecf900adbe4a3a),
        Requirement(ClubService, 'start', 0xa220935b9e13adbc),
        Requirement(ClanService, 'start', 0x2d3c840bcc204cf3)]


FIX = Fix('travel_event_subscriptions', 'Rabbit holes, roommates, clubs and relationships keep listening after you travel', _build)
