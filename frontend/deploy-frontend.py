#! /usr/bin/python3

import sys
import shutil
import grp
from common.clilogging import *
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "../deployment-settings.ini"


def rec_set_same_rights_to_g_as_o(path):
    new_perm = os.stat(path).st_mode & 0o707
    new_perm |= (new_perm >> 3)

    if os.path.isdir(path):
        for sub in os.listdir(path):
            rec_set_same_rights_to_g_as_o(os.path.join(path, sub))

    os.chmod(path, new_perm)


def main():
    deploy_cfg = configparser.ConfigParser()

    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        Frontend.address = get_no_empty(deploy_cfg, "Frontend", "IPv4-Address")
        Frontend.rtt_users_chroot = get_no_empty(deploy_cfg, "Frontend", "RTT-Users-Chroot")
        Frontend.chroot_deb_v = get_no_empty(deploy_cfg, "Frontend", "Chroot-debian-version")
        Frontend.fstab_file = get_no_empty(deploy_cfg, "Frontend", "Fstab-file")
        Frontend.ssh_config = get_no_empty(deploy_cfg, "Frontend", "SSH-Config")

        Database.address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        Database.mysql_port = get_no_empty(deploy_cfg, "Database", "MySQL-port")
        Database.ssh_port = get_no_empty(deploy_cfg, "Database", "SSH-Port")
        Database.ssh_root_user = get_no_empty(deploy_cfg, "Database", "SSH-Root-User")

        Storage.address = get_no_empty(deploy_cfg, "Storage", "IPv4-Address")
        Storage.ssh_root_user = get_no_empty(deploy_cfg, "Storage", "SSH-Root-User")
        Storage.acc_chroot = get_no_empty(deploy_cfg, "Storage", "Storage-Chroot")
        Storage.storage_user = get_no_empty(deploy_cfg, "Storage", "Storage-User")
        Storage.ssh_port = get_no_empty(deploy_cfg, "Storage-server", "SSH-port")

    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Sanity checks
    if not os.path.isabs(Frontend.rtt_users_chroot):
        print_error("Path is not absolute: {}".format(Frontend.rtt_users_chroot))
        sys.exit(1)

    if not os.path.isabs(Frontend.CHROOT_RTT_FILES):
        print_error("Path is not absolute: {}".format(Frontend.CHROOT_RTT_FILES))
        sys.exit(1)

    # Setting of paths used in this script
    Frontend.abs_rtt_files = \
        Frontend.rtt_users_chroot + Frontend.CHROOT_RTT_FILES
    Frontend.abs_config_ini = \
        os.path.join(Frontend.abs_rtt_files, Frontend.FRONT_CONFIG_FILE)
    Frontend.abs_submit_exp_script = \
        os.path.join(Frontend.abs_rtt_files, Frontend.SUBMIT_EXPERIMENT_SCRIPT)
    Frontend.abs_add_user_script = \
        os.path.join(Frontend.abs_rtt_files, Frontend.ADD_USER_SCRIPT)
    Frontend.submit_exp_base_name = \
        os.path.splitext(Frontend.SUBMIT_EXPERIMENT_SCRIPT)[0]
    Frontend.abs_cred_dir = \
        os.path.join(Frontend.abs_rtt_files, Frontend.CREDENTIALS_DIR)
    Frontend.rel_cred_dir = \
        os.path.join(Frontend.CHROOT_RTT_FILES, Frontend.CREDENTIALS_DIR)
    Frontend.abs_common_files = \
        os.path.join(Frontend.abs_rtt_files, Frontend.COMMON_FILES_DIR)
    Frontend.abs_cred_mysql_ini = \
        os.path.join(Frontend.abs_cred_dir, Frontend.MYSQL_CREDENTIALS_FILE)
    Frontend.rel_cred_mysql_ini = \
        os.path.join(Frontend.rel_cred_dir, Frontend.MYSQL_CREDENTIALS_FILE)
    Frontend.abs_cred_store_ini = \
        os.path.join(Frontend.abs_cred_dir, Frontend.SSH_CREDENTIALS_FILE)
    Frontend.rel_cred_store_ini = \
        os.path.join(Frontend.rel_cred_dir, Frontend.SSH_CREDENTIALS_FILE)
    Frontend.abs_cred_store_key = \
        os.path.join(Frontend.abs_cred_dir, Frontend.SSH_CREDENTIALS_KEY)
    Frontend.rel_cred_store_key = \
        os.path.join(Frontend.rel_cred_dir, Frontend.SSH_CREDENTIALS_KEY)

    try:
        update_env()

        # Adding rtt-admin group that is intended to manage
        # directories and files related to rtt without root access
        exec_sys_call_check("groupadd {}".format(Frontend.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        rtt_admin_grp_gid = grp.getgrnam(Frontend.RTT_ADMIN_GROUP).gr_gid
        # Adding group for users of rtt
        exec_sys_call_check("groupadd {}".format(Frontend.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        rtt_user_grp_gid = grp.getgrnam(Frontend.RTT_ADMIN_GROUP).gr_gid

        # Installing debootstrap used for ssh jail
        install_pkg("debootstrap")

        # Building chroot jail for rtt users
        create_dir(Frontend.rtt_users_chroot, 0o775, grp=Frontend.RTT_ADMIN_GROUP)
        # chroot jail should have sticky bit set!
        exec_sys_call_check("debootstrap {} {}"
                            .format(Frontend.chroot_deb_v, Frontend.rtt_users_chroot))
        with open(Frontend.fstab_file, "a") as f:
            f.write("proc {} proc defaults 0 0\n"
                    .format(os.path.join(Frontend.rtt_users_chroot, "proc")))
            f.write("sysfs {} sysfs defaults 0 0\n"
                    .format(os.path.join(Frontend.rtt_users_chroot, "sys")))

        exec_sys_call_check("mount proc {} -t proc"
                            .format(os.path.join(Frontend.rtt_users_chroot, "proc")))
        exec_sys_call_check("mount sysfs {} -t sysfs"
                            .format(os.path.join(Frontend.rtt_users_chroot, "sys")))
        shutil.copy("/etc/hosts", os.path.join(Frontend.rtt_users_chroot, "etc/hosts"))

        create_dir(Frontend.abs_rtt_files, 0o775, grp=Frontend.RTT_ADMIN_GROUP)
        create_dir(Frontend.abs_cred_dir, 0o770, grp=Frontend.RTT_ADMIN_GROUP)

        cred_mysql_db_password = get_rnd_pwd()
        create_file(Frontend.abs_cred_mysql_ini, 0o660, grp=Frontend.RTT_ADMIN_GROUP)
        cred_mysql_db_cfg = configparser.ConfigParser()
        cred_mysql_db_cfg.add_section("Credentials")
        cred_mysql_db_cfg.set("Credentials", "Username", Frontend.MYSQL_FRONTEND_USER)
        cred_mysql_db_cfg.set("Credentials", "Password", cred_mysql_db_password)
        with open(Frontend.abs_cred_mysql_ini, "w") as f:
            cred_mysql_db_cfg.write(f)

        cred_store_ssh_key_password = get_rnd_pwd()
        create_file(Frontend.abs_cred_store_ini, 0o660, grp=Frontend.RTT_ADMIN_GROUP)
        cred_store_ssh_cfg = configparser.ConfigParser()
        cred_store_ssh_cfg.add_section("Credentials")
        cred_store_ssh_cfg.set("Credentials", "Username", Storage.storage_user)
        cred_store_ssh_cfg.set("Credentials", "Private-key-file",
                               Frontend.rel_cred_store_key)
        cred_store_ssh_cfg.set("Credentials", "Private-key-password",
                               cred_store_ssh_key_password)
        with open(Frontend.abs_cred_store_ini, "w") as f:
            cred_store_ssh_cfg.write(f)

        exec_sys_call_check("ssh-keygen -q -b 2048 -t rsa -N {} -f {}"
                            .format(cred_store_ssh_key_password, Frontend.abs_cred_store_key))

        create_file(Frontend.abs_config_ini, 0o660, grp=Frontend.RTT_ADMIN_GROUP)
        frontend_ini_cfg = configparser.ConfigParser()
        frontend_ini_cfg.add_section("MySql-Database")
        frontend_ini_cfg.set("MySql-Database", "Name", Database.MYSQL_DB_NAME)
        frontend_ini_cfg.set("MySql-Database", "Address", Database.address)
        frontend_ini_cfg.set("MySql-Database", "Port", Database.mysql_port)
        frontend_ini_cfg.set("MySql-Database", "Credentials-file",
                             Frontend.rel_cred_mysql_ini)
        frontend_ini_cfg.add_section("Storage")
        frontend_ini_cfg.set("Storage", "Address", Storage.address)
        frontend_ini_cfg.set("Storage", "Port", Storage.ssh_port)
        frontend_ini_cfg.set("Storage", "Data-directory",
                             os.path.join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_DATA_DIR))
        frontend_ini_cfg.set("Storage", "Config-directory",
                             os.path.join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_CONF_DIR))
        frontend_ini_cfg.set("Storage", "Credentials-file", Frontend.rel_cred_store_ini)
        with open(Frontend.abs_cred_store_ini, "w") as f:
            frontend_ini_cfg.write(f)

        shutil.copy(CommonConst.FRONTEND_SUBMIT_EXPERIMENT_SCRIPT,
                    Frontend.abs_submit_exp_script)
        chmod_chown(Frontend.abs_submit_exp_script, 0o660, grp=Frontend.RTT_ADMIN_GROUP)

        shutil.copy(CommonConst.FRONTEND_ADD_USER_SCRIPT, Frontend.abs_add_user_script)
        chmod_chown(Frontend.abs_add_user_script, 0o660, grp=Frontend.RTT_ADMIN_GROUP)

        if os.path.exists(Frontend.abs_common_files):
            shutil.rmtree(Frontend.abs_common_files)
        shutil.copytree(CommonConst.COMMON_FILES_DIR, Frontend.abs_common_files)
        recursive_chmod_chown(Frontend.abs_common_files, mod_f=0o660, mod_d=0o770,
                              grp=Frontend.RTT_ADMIN_GROUP)

        # Entering chroot jail
        real_root = os.open("/", os.O_RDONLY)
        os.chroot(Frontend.rtt_users_chroot)

        # Adding groups - instead there should be two-way sync!!!
        exec_sys_call_check("groupadd -g {} {}".format(rtt_admin_grp_gid, Frontend.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        exec_sys_call_check("groupadd -g {} {}".format(rtt_user_grp_gid, Frontend.RTT_USER_GROUP),
                            acc_codes=[0, 9])

        # Installing needed packages inside jail
        update_env()
        install_pkg("python3-setuptools")
        install_pkg("python3-pip")
        install_pkg("libmysqlclient-dev")
        install_pkg("build-essential")
        install_pkg("libssl-dev")
        install_pkg("libffi-dev")
        install_pkg("python-dev")
        install_pkg("pyinstaller", pkg_mngr="pip3")
        install_pkg("mysqlclient", pkg_mngr="pip3")
        install_pkg("cryptography", pkg_mngr="pip3")
        install_pkg("paramiko", pkg_mngr="pip3")

        os.chdir(Frontend.CHROOT_RTT_FILES)
        exec_sys_call_check("pyinstaller -F {}".format(Frontend.SUBMIT_EXPERIMENT_SCRIPT))
        shutil.move("dist/{}".format(Frontend.submit_exp_base_name),
                    Frontend.SUBMIT_EXPERIMENT_BINARY)
        chmod_chown(Frontend.SUBMIT_EXPERIMENT_BINARY, 0o2775, grp=Frontend.RTT_ADMIN_GROUP)
        shutil.rmtree("dist")
        shutil.rmtree("build")
        shutil.rmtree("__pycache__")
        shutil.rmtree("{}.spec".format(Frontend.submit_exp_base_name))

        # Exiting chroot jail
        os.fchdir(real_root)
        os.chroot(".")
        os.close(real_root)

        sshd_config_append = "\n\n\n\n" \
                             "Match Group {0}\n" \
                             "\tChrootDirectory {1}\n" \
                             "\tPasswordAuthentication yes\n" \
                             "\tAllowTcpForwarding no\n" \
                             "\tPermitTunnel no\n" \
                             "\tX11Forwarding no\n" \
                             "\tAuthorizedKeysFile {2}\n" \
                             "\n".format(Frontend.RTT_USER_GROUP, Frontend.rtt_users_chroot,
                                         os.path.join(Frontend.rtt_users_chroot,
                                                      Frontend.CHROOT_RTT_USERS_HOME, "%u",
                                                      Frontend.SSH_DIR, Frontend.AUTH_KEYS_FILE))
        with open(Frontend.ssh_config, "a") as f:
            f.write(sshd_config_append)
            
        exec_sys_call_check("service sshd restart")

        # Register frontend at MySQL server
        exec_sys_call_check("ssh -p {0} {1}@{2} "
                            "\"mysql -u root -p -e "
                            "\\\"GRANT SELECT ON {3}.* TO '{4}'@'{5}' "
                            "IDENTIFIED BY '{6}'\\\"\""
                            .format(Database.ssh_port, Database.ssh_root_user, Database.address,
                                    Database.MYSQL_DB_NAME, Frontend.MYSQL_FRONTEND_USER,
                                    Frontend.address, cred_mysql_db_password))

        # Register frontend at the storage
        exec_sys_call_check("ssh -p {0} {1}@{2} "
                            "\"echo \\\"`{3}.pub`\\\" >> {4}\""
                            .format(Storage.ssh_port, Storage.ssh_root_user, Storage.address,
                                    Frontend.abs_cred_store_key,
                                    os.path.join(Storage.acc_chroot, Storage.CHROOT_HOME_DIR,
                                                 Storage.SSH_DIR, Storage.AUTH_KEYS_FILE)))

        # Everything should be okay now.

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))


if __name__ == "__main__":
    print_start("deploy-frontend")
    main()
    print_end()
