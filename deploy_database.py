#! /usr/bin/python3

import configparser
import subprocess
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "deployment_settings.ini"


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

    try:
        install_debian_pkg("mysql-server")

        # Configuring environment
        exec_sys_call_check("mysql_secure_installation")
        set_cfg_value("bind-address", Database.address, Database.mysql_cfg_path)
        set_cfg_value("port", Database.mysql_port, Database.mysql_cfg_path)
        comment_cfg_line("skip-external-locking", Database.mysql_cfg_path)

        # Restarting mysql service
        exec_sys_call_check("/etc/init.d/mysql restart")

        print_info("Creating database scheme: {}".format(Database.MYSQL_DB_NAME))
        print_info("You may be asked password for database user: {}"
                   .format(Database.MYSQL_ROOT_USERNAME))
        exec_sys_call_check("mysql -u {} -p".format(Database.MYSQL_ROOT_USERNAME),
                            stdin=open(CommonConst.CREATE_TABLES_SCRIPT, "r"))

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))


if __name__ == "__main__":
    print_start("deploy_database")
    main()
    print_end()
