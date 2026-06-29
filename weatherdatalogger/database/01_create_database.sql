-- Run once as the MySQL root user on the LXC:
--   mysql -u root -p < /path/to/database/01_create_database.sql
--
-- Change the password on the CREATE USER line before running.

CREATE DATABASE IF NOT EXISTS weatherdatalogger
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- '%' allows connections from any host on the network.
-- Requires MariaDB bind-address = 0.0.0.0 in /etc/mysql/mariadb.conf.d/50-server.cnf.
CREATE USER IF NOT EXISTS 'weatherlogger'@'%' IDENTIFIED BY 'change_me_before_running';

GRANT ALL PRIVILEGES ON weatherdatalogger.* TO 'weatherlogger'@'%';

FLUSH PRIVILEGES;
