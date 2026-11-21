# TODO
## Needs human
## Next agent
- backend/Dockerfile: pin the uv version (not :latest) and run the final image as a non-root user.
- init.sh: run `uv sync --frozen` (as CI does) so uv.lock drift fails loudly.
- scripts/test-smoke.sh: simulate API-down by killing uvicorn (per S01 test_step), not only a dead port.
- init.sh: PID liveness via `kill -0` can match a reused PID; also verify the process command line.
- backend/app/core/db.py (S01, NullPool engine used by /healthz) duplicates app/db/session.py; point /healthz at db.session and delete core/db.py.
- gold_transaction.(user_id, partnership_id) is not FK-tied to its wallet's (user_id, partnership_id); consider a composite FK to wallet(id, user_id, partnership_id).
- FKs are all NO ACTION (users are soft-deleted); /api/test/reset must TRUNCATE ... CASCADE (see tests/conftest.py::truncate_all).
