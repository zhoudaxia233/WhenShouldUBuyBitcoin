from pathlib import Path


def test_docker_runtime_disables_uvicorn_access_log():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert '"--no-access-log"' in dockerfile
