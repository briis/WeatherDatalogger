-- Run once as the MySQL root user on the LXC:
--   mysql -u root -p < /path/to/database/01_create_database.sql
--
-- Change the password on the CREATE USER line before running.

CREATE DATABASE IF NOT EXISTS weatherdatalogger
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- '%' allows connections from any host; restrict to '127.0.0.1' or a specific
-- subnet if this instance should not be reachable from the wider network.
CREATE USER IF NOT EXISTS 'weatherlogger'@'%' IDENTIFIED BY 'change_me_before_running';

GRANT ALL PRIVILEGES ON weatherdatalogger.* TO 'weatherlogger'@'%';

FLUSH PRIVILEGES;
