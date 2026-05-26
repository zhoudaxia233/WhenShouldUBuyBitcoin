from fastapi.testclient import TestClient


def test_one_time_dca_repair_endpoint_is_removed(client: TestClient):
    response = client.post("/api/transactions/repair-dca-classification?dry_run=true")

    assert response.status_code in {404, 405}
