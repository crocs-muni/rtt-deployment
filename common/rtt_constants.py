# File containing constants used in deployment.
# Change them only if you have good reason to do so :)


class CommonConst(object):
    COMMON_FILES_DIR = "common"
    CREATE_TABLES_SCRIPT = "files/create_rtt_tables.sql"
    STORAGE_CLEAN_CACHE = "files/clean_cache.py"
    FRONTEND_SUBMIT_EXPERIMENT_SCRIPT = "files/submit_experiment.py"
    FRONTEND_ADD_USER_SCRIPT = "files/add_rtt_user.py"
    BACKEND_RUN_JOBS_SCRIPT = "files/run_jobs.py"
    BACKEND_CLEAN_CACHE_SCRIPT = "files/clean_cache.py"
    PASSWD_MYSQL = "/root/mysql-pass.txt"
    CONF_MYSQL = "/root/.my.cnf"
    USR_SRC = "/usr/src"

    CRYPTOSTREAMS_REPO = 'https://github.com/crocs-muni/CryptoStreams.git'
    CRYPTOSTREAMS_REPO_BRANCH = 'master'
    CRYPTOSTREAMS_REPO_PH4 = 'https://github.com/ph4r05/eacirc-streams.git'
    CRYPTOSTREAMS_REPO_BRANCH_PH4 = 'ph4'


class Database(object):
    # Name of the database. If you change this, you also have to change
    # name of the database in create_rtt_tables.sql script. It is discouraged.
    MYSQL_DB_NAME = "rtt"
    MYSQL_ROOT_USERNAME = "root"


class Storage(object):
    CHROOT_HOME_DIR = "/home"
    CHROOT_DATA_DIR = "data_files"
    CHROOT_CONF_DIR = "config_files"
    RTT_ADMIN_GROUP = "rtt_admin"
    SSH_DIR = ".ssh"
    AUTH_KEYS_FILE = "authorized_keys"
    STORE_CONFIG_FILE = "storage.ini"
    CLEAN_CACHE_SCRIPT = "clean_cache_storage.py"
    CLEAN_CACHE_LOG = "clean_cache_storage.log"
    COMMON_FILES_DIR = "common"
    CREDENTIALS_DIR = "credentials"
    MYSQL_STORAGE_USER = "rtt_storage"
    MYSQL_CREDENTIALS_FILE = "db_mysql_cred.ini"


class Frontend(object):
    RTT_ADMIN_GROUP = "rtt_admin"
    RTT_USER_GROUP = "rtt_user"
    CHROOT_RTT_FILES = "/rtt_frontend_files"
    CHROOT_RTT_USERS_HOME = "/home"
    FRONT_CONFIG_FILE = "frontend.ini"
    ADD_USER_SCRIPT = "add_rtt_user.py"
    SUBMIT_EXPERIMENT_SCRIPT = "submit_experiment.py"
    SUBMIT_EXPERIMENT_BINARY = "submit_experiment"
    CREDENTIALS_DIR = "credentials"
    COMMON_FILES_DIR = "common"
    MYSQL_FRONTEND_USER = "rtt_frontend"
    MYSQL_CREDENTIALS_FILE = "db_mysql_cred.ini"
    SSH_CREDENTIALS_FILE = "storage_ssh_cred.ini"
    SSH_CREDENTIALS_KEY = "storage_ssh_key"
    SSH_DIR = ".ssh"
    AUTH_KEYS_FILE = "authorized_keys"
    FSTAB_FILE = "/etc/fstab"
    CHROOT_DEBIAN_VERSION = "stretch"


