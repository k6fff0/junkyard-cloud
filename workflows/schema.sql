-- The assistant's own tables, in their own database (not n8n's). Safe to run again.
CREATE TABLE IF NOT EXISTS jc_assistant_memory (          -- chat memory (n8n Postgres Chat Memory) + server notes
    id serial PRIMARY KEY,
    session_id varchar(255) NOT NULL,
    message jsonb NOT NULL);
CREATE INDEX IF NOT EXISTS jc_assistant_memory_session_idx ON jc_assistant_memory (session_id, id);

CREATE TABLE IF NOT EXISTS jc_web_taint (                 -- runs that read from the web: their other tools are locked
    exec_id text PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS jc_web_taint_ts_idx ON jc_web_taint (ts);

CREATE TABLE IF NOT EXISTS jc_notes (                     -- "remember this": the owner's long-term notes
    id serial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    text text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'deleted')),
    closed_note text,
    source text);

CREATE TABLE IF NOT EXISTS jc_watches (                   -- website watches
    id serial PRIMARY KEY,
    name text NOT NULL,
    urls jsonb NOT NULL,
    criteria text NOT NULL,
    every_minutes integer NOT NULL DEFAULT 180,
    channels jsonb NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created timestamptz NOT NULL DEFAULT now(),
    last_run timestamptz,
    runs integer NOT NULL DEFAULT 0,
    last_error text,
    seen jsonb NOT NULL DEFAULT '[]'::jsonb);
CREATE INDEX IF NOT EXISTS jc_watches_due_idx ON jc_watches (active, last_run);

CREATE TABLE IF NOT EXISTS jc_mail (                      -- emails seen by mailwatch (kept 90 days)
    id bigserial PRIMARY KEY,
    account text NOT NULL,
    uid bigint,
    message_id text NOT NULL UNIQUE,
    received_at timestamptz NOT NULL DEFAULT now(),
    mail_date text,
    from_name text,
    from_addr text,
    to_addr text,
    subject text,
    snippet text,
    attachments text,
    category text,
    otp_code text,
    summary text,
    notified_at timestamptz,
    digested_at timestamptz);
CREATE INDEX IF NOT EXISTS jc_mail_digest_idx ON jc_mail (digested_at, category);
CREATE INDEX IF NOT EXISTS jc_mail_received_idx ON jc_mail (received_at);
CREATE INDEX IF NOT EXISTS jc_mail_from_idx ON jc_mail (lower(from_addr));
