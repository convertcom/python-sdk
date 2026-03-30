from convertcom_sdk import EventManager, SystemEvents


class RecordingLogger:
    def __init__(self) -> None:
        self.errors = []

    def error(self, *args):
        self.errors.append(args)


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


def test_event_manager_logs_listener_errors():
    logger = RecordingLogger()
    event_manager = EventManager(logger_manager=logger)

    def broken_listener(args, err):
        del args, err
        raise RuntimeError("boom")

    event_manager.on(SystemEvents.READY, broken_listener)
    event_manager.fire(SystemEvents.READY, {"ok": True})

    assert logger.errors[0][0] == "EventManager.fire()"
    assert isinstance(logger.errors[0][1], RuntimeError)