class Backend(object):
    RTT_ADMIN_GROUP = "rtt_admin"
    BACKEND_CONFIG_FILE = "backend.ini"
    COMMON_FILES_DIR = "common"
    CACHE_CONFIG_DIR = "config_files"
    CACHE_DATA_DIR = "data_files"
    CREDENTIALS_DIR = "credentials"
    RTT_EXECUTION_DIR = "rtt_execution"
    RUN_JOBS_SCRIPT = "run_jobs.py"
    RUN_JOBS_LOG = "run_jobs.log"
    CLEAN_CACHE_SCRIPT = "clean_cache_backend.py"
    CLEAN_CACHE_LOG = "clean_cache_backend.log"

    POSTFIX_CFG_PATH = "/etc/postfix/main.cf"
    POSTFIX_HOST_OPT = "myhostname"

    MYSQL_BACKEND_USER = "rtt_backend"
    MYSQL_CREDENTIALS_FILE_INI = "db_mysql_cred.ini"
    MYSQL_CREDENTIALS_FILE_JSON = "db_mysql_cred.json"
    SSH_CREDENTIALS_FILE = "storage_ssh_cred.ini"
    SSH_CREDENTIALS_KEY = "storage_ssh_key"

    RTT_SETTINGS_JSON = "rtt-settings.json"
    RANDOMNESS_TESTING_TOOLKIT_SRC_DIR = "randomness-testing-toolkit"
    RANDOMNESS_TESTING_TOOLKIT_GIT_NAME = "randomness-testing-toolkit-master"
    RANDOMNESS_TESTING_TOOLKIT_ZIP_URL = \
        "https://github.com/crocs-muni/randomness-testing-toolkit/archive/master.zip"
    RTT_BINARY_PATH = "randomness-testing-toolkit"

    RTT_STATISTICAL_BATTERIES_SRC_DIR = "rtt-statistical-batteries"
    RTT_STATISTICAL_BATTERIES_GIT_NAME = "rtt-statistical-batteries-master"
    RTT_STATISTICAL_BATTERIES_ZIP_URL = \
        "https://github.com/crocs-muni/rtt-statistical-batteries/archive/master.zip"
    DIEHARDER_BINARY_PATH = "dieharder-src/install/bin/dieharder"
    NIST_STS_BINARY_PATH = "nist-sts-src/assess"
    TESTU01_BINARY_PATH = "testu01-src/binary/TestU01"

    NIST_STS_EXPERIMENTS_DIR = "nist-sts-src/experiments"
    NIST_STS_RESULT_DIR = "experiments/AlgorithmTesting"
    NIST_STS_TEMPLATES_DIR = "nist-sts-src/templates"

    EXEC_LOGS_TOP_DIR = "rtt_results/logs"
    # These values should be set in the default config in repo.
    # But better be sure.
    EXEC_LOGS_RUN_LOG_DIR = "run_logs"
    EXEC_LOGS_DIEHARDER_DIR = "dieharder"
    EXEC_LOGS_NIST_STS_DIR = "nist_sts"
    EXEC_LOGS_SMALLCRUSH_DIR = "tu01/small_crush"
    EXEC_LOGS_CRUSH_DIR = "tu01/crush"
    EXEC_LOGS_BIGCRUSH_DIR = "tu01/big_crush"
    EXEC_LOGS_RABBIT_DIR = "tu01/rabbit"
    EXEC_LOGS_ALPHABIT_DIR = "tu01/alphabit"
    EXEC_LOGS_BLOCKALPHABIT_DIR = "tu01/block_alphabit"

    EXEC_REPS_TOP_DIR = "rtt_results/reports"
    EXEC_REPS_MAIN_FILE = "rtt_results/main_table.txt"
    # These values should be set in the default config in repo.
    # But better be sure.
    EXEC_REPS_DIEHARDER_DIR = "dieharder"
    EXEC_REPS_NIST_STS_DIR = "nist_sts"
    EXEC_REPS_SMALLCRUSH_DIR = "tu01/small_crush"
    EXEC_REPS_CRUSH_DIR = "tu01/crush"
    EXEC_REPS_BIGCRUSH_DIR = "tu01/big_crush"
    EXEC_REPS_RABBIT_DIR = "tu01/rabbit"
    EXEC_REPS_ALPHABIT_DIR = "tu01/alphabit"
    EXEC_REPS_BLOCKALPHABIT_DIR = "tu01/block_alphabit"

    # Miscellaneous default settings here!
    NIST_MAIN_RESULT_DIR = "experiments/AlgorithmTesting"
