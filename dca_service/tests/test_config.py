import pytest

from dca_service.config import (
    DEV_SESSION_SECRET_DEFAULT,
    Settings,
    _enforce_secure_session_secret,
)


def test_secure_session_requirement_can_be_loaded_from_env_file(tmp_path, monkeypatch):
    """DCA_REQUIRE_SECURE_SESSION should work when loaded through Settings from .env."""
    monkeypatch.delenv("DCA_REQUIRE_SECURE_SESSION", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DCA_REQUIRE_SECURE_SESSION=true",
                f"SESSION_SECRET={DEV_SESSION_SECRET_DEFAULT}",
            ]
        )
    )

    settings = Settings(_env_file=env_file)

    with pytest.raises(RuntimeError, match="SESSION_SECRET is the insecure dev default"):
        _enforce_secure_session_secret(settings)
