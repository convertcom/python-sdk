from convertcom_sdk import FileLogger


def test_file_logger_writes_prefixed_json_lines(tmp_path):
    path = tmp_path / "convert.log"
    logger = FileLogger(str(path))

    logger.info({"ok": True}, "hello")

    content = path.read_text(encoding="utf-8")
    assert "[INFO]" in content
    assert '{"ok": true}' in content
    assert '"hello"' in content
