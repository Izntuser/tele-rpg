import os

# Must run before app modules are imported: pytest uses the telerpg_test database.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_test"
)
os.environ["FRONTEND_DIST"] = "/nonexistent"
