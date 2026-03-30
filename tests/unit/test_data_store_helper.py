from convertcom_sdk import DataStore


def test_data_store_reads_writes_and_deletes(tmp_path):
    path = tmp_path / "store.json"
    store = DataStore(str(path))

    store.set("visitor-1", {"bucketing": {"exp-1": "var-1"}})

    assert store.get("visitor-1") == {"bucketing": {"exp-1": "var-1"}}

    store.delete("visitor-1")

    assert store.get("visitor-1") is None
