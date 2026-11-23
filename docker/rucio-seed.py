"""Bootstrap the Rucio DB and seed mock transfer history (Design-001, step 3).

Runs inside the rucio-server image (Python 3.9) before the server starts, and
in the integration tests. Idempotent: existing rows are left alone.

Seeded around SEED_DAY (default: yesterday, UTC), so `usage-reporter` finds
data with its default window:

  account      attributes                         transfers on SEED_DAY
  suc1-prod    RI-SCALE_ENES / suc1               100 + 50 bytes, plus 23:59:59
  suc2-prod    RI-SCALE_ENES / suc2               7 bytes, plus one FAILED
  suc3-prod    RI-SCALE_EISCAT / suc3             20 bytes
  ghost        none (unmapped)                    30 bytes
  reporter     admin, userpass reporter/secret    -
"""

import datetime
import os
import uuid

from rucio.common.exception import Duplicate, RucioException
from rucio.common.types import InternalAccount, InternalScope
from rucio.db.sqla import models
from rucio.db.sqla.constants import DIDType, RequestState, RequestType
from rucio.gateway.account import add_account, add_account_attribute
from rucio.gateway.identity import add_account_identity
from rucio.gateway.rse import add_rse, get_rse
from rucio.db.sqla.session import get_engine, get_session
from rucio.db.sqla.util import create_base_vo, create_root_account

RSES = ("CERN_DATADISK", "TUBITAK_DATADISK", "TUWIEN_DATADISK")
ACCOUNTS = {
    "suc1-prod": {"project_id": "RI-SCALE_ENES", "group_id": "suc1"},
    "suc2-prod": {"project_id": "RI-SCALE_ENES", "group_id": "suc2"},
    "suc3-prod": {"project_id": "RI-SCALE_EISCAT", "group_id": "suc3"},
    "ghost": {},
    "reporter": {"admin": "True"},
}


def _ignore_duplicate(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Duplicate:
        pass
    except RucioException as exc:  # some helpers wrap duplicates differently
        if "exist" not in str(exc).lower():
            raise


def _seed_day():
    raw = os.environ.get("SEED_DAY")
    if raw:
        return datetime.date.fromisoformat(raw)
    return datetime.datetime.utcnow().date() - datetime.timedelta(days=1)


def main():
    # Create tables directly (idempotent). No alembic stamp: this database is
    # throwaway test data, never migrated.
    models.register_models(get_engine())
    for bootstrap in (create_base_vo, create_root_account):
        try:
            bootstrap()
        except Exception as exc:  # already there on re-runs
            print(bootstrap.__name__, "skipped:", type(exc).__name__)

    for rse in RSES:
        _ignore_duplicate(add_rse, rse, issuer="root")
    for name, attrs in ACCOUNTS.items():
        _ignore_duplicate(add_account, name, "SERVICE", "dlm@example.org", issuer="root")
        for key, value in attrs.items():
            _ignore_duplicate(add_account_attribute, key, value, name, issuer="root")
    _ignore_duplicate(add_account_identity, "reporter", "USERPASS", "reporter",
                      "dlm@example.org", issuer="root", password="secret")

    day = _seed_day()
    at = lambda h, m=0, s=0: datetime.datetime(day.year, day.month, day.day, h, m, s)  # noqa: E731
    cern, tubitak, tuwien = (get_rse(r)["id"] for r in RSES)
    rows = [
        # (id, account, bytes, transferred_at, state, src, dst)
        ("seed-01", "suc1-prod", 100, at(9), RequestState.DONE, cern, tubitak),
        ("seed-02", "suc1-prod", 50, at(14), RequestState.DONE, cern, tuwien),
        ("seed-03", "suc1-prod", 1, at(23, 59, 59), RequestState.DONE, tubitak, cern),
        ("seed-04", "suc1-prod", 999, at(0) + datetime.timedelta(days=1), RequestState.DONE, cern, tubitak),
        ("seed-05", "suc2-prod", 7, at(11), RequestState.DONE, cern, tubitak),
        ("seed-06", "suc2-prod", 500, at(12), RequestState.FAILED, cern, tubitak),
        ("seed-07", "suc3-prod", 20, at(10), RequestState.DONE, tuwien, cern),
        ("seed-08", "ghost", 30, at(8), RequestState.DONE, cern, tuwien),
    ]
    session = get_session()()
    try:
        existing = {uuid.UUID(str(r[0])).hex for r in session.query(models.RequestHistory.id)}
        for rid, account, nbytes, when, state, src, dst in rows:
            request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, rid))
            if uuid.UUID(request_id).hex in existing:
                continue
            session.add(models.RequestHistory(
                id=request_id, request_type=RequestType.TRANSFER,
                scope=InternalScope("mock"), name=rid, did_type=DIDType.FILE,
                dest_rse_id=dst, source_rse_id=src, state=state,
                account=InternalAccount(account), bytes=nbytes,
                transferred_at=when, created_at=when, updated_at=when,
            ))
        session.commit()
    finally:
        session.close()
    print("seeded transfer history for", day.isoformat())


if __name__ == "__main__":
    main()
