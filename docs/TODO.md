# TODO
## Needs human
## Next agent
- Production guard: refuse to start (APP_ENV=prod) when jwt_secret is still the default value.
- backend/Dockerfile: pin the uv version (not :latest) and run the final image as a non-root user.
- init.sh: run `uv sync --frozen` (as CI does) so uv.lock drift fails loudly.
- scripts/test-smoke.sh: simulate API-down by killing uvicorn (per S01 test_step), not only a dead port.
- init.sh: PID liveness via `kill -0` can match a reused PID; also verify the process command line.
