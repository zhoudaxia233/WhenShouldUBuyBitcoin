import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args, cwd, **kwargs):
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        **kwargs,
    )


def _git(repo, *args, check=True):
    result = _run(["git", *args], repo)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def _commit(repo, message):
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _configure_git(repo):
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _fake_docker_env(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
        "exit 0\n"
    )
    docker.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
    }, docker_log


def test_update_script_preserves_generated_artifacts_across_pull(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    updater = tmp_path / "updater"
    server = tmp_path / "server"

    _run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        tmp_path,
        check=True,
    )
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_git(seed)

    (seed / "docs/charts").mkdir(parents=True)
    (seed / "docs/data").mkdir(parents=True)
    (seed / "docs/charts/bottom_signals_info.json").write_text("initial\n")
    (seed / "docs/data/onchain_metrics.csv").write_text("initial\n")
    (seed / "update.sh").write_text((REPO_ROOT / "update.sh").read_text())
    _commit(seed, "initial")
    _git(seed, "push", "origin", "main")

    _git(tmp_path, "clone", str(origin), str(server))
    _git(tmp_path, "clone", str(origin), str(updater))
    _configure_git(updater)
    (updater / "docs/charts/bottom_signals_info.json").write_text("remote generated\n")
    _commit(updater, "remote generated update")
    _git(updater, "push", "origin", "main")

    (server / "docs/charts/bottom_signals_info.json").write_text("server generated\n")

    env, docker_log = _fake_docker_env(tmp_path)

    result = _run(["bash", "update.sh"], server, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (server / "docs/charts/bottom_signals_info.json").read_text() == "server generated\n"
    assert _git(server, "rev-parse", "--short", "HEAD").stdout.strip() == _git(
        updater, "rev-parse", "--short", "HEAD"
    ).stdout.strip()
    assert "compose down" in docker_log.read_text()
    assert "compose up -d --build" in docker_log.read_text()


def test_update_script_preserves_ignored_generated_artifacts_if_remote_retracks_them(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    updater = tmp_path / "updater"
    server = tmp_path / "server"

    _run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        tmp_path,
        check=True,
    )
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_git(seed)

    (seed / "docs/charts").mkdir(parents=True)
    (seed / "docs/data").mkdir(parents=True)
    (seed / ".gitignore").write_text(
        "docs/data/*\n"
        "docs/charts/*\n"
        "!docs/data/.gitkeep\n"
        "!docs/charts/.gitkeep\n"
    )
    (seed / "docs/charts/.gitkeep").write_text("")
    (seed / "docs/data/.gitkeep").write_text("")
    (seed / "update.sh").write_text((REPO_ROOT / "update.sh").read_text())
    _commit(seed, "initial ignored generated dirs")
    _git(seed, "push", "origin", "main")

    _git(tmp_path, "clone", str(origin), str(server))
    _git(tmp_path, "clone", str(origin), str(updater))
    _configure_git(updater)
    generated = updater / "docs/charts/bottom_signals_info.json"
    generated.write_text("remote re-tracked generated snapshot\n")
    _git(updater, "add", "-f", "docs/charts/bottom_signals_info.json")
    _git(updater, "commit", "-m", "force add generated snapshot")
    _git(updater, "push", "origin", "main")

    server_generated = server / "docs/charts/bottom_signals_info.json"
    server_generated.write_text("server generated newer data\n")

    env, docker_log = _fake_docker_env(tmp_path)

    result = _run(["bash", "update.sh"], server, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert server_generated.read_text() == "server generated newer data\n"
    assert "compose down" in docker_log.read_text()


def test_update_script_refuses_non_generated_changes(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    server = tmp_path / "server"

    _run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        tmp_path,
        check=True,
    )
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_git(seed)

    (seed / "docs/charts").mkdir(parents=True)
    (seed / "docs/data").mkdir(parents=True)
    (seed / "README.md").write_text("initial\n")
    (seed / "docs/charts/bottom_signals_info.json").write_text("initial\n")
    (seed / "docs/data/onchain_metrics.csv").write_text("initial\n")
    (seed / "update.sh").write_text((REPO_ROOT / "update.sh").read_text())
    _commit(seed, "initial")
    _git(seed, "push", "origin", "main")

    _git(tmp_path, "clone", str(origin), str(server))
    (server / "README.md").write_text("local code/doc change\n")
    env, docker_log = _fake_docker_env(tmp_path)

    result = _run(["bash", "update.sh"], server, env=env)

    assert result.returncode == 1
    assert "non-generated local changes" in result.stdout
    assert not docker_log.exists()
