-- PartnerPortal database schema.
--
-- These definitions match exactly what app.py reads and writes. If you change
-- a column here, grep app.py for the old name before you run it.
--
--   mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS partnerportaldb"
--   mysql -u root -p partnerportaldb < schema.sql
--   mysql -u root -p partnerportaldb < seed.sql   # optional sample partners

-- Accounts created through /register.
CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    -- Stored lower-cased by /register so login is not case-sensitive.
    email         VARCHAR(255) NOT NULL UNIQUE,
    -- bcrypt hash (60 chars today, but the prefix may grow).
    password      VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- The searchable directory behind /api/partners.
-- Column names are PascalCase because the API returns them straight to the
-- frontend, which reads partner.Name, partner.OrganizationType, and so on.
CREATE TABLE IF NOT EXISTS partners (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    Name             VARCHAR(255) NOT NULL,
    OrganizationType VARCHAR(255) NOT NULL,
    Expertise        VARCHAR(255) NOT NULL,
    Resources        TEXT,
    Email            VARCHAR(255),
    PhoneNumber      VARCHAR(32),
    Location         VARCHAR(255),
    Bio              TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Profiles submitted through /api/onboarding.
--
-- NOTE: there is deliberately no user_id yet -- nothing links a profile to the
-- account that created it, which is why an onboarded org is invisible to other
-- users' searches. Merging this table with `partners` and `users` into a single
-- `organizations` model is the next phase of work.
CREATE TABLE IF NOT EXISTS onboarding_profiles (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    organization_name       VARCHAR(255) NOT NULL,
    organization_type       VARCHAR(255) NOT NULL,
    location                VARCHAR(255) NOT NULL,
    remote_friendly         BOOLEAN NOT NULL DEFAULT FALSE,
    needs                   TEXT NOT NULL,
    offers                  TEXT NOT NULL,
    preferred_partner_types VARCHAR(255),
    partnership_goals       TEXT,
    description             TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Messages from the "Request a demo" form on the landing page.
CREATE TABLE IF NOT EXISTS contact_messages (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    -- Optional on the form, so nullable here rather than storing ''.
    phone       VARCHAR(32),
    email       VARCHAR(255) NOT NULL,
    message     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
