-- ============================================================
--  AGI Agent - PostgreSQL Schema
-- ============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- --------------------------------------------------------
-- Tasks table
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal            TEXT NOT NULL,
    mode            VARCHAR(20) NOT NULL DEFAULT 'interactive',
    status          VARCHAR(30) NOT NULL DEFAULT 'queued',
    current_step    TEXT,
    total_cost_usd  DECIMAL(10, 6) DEFAULT 0.0,
    model_used      VARCHAR(100),
    constraints     JSONB DEFAULT '{}',
    plan            JSONB DEFAULT '[]',
    artifacts       JSONB DEFAULT '[]',
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);

-- --------------------------------------------------------
-- Events table
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event_type      VARCHAR(50) NOT NULL,
    payload         JSONB DEFAULT '{}',
    model_used      VARCHAR(100),
    cost_usd        DECIMAL(10, 6) DEFAULT 0.0,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_task_id ON task_events(task_id);
CREATE INDEX idx_events_event_type ON task_events(event_type);
CREATE INDEX idx_events_created_at ON task_events(created_at DESC);

-- --------------------------------------------------------
-- Memory facts table
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_facts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key             VARCHAR(255) NOT NULL,
    value           TEXT NOT NULL,
    scope           VARCHAR(20) NOT NULL DEFAULT 'session',
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    embedding_id    VARCHAR(255),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_memory_key ON memory_facts(key);
CREATE INDEX idx_memory_scope ON memory_facts(scope);
CREATE INDEX idx_memory_task_id ON memory_facts(task_id);

-- --------------------------------------------------------
-- Evaluation metrics table
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_metrics (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id                 UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event_type              VARCHAR(50) NOT NULL,
    tool_name               VARCHAR(100),
    success                 BOOLEAN,
    retry_count             INTEGER DEFAULT 0,
    human_interventions     INTEGER DEFAULT 0,
    latency_ms              INTEGER,
    payload                 JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_eval_task_id ON eval_metrics(task_id);
CREATE INDEX idx_eval_event_type ON eval_metrics(event_type);

-- --------------------------------------------------------
-- Tool calls audit table
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS tool_calls (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tool_name       VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(255),
    input_schema    JSONB DEFAULT '{}',
    output          JSONB DEFAULT '{}',
    success         BOOLEAN NOT NULL DEFAULT FALSE,
    error_message   TEXT,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_tool_calls_idempotency ON tool_calls(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_tool_calls_task_id ON tool_calls(task_id);
CREATE INDEX idx_tool_calls_tool_name ON tool_calls(tool_name);

-- --------------------------------------------------------
-- Session preferences / long-term user memory
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_preferences (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key             VARCHAR(255) UNIQUE NOT NULL,
    value           TEXT NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- --------------------------------------------------------
-- Update trigger for updated_at
-- --------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

CREATE TRIGGER update_memory_updated_at
    BEFORE UPDATE ON memory_facts
    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- --------------------------------------------------------
-- Seed data: default user preferences
-- --------------------------------------------------------
INSERT INTO user_preferences (key, value, description) VALUES
    ('prefer_free_models', 'true', 'Use free OpenRouter models when possible'),
    ('max_budget_usd', '5.00', 'Maximum spend per task in USD'),
    ('require_approval_code', 'true', 'Require human approval before executing code'),
    ('max_retries', '3', 'Maximum retries per failed tool call')
ON CONFLICT (key) DO NOTHING;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO agi_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO agi_user;
