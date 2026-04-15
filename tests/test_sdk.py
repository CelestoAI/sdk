from celesto.sdk import Celesto


def test_sdk_exposes_service_clients():
    client = Celesto("test-key", base_url="http://localhost:8500/v1")
    assert hasattr(client, "deployment")
    assert hasattr(client, "gatekeeper")
    assert hasattr(client, "computers")
