from convertcom_sdk import LogManager


class RecordingClient:
    def __init__(self) -> None:
        self.calls = []

    def log(self, *args):
        self.calls.append(("log", args))

    def trace(self, *args):
        self.calls.append(("trace", args))

    def debug(self, *args):
        self.calls.append(("debug", args))

    def info(self, *args):
        self.calls.append(("info", args))

    def warn(self, *args):
        self.calls.append(("warn", args))

    def error(self, *args):
        self.calls.append(("error", args))


class CustomMethodClient:
    def __init__(self) -> None:
        self.calls = []

    def write_info(self, *args):
        self.calls.append(("write_info", args))

    def error(self, *args):
        self.calls.append(("error", args))


def test_log_manager_respects_client_level():
    client = RecordingClient()
    logger = LogManager(client=client, level="info")

    logger.debug("hidden")
    logger.info("visible")

    assert client.calls == [("info", ("visible",))]


def test_log_manager_uses_custom_method_map():
    client = CustomMethodClient()
    logger = LogManager(client=client, level="trace", mapper={"info": "write_info"})

    logger.info("mapped")

    assert client.calls == [("write_info", ("mapped",))]
