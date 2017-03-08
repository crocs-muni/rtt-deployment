# File containing constants used in deployment.
# Change them only if you have good reason to do so :)


class CommonConst(object):
    COMMON_FILES_DIR = "../common"
    CREATE_TABLES_SCRIPT = "db-files/create-rtt-tables.sql"
    STORAGE_CLEAN_CACHE = "storage-files/clean-cache.py"
    FRONTEND_SUBMIT_EXPERIMENT_SCRIPT = "frontend-files/submit-experiment.py"
    FRONTEND_ADD_USER_SCRIPT = "frontend-files/add-rtt-user.py"


class Database(object):
    # Name of the database. If you change this, you also have to change
    # name of the database in create-rtt-tables.sql script. It is discouraged.
    MYSQL_DB_NAME = "rtt"


class Storage(object):
    CHROOT_HOME_DIR = "/home"
    CHROOT_DATA_DIR = "data-files"
    CHROOT_CONF_DIR = "config-files"
    RTT_ADMIN_GROUP = "rtt_admin"
    SSH_DIR = ".ssh"
    AUTH_KEYS_FILE = "authorized_keys"
    STORE_CONFIG_FILE = "storage.ini"
    CLEAN_CACHE_SCRIPT = "clean-cache.py"
    CLEAN_CACHE_LOG = "clean-cache.log"
    COMMON_FILES_DIR = "common"
    CREDENTIALS_DIR = "credentials"
    MYSQL_STORAGE_USER = "rtt_storage"
    MYSQL_CREDENTIALS_FILE = "db-mysql-cred.ini"


class Frontend(object):
    RTT_ADMIN_GROUP = "rtt_admin"
    RTT_USER_GROUP = "rtt_user"
    CHROOT_RTT_FILES = "/rtt-files"
    CHROOT_RTT_USERS_HOME = "/home"
    FRONT_CONFIG_FILE = "frontend.ini"
    ADD_USER_SCRIPT = "add-rtt-user.py"
    SUBMIT_EXPERIMENT_SCRIPT = "submit-experiment.py"
    SUBMIT_EXPERIMENT_BINARY = "submit-experiment"
    CREDENTIALS_DIR = "credentials"
    COMMON_FILES_DIR = "common"
    MYSQL_FRONTEND_USER = "rtt_frontend"
    MYSQL_CREDENTIALS_FILE = "db-mysql-cred.ini"
    SSH_CREDENTIALS_FILE = "storage-ssh-cred.ini"
    SSH_CREDENTIALS_KEY = "storage-ssh-key"
    SSH_DIR = ".ssh"
    AUTH_KEYS_FILE = "authorized_keys"

