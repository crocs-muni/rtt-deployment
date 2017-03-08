# File containing constants used in deployment.
# Change them only if you have good reason to do so :)


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


class Frontend(object):
    CHROOT_RTT_FILES = "/rtt-files"
    RTT_ADMIN_GROUP = "rtt-admin"
    RTT_USER_GROUP = "rtt-user"
