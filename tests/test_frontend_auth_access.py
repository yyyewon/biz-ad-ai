import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / 'frontend'
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

from core.auth import should_allow_access


@pytest.mark.parametrize(
    ('session_state', 'expected'),
    [
        ({'mock_mode': False, 'dev_guest_mode': True, 'auth': {'access_token': None}}, True),
        ({'mock_mode': False, 'dev_guest_mode': False, 'auth': {'access_token': 'token'}}, True),
        ({'mock_mode': False, 'dev_guest_mode': False, 'auth': {'access_token': None}}, False),
    ],
)
def test_should_allow_access(session_state, expected):
    assert should_allow_access(session_state=session_state) is expected
