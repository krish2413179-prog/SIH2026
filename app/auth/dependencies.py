"""FastAPI RBAC dependencies — auth fully bypassed, returns static investigator user matching DB user ID instantly."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

ROLE_HIERARCHY: dict[str, int] = {
    "investigator": 1,
    "supervisor": 2,
}

# Current user ID from the database to satisfy Foreign Key constraints
USER_ID = uuid.UUID("165e9dfc-739a-419c-bc43-3be8d25afe92")
ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

def _make_static_user():
    user = MagicMock()
    user.id = USER_ID
    user.email = "investigator@lea.gov.in"
    role_mock = MagicMock()
    role_mock.value = "investigator"
    user.role = role_mock
    user.org_unit_id = ORG_ID
    user.failed_login_attempts = 0
    user.locked_until = None
    return user

_STATIC_USER = _make_static_user()


async def get_current_user():
    return _STATIC_USER


def require_role(minimum_role: str):
    async def _dependency():
        return _STATIC_USER

    _dependency.__name__ = f"require_{minimum_role}"
    return _dependency


require_investigator = require_role("investigator")
require_supervisor = require_role("supervisor")
