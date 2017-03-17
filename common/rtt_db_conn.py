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
def create_mysql_db_conn(main_cfg):
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

    try:
        db = MySQLdb.connect(host=address, port=port, db=name,
                             user=username, passwd=password)
        return db
    except BaseException as e:
        print_error("Database connection: {}".format(e))
        sys.exit(1)
