#! /usr/bin/python3

import configparser
import argparse
import grp
import traceback
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################


def main():
    parser = argparse.ArgumentParser(description='Web view deployment')
    parser.add_argument('--docker', dest='docker', action='store_const', const=True, default=False,
                        help='Docker deployment')
    parser.add_argument('--ph4', dest='ph4', action='store_const', const=True, default=False,
                        help='Use Ph4 forks of tools')
    parser.add_argument('--local-db', dest='local_db', action='store_const', const=True, default=False,
                        help='DB server is on the same machine')
    parser.add_argument('--mysql-pass', dest='mysql_pass', action='store_const', const=True, default=False,
                        help='DB password to use')
    parser.add_argument('--mysql-pass-file', dest='mysql_pass_file', action='store_const', const=True, default=False,
                        help='DB password file to use')
    parser.add_argument('--config', dest='config', default='deployment_settings.ini',
                        help='Path to deployment_settings.ini')
    args = parser.parse_args()
    deploy_cfg_file = args.config

    deploy_cfg = configparser.ConfigParser()
    current_dir = os.path.abspath(os.path.curdir)

    try:
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        Database.address = get_no_empty(deploy_cfg, "Database", "IPv4-Address")
        Database.mysql_port = get_no_empty(deploy_cfg, "Database", "MySQL-port")
        Database.ssh_port = get_no_empty(deploy_cfg, "Database", "SSH-Port")
        Database.ssh_root_user = get_no_empty(deploy_cfg, "Database", "SSH-Root-User")

        Storage.address = get_no_empty(deploy_cfg, "Storage", "IPv4-Address")
        Storage.ssh_root_user = get_no_empty(deploy_cfg, "Storage", "SSH-Root-User")
        Storage.acc_chroot = get_no_empty(deploy_cfg, "Storage", "Storage-Chroot")
        Storage.storage_user = get_no_empty(deploy_cfg, "Storage", "Storage-User")
        Storage.ssh_port = get_no_empty(deploy_cfg, "Storage", "SSH-port")

        RTTWeb.address = get_no_empty(deploy_cfg, "Web", "IPv4-Address")

    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Sanity checks
    try:
        check_files_exists({
            RTTWeb.APACHE_CONFIG,
            CommonConst.FRONTEND_SUBMIT_EXPERIMENT_SCRIPT
        })
    except AssertionError as e:
        print_error("Invalid configuration. {}".format(e))
        sys.exit(1)

    try:
        install_debian_pkgs([
            "acl", "sudo", "wget", "unzip", "rsync", "openssh-client",
            "python3-pip", "python3-venv", "apache2", "libapache2-mod-wsgi-py3", "certbot"
        ])

        python_packages = [
            "django", "pyinstaller", "filelock", "jsonpath-ng", "booltest", "booltest-rtt"
        ]

        install_python_pkg("pip", no_cache=False)
        install_python_pkgs(python_packages)

        # Adding rtt-admin group that is intended to manage
        # directories and files related to rtt without root access
        exec_sys_call_check("groupadd {}".format(Frontend.RTT_ADMIN_GROUP),
                            acc_codes=[0, 9])
        rtt_admin_grp_gid = grp.getgrnam(Frontend.RTT_ADMIN_GROUP).gr_gid
        # Adding group for users of rtt
        exec_sys_call_check("groupadd {}".format(Frontend.RTT_USER_GROUP),
                            acc_codes=[0, 9])
        rtt_user_grp_gid = grp.getgrnam(Frontend.RTT_USER_GROUP).gr_gid

        wusr = 'www-data'
        wgrp = 'www-data'

        # Lets encrypt http-auth
        os.makedirs('/var/www/html/.well-known/acme-challenge', 0o777, True)
        recursive_chmod_chown('/var/www/html/.well-known', 0o660, 0o771, wusr, wgrp)

        dst_dir = RTTWeb.RTT_WEB_PATH
        # if os.path.exists(dst_dir):
        #     shutil.rmtree(dst_dir)
        #
        # rttweb_repo = RTTWeb.WEB_REPO_PH4 if args.ph4 else RTTWeb.WEB_REPO
        # exec_sys_call_check("git clone --recursive %s %s" % (rttweb_repo, dst_dir))
        os.chdir(dst_dir)

        # exec_sys_call_check("python3 -m venv %s" % RTTWeb.RTT_WEB_ENV)
        # pip3_venv = os.path.abspath(os.path.join(RTTWeb.RTT_WEB_ENV, 'bin', 'pip3'))
        # install_python_pkgs(python_packages, pip3=pip3_venv)

        # Credentials
        from common.rtt_registration import register_db_user
        from common.rtt_registration import add_authorized_key_to_server
        from common.rtt_registration import get_db_reg_command

        credsdir = os.path.join(dst_dir, RTTWeb.RTT_WEB_CREDENTIALS)
        if os.path.exists(credsdir):
            shutil.rmtree(credsdir)
        os.makedirs(credsdir, 0o777, True)

        sec_key = get_rnd_pwd()
        sec_file = os.path.join(credsdir, RTTWeb.RTT_WEB_CREDENTIALS_SECRET_KEY)
        with create_file_wperms(sec_file, mask=0o640, mode='w') as fh:
            fh.write(sec_key)
        chmod_chown(sec_file, 0o640, own=wusr, grp=wgrp)

        # Register user for results preview
        cred_mysql_db_password = get_rnd_pwd()
        creds_db_path = os.path.join(credsdir, RTTWeb.MYSQL_RTT_CONFIG)
        creds_db_path2 = os.path.join(credsdir, RTTWeb.MYSQL_RTT_CONFIG2)
        write_db_credentials(RTTWeb.MYSQL_RTT_USER, cred_mysql_db_password, creds_db_path)
        shutil.copy(creds_db_path, creds_db_path2)
        chmod_chown(creds_db_path, 0o640, own=wusr, grp=wgrp)
        chmod_chown(creds_db_path2, 0o640, own=wusr, grp=wgrp)

        db_def_passwd = get_mysql_password_args(args)
        db_addr_from = RTTWeb.address if not args.docker else '%'
        register_db_user(Database.ssh_root_user, Database.address, Database.ssh_port,
                         RTTWeb.MYSQL_RTT_USER, cred_mysql_db_password, db_addr_from,
                         Database.MYSQL_ROOT_USERNAME, Database.MYSQL_DB_NAME,
                         priv_select=True, priv_insert=True,  # insert for submit_experiment
                         db_def_passwd=db_def_passwd, db_no_pass=args.local_db)

        # Register web user
        creds_mysql_web_pass = get_rnd_pwd()
        creds_db_path = os.path.join(credsdir, RTTWeb.WEB_DB_CONFIG)
        write_db_credentials_web(RTTWeb.MYSQL_USER, creds_mysql_web_pass, RTTWeb.MYSQL_DB, creds_db_path,
                                 address=Database.address)
        chmod_chown(creds_db_path, 0o640, own=wusr, grp=wgrp)
        register_db_user(Database.ssh_root_user, Database.address, Database.ssh_port,
                         RTTWeb.MYSQL_USER, creds_mysql_web_pass, db_addr_from,
                         Database.MYSQL_ROOT_USERNAME, RTTWeb.MYSQL_DB,
                         priv_select=True, priv_insert=True, priv_update=True, priv_delete=True,
                         db_def_passwd=db_def_passwd, db_no_pass=args.local_db)

        # Register machine to storage
        rtt_ssh_pkey = os.path.join(credsdir, RTTWeb.SSH_CREDENTIALS_KEY)
        key_pwd = get_rnd_pwd()
        exec_sys_call_check("ssh-keygen -q -b 2048 -t rsa -N {} -f {}".format(key_pwd, rtt_ssh_pkey))
        chmod_chown(rtt_ssh_pkey, 0o640, own=wusr, grp=wgrp)
        chmod_chown(rtt_ssh_pkey + ".pub", 0o640, own=wusr, grp=wgrp)
        with open(rtt_ssh_pkey + ".pub") as f:
            pub_key = f.read().rstrip()

        rtt_ssh_cfg = os.path.join(credsdir, RTTWeb.SSH_CREDENTIALS_FILE)
        write_ssh_credentials(Storage.storage_user, key_pwd, rtt_ssh_pkey, rtt_ssh_cfg)
        chmod_chown(rtt_ssh_cfg, 0o640, own=wusr, grp=wgrp)

        authorized_keys_path = "{}{}".format(Storage.acc_chroot, os.path.join(Storage.CHROOT_HOME_DIR, Storage.SSH_DIR,
                                                                              Storage.AUTH_KEYS_FILE))
        add_authorized_key_to_server(Storage.ssh_root_user, Storage.address, Storage.ssh_port, pub_key, authorized_keys_path)

        # Submit experiment
        submdir = os.path.join(dst_dir, RTTWeb.RTT_WEB_SUBMIT_EXP)
        if os.path.exists(submdir):
            shutil.rmtree(submdir)
        os.makedirs(submdir, 0o771, True)
        os.chdir(submdir)

        #  - create frontend.ini
        frontend_ini_cfg = configparser.ConfigParser()
        frontend_ini_cfg.add_section("MySQL-Database")
        frontend_ini_cfg.set("MySQL-Database", "Name", Database.MYSQL_DB_NAME)
        frontend_ini_cfg.set("MySQL-Database", "Address", Database.address)
        frontend_ini_cfg.set("MySQL-Database", "Port", Database.mysql_port)
        frontend_ini_cfg.set("MySQL-Database", "Credentials-file", os.path.abspath(creds_db_path))
        frontend_ini_cfg.add_section("Storage")
        frontend_ini_cfg.set("Storage", "Address", Storage.address)
        frontend_ini_cfg.set("Storage", "Port", Storage.ssh_port)
        frontend_ini_cfg.set("Storage", "Data-directory", os.path.join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_DATA_DIR))
        frontend_ini_cfg.set("Storage", "Config-directory", os.path.join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_CONF_DIR))
        frontend_ini_cfg.set("Storage", "Credentials-file", os.path.abspath(rtt_ssh_cfg))
        with open(Frontend.FRONT_CONFIG_FILE, "w") as f:
            frontend_ini_cfg.write(f)

        shutil.copy(os.path.join(current_dir, CommonConst.FRONTEND_SUBMIT_EXPERIMENT_SCRIPT),
                    Frontend.SUBMIT_EXPERIMENT_SCRIPT)
        chmod_chown(Frontend.SUBMIT_EXPERIMENT_SCRIPT, 0o660, own=wusr, grp=wgrp)

        if os.path.exists(Frontend.COMMON_FILES_DIR):
            shutil.rmtree(Frontend.COMMON_FILES_DIR)

        shutil.copytree(os.path.join(current_dir, CommonConst.COMMON_FILES_DIR), Frontend.COMMON_FILES_DIR)
        recursive_chmod_chown(Frontend.COMMON_FILES_DIR, mod_f=0o660, mod_d=0o2770, own=wusr, grp=wgrp)

        submit_exp_base_name = os.path.splitext(Frontend.SUBMIT_EXPERIMENT_SCRIPT)[0]
        exec_sys_call_check("pyinstaller -F {}".format(Frontend.SUBMIT_EXPERIMENT_SCRIPT))
        shutil.move("dist/{}".format(submit_exp_base_name), Frontend.SUBMIT_EXPERIMENT_BINARY)
        chmod_chown(Frontend.SUBMIT_EXPERIMENT_BINARY, 0o2775, own=wusr, grp=wgrp)
        shutil.rmtree("dist")
        shutil.rmtree("build")
        shutil.rmtree("__pycache__")
        os.remove("{}.spec".format(submit_exp_base_name))

        # Chown all
        print("Chmoding...")
        exec_sys_call_check("chown -R \"%s:%s\" %s" % (wusr, wgrp, dst_dir))

        # Apache config file
        shutil.copy(
            os.path.join(current_dir, RTTWeb.APACHE_CONFIG),
            '/etc/apache2/sites-available/000-default.conf'
        )

        # Restart apache
        exec_sys_call_check("service apache2 restart")
        if not args.docker:
            service_enable("apache2.service")

        # Everything should be okay now.

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))
        traceback.print_exc()


if __name__ == "__main__":
    print_start("deploy_frontend")
    main()
    print_end()
