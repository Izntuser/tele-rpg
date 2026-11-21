-- Runs once on first Postgres start (docker-entrypoint-initdb.d); CI runs it with psql.
CREATE DATABASE telerpg;
CREATE DATABASE telerpg_test;
CREATE DATABASE telerpg_e2e;
