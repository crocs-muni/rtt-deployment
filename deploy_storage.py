#! /usr/bin/python3

import configparser
import shutil
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "deployment_settings.ini"


def main():
    deploy_cfg = configparser.ConfigParser()

    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        Database.address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        Database.ssh_root_user = get_no_empty(deploy_cfg, "Database", "SSH-Root-User")
        Database.ssh_port = get_no_empty(deploy_cfg, "Database", "SSH-Port")
        Database.mysql_port = get_no_empty(deploy_cfg, "Database", "MySql-Port")

        Storage.address = get_no_empty(deploy_cfg, "Storage", "IPv4-Address")
        Storage.rtt_dir = get_no_empty(deploy_cfg, "Storage", "RTT-Files-dir")
        Storage.ssh_config = get_no_empty(deploy_cfg, "Storage", "SSH-Config")
        Storage.acc_name = get_no_empty(deploy_cfg, "Storage", "Storage-User")
        Storage.acc_chroot = get_no_empty(deploy_cfg, "Storage", "Storage-Chroot")
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Sanity checks
    try:
        check_paths_abs({
            Storage.acc_chroot,
            Storage.CHROOT_HOME_DIR,
            Storage.rtt_dir
        })
        check_paths_rel({
            Storage.CHROOT_CONF_DIR,
            Storage.CHROOT_DATA_DIR,
            Storage.SSH_DIR,
            Storage.COMMON_FILES_DIR,
            Storage.CREDENTIALS_DIR
        })
        check_files_exists({
            Storage.ssh_config,
            CommonConst.STORAGE_CLEAN_CACHE
        })
    except AssertionError as e:
        print_error("Invalid configuration. {}".format(e))
        sys.exit(1)

    # Declaring all variables that
    # will be used in this script.
    # These are mostly absolute paths put
    # together from the settings.
    # Path related to storage user home
    Storage.home_dir = \
        "{}{}".format(Storage.acc_chroot, Storage.CHROOT_HOME_DIR)
    Storage.ssh_dir = \
        os.path.join(Storage.home_dir, Storage.SSH_DIR)
    Storage.authorized_keys_file = \
        os.path.join(Storage.ssh_dir, Storage.AUTH_KEYS_FILE)
    Storage.data_dir = \
        os.path.join(Storage.home_dir, Storage.CHROOT_DATA_DIR)
    Storage.config_dir = \
        os.path.join(Storage.home_dir, Storage.CHROOT_CONF_DIR)

    # Paths related to rtt files on server
    Storage.rtt_file_store_ini = \
        os.path.join(Storage.rtt_dir, Storage.STORE_CONFIG_FILE)
    Storage.rtt_file_clean_cache = \
        os.path.join(Storage.rtt_dir, Storage.CLEAN_CACHE_SCRIPT)
    Storage.rtt_file_clean_cache_log = \
        os.path.join(Storage.rtt_dir, Storage.CLEAN_CACHE_LOG)
    Storage.rtt_common_dir = \
        os.path.join(Storage.rtt_dir, Storage.COMMON_FILES_DIR)
    Storage.rtt_credentials_dir \
        = os.path.join(Storage.rtt_dir, Storage.CREDENTIALS_DIR)
    Storage.rtt_file_mysql_cred = \
        os.path.join(Storage.rtt_credentials_dir, Storage.MYSQL_CREDENTIALS_FILE)

    try:
        # Creating sftp jail for account
        # Adding rtt-admin group that is intended to manage
        # directories and files related to rtt without root access
        exec_sys_call_check("groupadd {}".format(Storage.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        # Adding user for access
        exec_sys_call_check("useradd -d {} -s /usr/sbin/nologin {}"
                            .format(Storage.CHROOT_HOME_DIR, Storage.acc_name),
                            acc_codes=[0, 9])

        # Configuring ssh server
        sshd_config_append = "\n\n\n\n" \
                             "Match User {0}\n" \
                             "\tChrootDirectory {1}\n" \
                             "\tForceCommand internal-sftp\n" \
                             "\tAllowTcpForwarding no\n" \
                             "\tPermitTunnel no\n" \
                             "\tX11Forwarding no\n" \
                             "\tAuthorizedKeysFile {1}{2}\n" \
                             "\tPasswordAuthentication no\n" \
                             "\n".format(Storage.acc_name, Storage.acc_chroot,
                                         os.path.join(Storage.CHROOT_HOME_DIR,
                                                      Storage.SSH_DIR, Storage.AUTH_KEYS_FILE))

        with open(Storage.ssh_config, "a") as f:
            f.write(sshd_config_append)

        exec_sys_call_check("service sshd restart")

        # Creating sftp jail for accessing storage
        create_dir(Storage.acc_chroot, 0o755)
        create_dir(Storage.home_dir, 0o700,
                   own=Storage.acc_name, grp=Storage.acc_name)
        create_dir(Storage.ssh_dir, 0o700,
                   own=Storage.acc_name, grp=Storage.acc_name)
        create_dir(Storage.data_dir, 0o700,
                   own=Storage.acc_name, grp=Storage.acc_name)
        create_dir(Storage.config_dir, 0o700,
                   own=Storage.acc_name, grp=Storage.acc_name)
        create_file(Storage.authorized_keys_file,
                    0o600, own=Storage.acc_name, grp=Storage.acc_name)

        # Creating directory for rtt files on the server
        create_dir(Storage.rtt_dir, 0o2770, grp=Storage.RTT_ADMIN_GROUP)

        # Set ACL on top directory - ensures all new files will have correct permissions
        exec_sys_call_check("setfacl -R -d -m g::rwx {}".format(Storage.rtt_dir))
        exec_sys_call_check("setfacl -R -d -m o::--- {}".format(Storage.rtt_dir))

        create_dir(Storage.rtt_credentials_dir, 0o2770,
                   grp=Storage.RTT_ADMIN_GROUP)

        # Copying script for cache cleaning
        shutil.copy(CommonConst.STORAGE_CLEAN_CACHE, Storage.rtt_file_clean_cache)
        chmod_chown(Storage.rtt_file_clean_cache, 0o770,
                    grp=Storage.RTT_ADMIN_GROUP)

        # Copying common scripts into directory
        # with rtt files
        if os.path.exists(Storage.rtt_common_dir):
            shutil.rmtree(Storage.rtt_common_dir)

        shutil.copytree(CommonConst.COMMON_FILES_DIR, Storage.rtt_common_dir)
        recursive_chmod_chown(Storage.rtt_common_dir, mod_f=0o660, mod_d=0o2770,
                              grp=Storage.RTT_ADMIN_GROUP)

        # Creating configuration file for storage server scripts
        ini_cfg = configparser.ConfigParser()
        ini_cfg.add_section("MySQL-Database")
        ini_cfg.set("MySQL-Database", "Name", Database.MYSQL_DB_NAME)
        ini_cfg.set("MySQL-Database", "Address", Database.address)
        ini_cfg.set("MySQL-Database", "Port", Database.mysql_port)
        ini_cfg.set("MySQL-Database", "Credentials-file", Storage.rtt_file_mysql_cred)
        ini_cfg.add_section("Local-cache")
        ini_cfg.set("Local-cache", "Data-directory", Storage.data_dir)
        ini_cfg.set("Local-cache", "Config-directory", Storage.config_dir)
        with open(Storage.rtt_file_store_ini, "w") as f:
            ini_cfg.write(f)

        # Creating credentials file for database access
        cred_db_password = get_rnd_pwd()
        cred_cfg = configparser.ConfigParser()
        cred_cfg.add_section("Credentials")
        cred_cfg.set("Credentials", "Username", Storage.MYSQL_STORAGE_USER)
        cred_cfg.set("Credentials", "Password", cred_db_password)
        with open(Storage.rtt_file_mysql_cred, "w") as f:
            cred_cfg.write(f)

        # Installing required packages
        install_debian_pkg("libmysqlclient-dev")
        install_debian_pkg("python3-pip")
        install_debian_pkg("python3-cryptography")
        install_debian_pkg("python3-paramiko")

        install_python_pkg("mysqlclient")

        # This can be done only after installing cryptography and paramiko
        from common.rtt_registration import register_db_user

        register_db_user(Database.ssh_root_user, Database.address, Database.ssh_port,
                         Storage.MYSQL_STORAGE_USER, cred_db_password, Storage.address,
                         Database.MYSQL_ROOT_USERNAME, Database.MYSQL_DB_NAME,
                         priv_select=True)

        # Adding new job to cron - cache cleaning script
        add_cron_job(Storage.rtt_file_clean_cache,
                     Storage.rtt_file_store_ini,
                     Storage.rtt_file_clean_cache_log)

        # All configured here.

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))


if __name__ == "__main__":
    print_start("deploy_storage")
    main()
    print_end()
