import re
from pathlib import Path


def test_docker_runtime_disables_uvicorn_access_log():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert '"--no-access-log"' in dockerfile


def test_nginx_rate_limits_login_submissions_not_login_page_views():
    repo_root = Path(__file__).resolve().parents[2]
    config = (repo_root / "nginx.conf.example").read_text(encoding="utf-8")

    method_map = re.search(
        r"map\s+\$request_method\s+\$(?P<key>\w+)\s*\{(?P<body>.*?)\}",
        config,
        re.DOTALL,
    )
    assert method_map, "login rate-limit key must depend on the request method"
    assert re.search(r'\bdefault\s+""\s*;', method_map.group("body"))
    assert re.search(
        r"\bPOST\s+\$binary_remote_addr\s*;", method_map.group("body")
    )
    assert re.search(
        rf"limit_req_zone\s+\${method_map.group('key')}\s+zone=login_limit:",
        config,
    )
