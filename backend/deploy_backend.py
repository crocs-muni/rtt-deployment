#! /usr/bin/python3

import configparser
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "../deployment_settings.ini"


def main():
    if len(sys.argv) != 2:
        print("\nUsage: ./deploy_backend.py <backend-id>\n")
        print("<backend-id> must be entered according to config with deployment settings.\n"
              "             Configuration file \"{}\" must\n"
              "             contain one and only one section named\n"
              "             \"Backend-<backend-id>\"\n".format(deploy_cfg_file))
        sys.exit(1)

    deploy_cfg = configparser.ConfigParser()

    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        backend_sec = "Backend-" + sys.argv[1]

        Backend.address = get_no_empty(deploy_cfg, backend_sec, "IPv4-Address")
        Backend.rtt_files_dir = get_no_empty(deploy_cfg, backend_sec, "RTT-Files-dir")
        Backend.exec_max_tests = get_no_empty(deploy_cfg, backend_sec, "Maximum-parallel-tests")
        Backend.exec_test_timeout = get_no_empty(deploy_cfg, backend_sec, "Maximum-seconds-per-test")

        Database.address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        Database.mysql_port = get_no_empty(deploy_cfg, "Database", "MySQL-port")
        Database.ssh_port = get_no_empty(deploy_cfg, "Database", "SSH-Port")
        Database.ssh_root_user = get_no_empty(deploy_cfg, "Database", "SSH-Root-User")

        Storage.address = get_no_empty(deploy_cfg, "Storage", "IPv4-Address")
        Storage.ssh_root_user = get_no_empty(deploy_cfg, "Storage", "SSH-Root-User")
        Storage.acc_chroot = get_no_empty(deploy_cfg, "Storage", "Storage-Chroot")
        Storage.storage_user = get_no_empty(deploy_cfg, "Storage", "Storage-User")
        Storage.ssh_port = get_no_empty(deploy_cfg, "Storage", "SSH-port")

    except Exception as e:
        print_error("Configuration file: {}".format(e))


if __name__ == "__main__":
    print_start("deploy_backend")
    main()
    print_end()