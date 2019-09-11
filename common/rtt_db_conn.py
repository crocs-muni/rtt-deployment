import configparser
import MySQLdb
import sys
from common.clilogging import *


# Will create connection to Mysql database
# Takes object main_cfg which is loaded
# configuration file. Config must contain
# section MySql-Database with fields
# Name - Database name
# Address - IP address or host
# Port - port
# Credentials-file - path to file with login information
#   Must contain section Credentials with
#   fields Username and Password

class MySQLParams(object):
    def __init__(self, host="127.0.0.1", port=3306, db="rtt", user="rtt", password=""):
        self.host = host
        self.port = port
        self.db = db
        self.user = user
        self.password = password


def mysql_load_params(main_cfg, host_override=None, port_override=None) -> MySQLParams:
    try:
        name = main_cfg.get('MySQL-Database', 'Name')
        address = main_cfg.get('MySQL-Database', 'Address')
        port = int(main_cfg.get('MySQL-Database', 'Port'))
        db_cred_file = main_cfg.get('MySQL-Database', 'Credentials-file')
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    cred_cfg = configparser.ConfigParser()

    try:
        cred_cfg.read(db_cred_file)
        if len(cred_cfg.sections()) == 0:
            print_error("Can't read credentials file: {}".format(db_cred_file))
            sys.exit(1)

        username = cred_cfg.get('Credentials', 'Username')
        password = cred_cfg.get('Credentials', 'Password')
    except BaseException as e:
        print_error("Credentials file: {}".format(e))
        sys.exit(1)

    if host_override:
        address = host_override
    if port_override:
        port = port_override
    return MySQLParams(host=address, port=port, db=name,
                       user=username, password=password)


def connect_mysql_db(params: MySQLParams):
    try:
        db = MySQLdb.connect(host=params.host, port=params.port, db=params.db,
                             user=params.user, passwd=params.password)
        return db
    except BaseException as e:
        print_error("Database connection: {}".format(e))
        sys.exit(1)


def create_mysql_db_conn(main_cfg, host_override=None, port_override=None):
    params = mysql_load_params(main_cfg, host_override=host_override, port_override=port_override)
    return connect_mysql_db(params)

