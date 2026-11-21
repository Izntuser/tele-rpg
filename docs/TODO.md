# TODO
## Needs human
## Next agent
- Needs human: .env.example could not be written (write denied by permission settings). Copy /private/tmp/claude-501/-Users-Anton-devs-red-tele-rpg/95f0f1c7-688e-4ba7-9f70-df967261594f/scratchpad/env.example to .env.example (init.sh and config already fall back to the same defaults).
- Production guard: refuse to start (APP_ENV=prod) when jwt_secret is still the default value.
- backend/Dockerfile: pin the uv version (not :latest) and run the final image as a non-root user.
