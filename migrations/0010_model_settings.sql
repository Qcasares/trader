-- 0010_model_settings.sql
--
-- Which model the programme is pointed at, how hard it is asked to think, the
-- token ceiling on a reply, and how often it runs. Four settings that used to
-- be an environment variable and a constant, moved into the control plane so an
-- operator can change them without a redeploy.
--
-- These live in `system_flags` rather than in `programme_config` on purpose.
-- `programme_config` is the operating prompt's section 2: a vocabulary of
-- research parameters where NULL means TBD and TBD is rendered rather than
-- invented. These are not that. They are operational knobs read on every pass,
-- and a NULL here would not mean "nobody has decided" — it would mean the
-- programme cannot make a request. `system_flags` is where the kill switch and
-- the autonomy ceiling already live, and these are read the same fail-closed
-- way by `src/programme/flags.py`.
--
-- Every value below is seeded rather than left absent, and each is the
-- documented default of the thing it configures rather than a preference:
--
--   * `claude-sonnet-5` is what `src/programme/client.py` already used.
--   * `high` is the vendor's own default effort. Choosing anything else would
--     be this repository inventing a setting and then rendering it as though
--     somebody had agreed it.
--   * 2500 is the largest `max_tokens` any current ModelCall asks for, so the
--     ceiling starts non-binding. It is a cap on the call, not the call's size.
--   * 3600 is the interval `PROGRAMME_TICK_SECONDS` defaulted to.
--
-- `updated_by` is 'migration' for all four, which is how the configuration page
-- can honestly say these are defaults nobody has yet reviewed.

INSERT INTO system_flags (key, value, updated_by, updated_at) VALUES
    ('programme_provider',     '"anthropic"'::jsonb,        'migration', NOW()),
    ('programme_model',        '"claude-sonnet-5"'::jsonb,  'migration', NOW()),
    ('programme_effort',       '"high"'::jsonb,             'migration', NOW()),
    ('programme_max_tokens',   '2500'::jsonb,               'migration', NOW()),
    ('programme_tick_seconds', '3600'::jsonb,               'migration', NOW())
ON CONFLICT (key) DO NOTHING;
