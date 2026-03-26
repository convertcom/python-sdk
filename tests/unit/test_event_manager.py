from convertcom_sdk import EventManager, SystemEvents


def test_event_manager_fires_deferred_event_for_late_listener():
    event_manager = EventManager()
    received = []

    event_manager.fire(SystemEvents.READY, {"ok": True}, None, True)
    event_manager.on(SystemEvents.READY, lambda args, err: received.append((args, err)))

    assert received == [({"ok": True}, None)]


def test_event_manager_remove_listeners_clears_callbacks():
    event_manager = EventManager()
    received = []

    event_manager.on(SystemEvents.CONFIG_UPDATED, lambda args, err: received.append(args))
    event_manager.remove_listeners(SystemEvents.CONFIG_UPDATED)
    event_manager.fire(SystemEvents.CONFIG_UPDATED, {"updated": True})

    assert received == []
