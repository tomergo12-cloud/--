PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    phone         TEXT,
    password_hash TEXT    NOT NULL,
    -- client = מזמין, pro = בעל פרופיל מקצועי, admin = ניהול המערכת
    role          TEXT    NOT NULL DEFAULT 'client',
    blocked       INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS professionals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    profession       TEXT    NOT NULL,
    headline         TEXT    NOT NULL DEFAULT '',
    bio              TEXT    NOT NULL DEFAULT '',
    city             TEXT    NOT NULL DEFAULT '',
    lat              REAL    NOT NULL,
    lng              REAL    NOT NULL,
    service_radius_km REAL   NOT NULL DEFAULT 15,
    hourly_rate      INTEGER NOT NULL DEFAULT 0,
    currency         TEXT    NOT NULL DEFAULT 'ILS',
    min_job_minutes  INTEGER NOT NULL DEFAULT 60,
    years_experience INTEGER NOT NULL DEFAULT 0,
    verified         INTEGER NOT NULL DEFAULT 0,
    active           INTEGER NOT NULL DEFAULT 1,
    emergency        INTEGER NOT NULL DEFAULT 0,  -- זמין גם לקריאות דחופות מחוץ ללו"ז
    tags             TEXT    NOT NULL DEFAULT '',
    photo            TEXT    NOT NULL DEFAULT '',  -- נתיב לתמונת פרופיל שהועלתה
    created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pros_box ON professionals(active, lat, lng);
CREATE INDEX IF NOT EXISTS idx_pros_profession ON professionals(profession);

-- לוח זמינות שבועי חוזר. weekday: 0=ראשון .. 6=שבת. דקות מתחילת היום.
CREATE TABLE IF NOT EXISTS availability_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pro_id     INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_min  INTEGER NOT NULL CHECK (start_min BETWEEN 0 AND 1440),
    end_min    INTEGER NOT NULL CHECK (end_min BETWEEN 0 AND 1440)
);
CREATE INDEX IF NOT EXISTS idx_rules_pro ON availability_rules(pro_id, weekday);

-- חסימות חד פעמיות (חופשה, עבודה פרטית, מילואים)
CREATE TABLE IF NOT EXISTS time_off (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pro_id   INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    start_ts INTEGER NOT NULL,
    end_ts   INTEGER NOT NULL,
    reason   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_timeoff_pro ON time_off(pro_id, start_ts, end_ts);

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pro_id         INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    client_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_ts       INTEGER NOT NULL,
    end_ts         INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending|confirmed|declined|cancelled|done
    address        TEXT    NOT NULL DEFAULT '',
    lat            REAL,
    lng            REAL,
    note           TEXT    NOT NULL DEFAULT '',
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_pro ON bookings(pro_id, status, start_ts);
CREATE INDEX IF NOT EXISTS idx_bookings_client ON bookings(client_user_id, start_ts);

CREATE TABLE IF NOT EXISTS reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pro_id         INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    booking_id     INTEGER UNIQUE REFERENCES bookings(id) ON DELETE SET NULL,
    client_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating         INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment        TEXT    NOT NULL DEFAULT '',
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_pro ON reviews(pro_id);
