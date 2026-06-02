from pathlib import Path


def test_docker_runtime_disables_uvicorn_access_log():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert '"--no-access-log"' in dockerfile
