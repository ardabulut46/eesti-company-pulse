import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from pulse.config import Paths  # noqa: E402


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(tmp_path / "data")
