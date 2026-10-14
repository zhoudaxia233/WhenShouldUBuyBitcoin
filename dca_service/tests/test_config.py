import pytest

from dca_service.config import (
    DEV_SESSION_SECRET_DEFAULT,
    ENV_EXAMPLE_SESSION_SECRET,
    Settings,
    _resolve_session_secret,
)


@pytest.fixture(autouse=True)
def no_session_env(monkeypatch):
    monkeypatch.delenv("DCA_REQUIRE_SECURE_SESSION", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)


def test_secure_session_requirement_can_be_loaded_from_env_file(tmp_path):
    """DCA_REQUIRE_SECURE_SESSION should work when loaded through Settings from .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("DCA_REQUIRE_SECURE_SESSION=true\n")

    settings = Settings(_env_file=env_file)

    with pytest.raises(RuntimeError, match="SESSION_SECRET is not set"):
        _resolve_session_secret(settings)


@pytest.mark.parametrize("public_value", [DEV_SESSION_SECRET_DEFAULT, ENV_EXAMPLE_SESSION_SECRET])
def test_publicly_known_secret_is_refused_even_in_dev(tmp_path, public_value):
    """These values are in the open-source repo: anyone could forge a login cookie."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"SESSION_SECRET={public_value}\n")

    settings = Settings(_env_file=env_file)

    with pytest.raises(RuntimeError, match="publicly known"):
        _resolve_session_secret(settings)


def test_unset_secret_falls_back_to_a_random_one():
    first = Settings(_env_file=None)
    second = Settings(_env_file=None)

    _resolve_session_secret(first)
    _resolve_session_secret(second)

    assert len(first.SESSION_SECRET) >= 32
    assert first.SESSION_SECRET not in {DEV_SESSION_SECRET_DEFAULT, ENV_EXAMPLE_SESSION_SECRET}
    assert first.SESSION_SECRET != second.SESSION_SECRET


def test_configured_secret_is_kept(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SESSION_SECRET=my-own-strong-random-secret-value-0123456789\n")

    settings = Settings(_env_file=env_file)
    _resolve_session_secret(settings)

    assert settings.SESSION_SECRET == "my-own-strong-random-secret-value-0123456789"
