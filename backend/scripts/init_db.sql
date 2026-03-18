-- Initialize PostgreSQL extensions for local development.
-- Runs once on first docker-compose up via /docker-entrypoint-initdb.d/.
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
