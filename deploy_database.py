#! /usr/bin/python3

import configparser
import subprocess
import argparse
import traceback
import os
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################

# noinspection SqlDialectInspection,SqlNoDataSourceInspection
sql_file_setup = """
# Make sure that NOBODY can access the server without a password
UPDATE mysql.user SET Password=PASSWORD('{{{MYSQL_PASS}}}') WHERE User='root';
# Kill the anonymous users
DELETE FROM mysql.user WHERE User='';
# disallow remote login for root
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
# Kill off the demo database
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
# Make our changes take effect
FLUSH PRIVILEGES;
"""

sql_config_file = """[client]
password="{{{MYSQL_PASS}}}"
"""


def set_cfg_value(key, value, cfg_path, sep="="):
    sed_string = r"s_\({}\s*\){}\s*.*_\1= {}_".format(key, sep, value)
    rval = subprocess.call(["sed", "-i", sed_string, cfg_path])
    if rval != 0:
        raise EnvironmentError("Executing sed command \'{}\', error code: {}"
                               .format(sed_string, rval))


def comment_cfg_line(line_content, cfg_path):
    sed_string = r"s_\(.*{}.*\)_# \1_".format(line_content)
    rval = subprocess.call(["sed", "-i", sed_string, cfg_path])
    if rval != 0:
        raise EnvironmentError("Executing sed command \'{}\', error code: {}"
                               .format(sed_string, rval))


def main():
    # Reading configuration
    parser = argparse.ArgumentParser(description='DB deployment')
    parser.add_argument('--config', dest='config', default='deployment_settings.ini',
                        help='Path to deployment_settings.ini')
    args = parser.parse_args()
    deploy_cfg_file = args.config

    deploy_cfg = configparser.ConfigParser()
    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        Database.address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        Database.mysql_port = get_no_empty(deploy_cfg, "Database", "MySQL-port")
        Database.mysql_cfg_path = get_no_empty(deploy_cfg, "Database", "MySQL-config-file")
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Sanity checks
    try:
        check_files_exists({
            CommonConst.CREATE_TABLES_SCRIPT
        })
    except AssertionError as e:
        print_error("Invalid configuration. {}".format(e))
        sys.exit(1)

    sec_fpath = CommonConst.PASSWD_MYSQL
    tmp_sql = '/tmp/setup.sql'
    try:
        install_debian_pkgs(["acl", "sudo", "wget", "unzip", "rsync"])
        install_debian_pkg("mysql-server")
        exec_sys_call_check("service mysql start")

        backup_file(sec_fpath, remove=True)
        mysql_pass = get_rnd_pwd()
        with create_file_wperms(sec_fpath, mask=0o600, mode='w') as fh:
            fh.write(mysql_pass)

        # Configuring environment
        # exec_sys_call_check("mysql_secure_installation")
        sql_file_setup_data = sql_file_setup.replace('{{{MYSQL_PASS}}}', mysql_pass)
        with create_file_wperms(tmp_sql, mask=0o600, mode='w') as fh:
            fh.write(sql_file_setup_data)

        exec_sys_call_check("mysql --no-auto-rehash -u {}"
                            .format(Database.MYSQL_ROOT_USERNAME),
                            stdin=open(tmp_sql, "r"))

        set_cfg_value("bind-address", Database.address, Database.mysql_cfg_path)
        set_cfg_value("port", Database.mysql_port, Database.mysql_cfg_path)
        comment_cfg_line("skip-external-locking", Database.mysql_cfg_path)

        # Restarting mysql service
        exec_sys_call_check("service mysql restart")

        backup_file(CommonConst.CONF_MYSQL, remove=True)
        with create_file_wperms(CommonConst.CONF_MYSQL, mask=0o600, mode='w') as fh:
            fh.write(sql_config_file.replace('{{{MYSQL_PASS}}}', mysql_pass))

        print_info("Creating database scheme: {}".format(Database.MYSQL_DB_NAME))
        exec_sys_call_check("mysql --no-auto-rehash -u {}"
                            .format(Database.MYSQL_ROOT_USERNAME),
                            stdin=open(CommonConst.CREATE_TABLES_SCRIPT, "r"))

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))
        traceback.print_exc()

    finally:
        try_fnc(lambda: os.unlink(tmp_sql))


if __name__ == "__main__":
    print_start("deploy_database")
    main()
    print_end()
