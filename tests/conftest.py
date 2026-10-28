import pytest

from capsule.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        capsule_state_dir=tmp_path,
        capsule_mode="simulation",
        google_api_key="",
        capsule_token="",
    )
