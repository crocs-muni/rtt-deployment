# File containing constants used in deployment.
# Change them only if you have good reason to do so :)


class CommonConst(object):
    COMMON_FILES_DIR = "../common"
    CREATE_TABLES_SCRIPT = "db-files/create-rtt-tables.sql"
    STORAGE_CLEAN_CACHE = "storage-files/clean-cache.py"


class Database(object):
    # Name of the database. If you change this, you also have to change
    # name of the database in create-rtt-tables.sql script. It is discouraged.
    MYSQL_DB_NAME = "rtt"


class Storage(object):
    CHROOT_HOME_DIR = "/home"
    CHROOT_DATA_DIR = "data-files"
    CHROOT_CONF_DIR = "config-files"
    RTT_ADMIN_GROUP = "rtt-admin"
    SSH_DIR = ".ssh"
    AUTH_KEYS_DIR = "authorized_keys"
    STORE_CONFIG_FILE = "storage.ini"
    CLEAN_CACHE_SCRIPT = "clean-cache.py"
    CLEAN_CACHE_LOG = "clean-cache.log"
    COMMON_CODE_DIR = "common"
    CREDENTIALS_DIR = "credentials"
    MYSQL_STORAGE_USER = "rtt_storage"
    MYSQL_CREDENTIALS_FILE = "mysql-db-cred.ini"


class Frontend(object):
    CHROOT_RTT_FILES = "/rtt-files"
    RTT_ADMIN_GROUP = "rtt-admin"
    RTT_USER_GROUP = "rtt-user"
