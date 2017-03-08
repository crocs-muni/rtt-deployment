#! /usr/bin/python3

import sys
import shutil
from common.clilogging import *
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "../deployment-settings.ini"


def main():
    deploy_cfg = configparser.ConfigParser()

    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        db_address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        db_ssh_user = get_no_empty(deploy_cfg, "Database", "SSH-Root-User")
        db_ssh_port = get_no_empty(deploy_cfg, "Database", "SSH-Port")
        db_mysql_port = get_no_empty(deploy_cfg, "Database", "MySql-Port")

        store_address = get_no_empty(deploy_cfg, "Storage", "IPv4-Address")
        store_rtt_dir = get_no_empty(deploy_cfg, "Storage", "RTT-Files-dir")
        store_ssh_config = get_no_empty(deploy_cfg, "Storage", "SSH-Config")
        store_acc_name = get_no_empty(deploy_cfg, "Storage", "Storage-User")
        store_acc_chroot = get_no_empty(deploy_cfg, "Storage", "Storage-Chroot")
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Sanity checks
    if not os.path.isabs(store_acc_chroot):
        print_error("Path is not absolute: {}".format(store_acc_chroot))
        sys.exit(1)
    if not os.path.isabs(Storage.CHROOT_HOME_DIR):
        print_error("Path is not absolute: {}".format(Storage.CHROOT_HOME_DIR))
        sys.exit(1)
    if not os.path.isabs(store_rtt_dir):
        print_error("Path is not absolute: {}".format(store_rtt_dir))
        sys.exit(1)
    if os.path.isabs(Storage.CHROOT_CONF_DIR):
        print_error("Path is not relative: {}".format(Storage.CHROOT_CONF_DIR))
        sys.exit(1)
    if os.path.isabs(Storage.CHROOT_DATA_DIR):
        print_error("Path is not relative: {}".format(Storage.CHROOT_DATA_DIR))
        sys.exit(1)
    if not os.path.exists(store_ssh_config):
        print_error("File does not exist: {}".format(store_ssh_config))
        sys.exit(1)

    try:
        # Creating sftp jail for account
        # Adding rtt-admin group that is intended to manage
        # directories and files related to rtt without root access
        exec_sys_call_check("groupadd {}".format(Storage.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        # Adding user for access
        exec_sys_call_check("useradd -d {} -s /usr/sbin/nologin {}"
                            .format(Storage.CHROOT_HOME_DIR, store_acc_name)
                            , acc_codes=[0, 9])

        # Configuring ssh server
        sshd_config_append = "\n\n\n\n" \
                             "Match User {0}\n" \
                             "\tChrootDirectory {1}\n" \
                             "\tForceCommand internal-sftp\n" \
                             "\tAllowTcpForwarding no\n" \
                             "\tPermitTunnel no\n" \
                             "\tX11Forwarding no\n" \
                             "\tAuthorizedKeysFile {1}{2}/{3}/{4}\n" \
                             "\tPasswordAuthentication no\n" \
                             "\n".format(store_acc_name, store_acc_chroot, Storage.CHROOT_HOME_DIR,
                                         Storage.SSH_DIR, Storage.AUTH_KEYS_DIR)

        with open(store_ssh_config, "a") as f:
            f.write(sshd_config_append)

        exec_sys_call_check("service sshd restart")

        abs_home_dir = "{}{}".format(store_acc_chroot, Storage.CHROOT_HOME_DIR)
        abs_ssh_dir = os.path.join(abs_home_dir, Storage.SSH_DIR)
        abs_authorized_keys_file = os.path.join(abs_ssh_dir, Storage.AUTH_KEYS_DIR)
        abs_data_dir = os.path.join(abs_home_dir, Storage.CHROOT_DATA_DIR)
        abs_config_dir = os.path.join(abs_home_dir, Storage.CHROOT_DATA_DIR)

        # Creating directories and setting
        # correct access rights inside sftp jail
        create_dir(store_acc_chroot, 0o755)
        create_dir(abs_home_dir, 0o700, own=store_acc_name, grp=store_acc_name)
        create_dir(abs_ssh_dir, 0o700, own=store_acc_name, grp=store_acc_name)
        create_dir(abs_data_dir, 0o700, own=store_acc_name, grp=store_acc_name)
        create_dir(abs_config_dir, 0o700, own=store_acc_name, grp=store_acc_name)
        create_file(abs_authorized_keys_file, 0o600, own=store_acc_name, grp=store_acc_name)

        # Creating and copying rtt files and scripts
        # Creating directories
        abs_rtt_ini_files_dir = os.path.join(store_rtt_dir, "ini-files")
        abs_rtt_credentials_dir = os.path.join(store_rtt_dir, "credentials")

        create_dir(store_rtt_dir, 0o770, grp=Storage.RTT_ADMIN_GROUP)
        create_dir(abs_rtt_ini_files_dir, 0o770, grp=Storage.RTT_ADMIN_GROUP)
        create_dir(abs_rtt_credentials_dir, 0o770, grp=Storage.RTT_ADMIN_GROUP)

        # Copy and create needed files
        abs_rtt_file_mysql_cred = os.path.join(abs_rtt_credentials_dir, "mysql-db-cred.ini")
        abs_rtt_file_store_ini = os.path.join(abs_rtt_ini_files_dir, "storage.ini")
        abs_rtt_file_clean_cache = os.path.join(store_rtt_dir, "clean-cache.py")
        abs_rtt_file_clean_cache_logfile = os.path.join(store_rtt_dir, "clean-cache.log")
        abs_rtt_common_dir = os.path.join(store_rtt_dir, "common")

        create_file(abs_rtt_file_mysql_cred, 0o660, grp=Storage.RTT_ADMIN_GROUP)
        cred_db_username = "rtt_storage"
        cred_db_password = get_rnd_pwd()
        cred_cfg = configparser.ConfigParser()
        cred_cfg.add_section("Credentials")
        cred_cfg.set("Credentials", "Username", cred_db_username)
        cred_cfg.set("Credentials", "Password", cred_db_password)
        cred_cfg_file = open(abs_rtt_file_mysql_cred, "w")
        cred_cfg.write(cred_cfg_file)
        cred_cfg_file.close()
        
        create_file(abs_rtt_file_store_ini, 0o660, grp=Storage.RTT_ADMIN_GROUP)
        ini_cfg = configparser.ConfigParser()
        ini_cfg.add_section("MySql-Database")
        ini_cfg.set("MySql-Database", "Name", Database.MYSQL_DB_NAME)
        ini_cfg.set("MySql-Database", "Address", db_address)
        ini_cfg.set("MySql-Database", "Port", db_mysql_port)
        ini_cfg.set("MySql-Database", "Credentials-file", abs_rtt_file_mysql_cred)
        ini_cfg.add_section("Local-cache")
        ini_cfg.set("Local-cache", "Data-directory", abs_data_dir)
        ini_cfg.set("Local-cache", "Config-directory", abs_config_dir)
        ini_cfg_file = open(abs_rtt_file_store_ini, "w")
        ini_cfg.write(ini_cfg_file)
        ini_cfg_file.close()

        shutil.copy("storage-files/clean-cache.py", abs_rtt_file_clean_cache)
        chmod_chown(abs_rtt_file_clean_cache, 0o770, grp=Storage.RTT_ADMIN_GROUP)

        if os.path.exists(abs_rtt_common_dir):
            shutil.rmtree(abs_rtt_common_dir)

        shutil.copytree("../common", abs_rtt_common_dir)
        recursive_chmod_chown(abs_rtt_common_dir, mod_f=0o660, mod_d=0o770,
                              grp=Storage.RTT_ADMIN_GROUP)

        # Installing required packages
        update_env()
        install_pkg("libmysqlclient-dev")
        install_pkg("python3-pip")
        install_pkg("mysqlclient", pkg_mngr="pip3")

        # Registering this storage at database server - creating new db user
        exec_sys_call_check("ssh -p {0} {1}@{2} "
                            "\"mysql -u root -p -e "
                            "\\\"GRANT SELECT ON {3}.* TO '{4}'@'{5}' "
                            "IDENTIFIED BY '{6}'\\\"\""
                            .format(db_ssh_port, db_ssh_user, db_address, 
                                    Database.MYSQL_DB_NAME, cred_db_username,
                                    store_address, cred_db_password))

        # Adding new job to cron - cache cleaning script
        cron_tmp_filename = "cron.tmp"
        cron_entry = "\n* * * * *    " \
                     "/usr/bin/flock " \
                     "/var/tmp/clean-cache.lock {} {} >> {} 2>&1\n\n" \
                     .format(abs_rtt_file_clean_cache,
                             abs_rtt_file_store_ini,
                             abs_rtt_file_clean_cache_logfile)

        cron_tmp_file = open(cron_tmp_filename, "w")
        exec_sys_call_check("crontab -l", stdout=cron_tmp_file, acc_codes=[0, 1])
        cron_tmp_file.write(cron_entry)
        cron_tmp_file.close()

        exec_sys_call_check("crontab {}".format(cron_tmp_filename))
        os.remove(cron_tmp_filename)

        # All configured here.

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))


if __name__ == "__main__":
    print_start("deploy-storage")
    main()
    print_end()
