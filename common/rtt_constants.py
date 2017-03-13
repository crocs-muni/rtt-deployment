# File containing constants used in deployment.
# Change them only if you have good reason to do so :)


class CommonConst(object):
    COMMON_FILES_DIR = "../common"
    CREATE_TABLES_SCRIPT = "db_files/create_rtt_tables.sql"
    STORAGE_CLEAN_CACHE = "storage_files/clean_cache.py"
    FRONTEND_SUBMIT_EXPERIMENT_SCRIPT = "frontend_files/submit_experiment.py"
    FRONTEND_ADD_USER_SCRIPT = "frontend_files/add_rtt_user.py"


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
    CLEAN_CACHE_SCRIPT = "clean_cache.py"
    CLEAN_CACHE_LOG = "clean_cache.log"
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
    CHROOT_DEBIAN_VERSION = "jessie"

