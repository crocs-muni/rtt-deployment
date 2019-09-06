DROP DATABASE IF EXISTS rtt;

CREATE DATABASE IF NOT EXISTS rtt;
USE rtt;

CREATE TABLE IF NOT EXISTS experiments (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(255) NOT NULL,
    author_email        VARCHAR(255),
    status              ENUM('pending','running','finished') NOT NULL DEFAULT 'pending',
    created             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_started         DATETIME DEFAULT NULL,
    run_finished        DATETIME DEFAULT NULL,
    config_file         VARCHAR(255) NOT NULL,
    data_file           VARCHAR(255) NOT NULL,
    data_file_sha256    VARCHAR(64) NOT NULL
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS jobs (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    battery             VARCHAR(100) NOT NULL,
    status              ENUM('pending','running','finished') NOT NULL DEFAULT 'pending',
    run_started         DATETIME DEFAULT NULL,
    run_finished        DATETIME DEFAULT NULL,
    experiment_id       BIGINT UNSIGNED NOT NULL,
    run_heartbeat       DATETIME DEFAULT NULL,
    worker_id           BIGINT UNSIGNED DEFAULT NULL,
    worker_pid          INT UNSIGNED DEFAULT NULL,
    retries             INT UNSIGNED DEFAULT 0,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

-- ALTER TABLE jobs
-- ADD COLUMN run_heartbeat  DATETIME DEFAULT NULL AFTER experiment_id,
-- ADD COLUMN worker_id BIGINT UNSIGNED DEFAULT NULL AFTER run_heartbeat;

-- ALTER TABLE jobs
-- ADD COLUMN worker_pid          INT UNSIGNED DEFAULT NULL AFTER worker_id,
-- ADD COLUMN retries             INT UNSIGNED DEFAULT 0 AFTER worker_pid;

CREATE TABLE IF NOT EXISTS batteries (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(255) NOT NULL,
    passed_tests        BIGINT UNSIGNED NOT NULL,
    total_tests         BIGINT UNSIGNED NOT NULL,
    alpha               DOUBLE NOT NULL,
    experiment_id       BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS battery_errors (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    message             VARCHAR(1000) NOT NULL,
    battery_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (battery_id) REFERENCES batteries(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS battery_warnings (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    message             VARCHAR(1000) NOT NULL,
    battery_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (battery_id) REFERENCES batteries(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS tests (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(255) NOT NULL,
    partial_alpha       DOUBLE NOT NULL,
    result              ENUM('passed', 'failed') NOT NULL,
    test_index          INT UNSIGNED NOT NULL,
    battery_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (battery_id) REFERENCES batteries(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS variants (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    variant_index       INT UNSIGNED NOT NULL,
    test_id             BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS variant_warnings (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    message             VARCHAR(1000) NOT NULL,
    variant_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS variant_errors (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    message             VARCHAR(1000) NOT NULL,
    variant_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS variant_stderr (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    message             VARCHAR(1000) NOT NULL,
    variant_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS user_settings (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(100) NOT NULL,
    value               VARCHAR(50) NOT NULL,
    variant_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS subtests (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    subtest_index       INT UNSIGNED NOT NULL,
    variant_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS statistics (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(255) NOT NULL,
    value               DOUBLE NOT NULL,
    result              ENUM('passed', 'failed') NOT NULL,
    subtest_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (subtest_id) REFERENCES subtests(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS test_parameters (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    name                VARCHAR(100) NOT NULL,
    value               VARCHAR(50) NOT NULL,
    subtest_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (subtest_id) REFERENCES subtests(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS p_values (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    value               DOUBLE NOT NULL,
    subtest_id          BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (subtest_id) REFERENCES subtests(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE = INNODB;

CREATE TABLE IF NOT EXISTS workers (
    id                  BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    worker_id           VARCHAR(32) NOT NULL,
    worker_name         VARCHAR(250) DEFAULT NULL,
    worker_type         ENUM('longterm','shortterm') NOT NULL DEFAULT 'longterm',
    worker_added        DATETIME DEFAULT NULL,
    worker_last_seen    DATETIME DEFAULT NULL,
    worker_active       INT UNSIGNED NOT NULL DEFAULT 1,
    worker_address      VARCHAR(250) DEFAULT NULL,
    worker_location     VARCHAR(250) DEFAULT NULL,
    worker_aux          LONGTEXT DEFAULT NULL,
    UNIQUE(worker_id)
) ENGINE = INNODB;
