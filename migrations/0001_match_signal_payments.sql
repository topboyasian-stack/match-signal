-- Match Signal Paystack checkout and API access ledger.
-- Bind this database in Cloudflare Pages as MATCH_SIGNAL_DB, then apply this migration.
CREATE TABLE IF NOT EXISTS ms_payments (
  reference TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  amount_kobo INTEGER NOT NULL CHECK (amount_kobo > 0),
  plan_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'initialized' CHECK (status IN ('initialized','paid','failed','expired')),
  checkout_token_hash TEXT NOT NULL,
  paystack_transaction_id TEXT,
  paid_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ms_api_keys (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  key_ciphertext TEXT NOT NULL,
  plan_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','expired')),
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  payment_reference TEXT NOT NULL UNIQUE REFERENCES ms_payments(reference)
);
CREATE INDEX IF NOT EXISTS idx_ms_api_keys_email ON ms_api_keys(email);
CREATE INDEX IF NOT EXISTS idx_ms_api_keys_status_expiry ON ms_api_keys(status, expires_at);
