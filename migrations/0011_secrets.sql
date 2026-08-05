-- 0011_secrets.sql
--
-- Credentials an operator can set from the control plane, encrypted at rest.
--
-- Until now the model API key was an environment variable of the programme
-- process, which is the strongest place to keep it: a value in a process's
-- environment is in no backup, no replica and no dump. The cost was that
-- changing it meant editing a `.env` on the host and restarting a container,
-- which is not something an operator can do from a browser at all.
--
-- This table is the trade, and it is worth naming both halves rather than only
-- the convenient one:
--
--   * Gained — the key is settable and rotatable from the UI, with an audit
--     entry, without a redeploy. A key that is hard to rotate is a key nobody
--     rotates.
--   * Lost — the secret now exists in the database, so it is in every backup
--     and every replica. Encryption is what makes that acceptable, not what
--     makes it free.
--
-- Three things about the shape:
--
-- `ciphertext` is a Fernet token and never a plaintext column. There is
-- deliberately no `value` column for anyone to write to by accident.
--
-- `fingerprint` is a truncated BLAKE2b digest of the *plaintext*, stored so the
-- UI can answer "is the key here the one I think it is" without the API ever
-- decrypting to answer it. It is not sensitive: 48 bits identifies a
-- high-entropy token, and cannot produce one.
--
-- There is no `created_at`/`rotated_at` history and no second row per name. A
-- table that retains superseded secrets is a table that retains revoked
-- credentials, and the audit log already records that a rotation happened, by
-- whom, and when — without keeping the value it replaced.

CREATE TABLE IF NOT EXISTS secrets (
    name        TEXT PRIMARY KEY,
    ciphertext  TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT 'operator',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A row that exists must carry something. An empty ciphertext would read as
    -- "configured" everywhere in the UI while decrypting to nothing at the one
    -- moment it matters, which is the failure mode this whole feature exists to
    -- avoid: a control that looks set and is not.
    CONSTRAINT secrets_ciphertext_present CHECK (length(ciphertext) > 0),
    CONSTRAINT secrets_fingerprint_present CHECK (length(fingerprint) > 0)
);

-- No seed row. An absent secret is absent, and seeding an empty one would make
-- "never configured" and "explicitly cleared" indistinguishable — the same
-- distinction `programme_config` draws with NULL meaning TBD.
