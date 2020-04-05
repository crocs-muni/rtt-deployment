#! /usr/bin/python3

import configparser
import json
import shutil
import subprocess
import argparse
import traceback
from os.path import join
from common.rtt_deploy_utils import *
from common.rtt_constants import *

################################
# Global variables declaration #
################################
deploy_cfg_file = "deployment_settings.ini"


def main():
    parser = argparse.ArgumentParser(description='Worker deployment')
    parser.add_argument('--metacentrum', dest='metacentrum', action='store_const', const=True, default=False,
                        help='Metacetrum deployment')
    parser.add_argument('--db-passwd', dest='db_passwd',
                        help='DB password to use, if given, skips DB registration')
    parser.add_argument('--ssh-passphrase', dest='ssh_passphrase',
                        help='SSH passphrase to use to protect the private key')
    parser.add_argument('--ssh-priv', dest='ssh_priv',
                        help='SSH private key to use instead of generated one, has to have .pub counterpart')
    parser.add_argument('--no-db-reg', dest='no_db_reg', action='store_const', const=True, default=False,
                        help='Skip MySQL user registration')
    parser.add_argument('--no-ssh-reg', dest='no_ssh_reg', action='store_const', const=True, default=False,
                        help='Skip SSH key registration at storage server')
    parser.add_argument('--no-email', dest='no_email', action='store_const', const=True, default=False,
                        help='Skip email registration')
    parser.add_argument('--no-cron', dest='no_cron', action='store_const', const=True, default=False,
                        help='Skip cron setup')
    parser.add_argument('--ph4-rtt', dest='ph4_rtt', action='store_const', const=True, default=False,
                        help='Use Ph4r05 fork of RTT - required for metacentrum')
    parser.add_argument('--config', dest='config', default='deployment_settings.ini',
                        help='Path to deployment_settings.ini')
    parser.add_argument('backend_id', default=None,
                        help='Config file')
    args = parser.parse_args()
    wbare = not args.metacentrum
    if args.metacentrum:
        args.ph4_rtt = True

    # Get path to main config from console
    if not args.backend_id:
        print("\nUsage: ./deploy_backend.py <backend-id>\n")
        print("<backend-id> must be entered according to config with deployment settings.\n"
              "             Configuration file \"{}\" must\n"
              "             contain one and only one section named\n"
              "             \"Backend-<backend-id>\"\n".format(deploy_cfg_file))
        sys.exit(1)

    deploy_cfg = configparser.ConfigParser()

    try:
        deploy_cfg_file = args.config
        deploy_cfg.read(deploy_cfg_file)
        if len(deploy_cfg.sections()) == 0:
            raise FileNotFoundError("can't read: {}".format(deploy_cfg_file))

        backend_sec = "Backend-" + args.backend_id

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
        sys.exit(1)

    # Sanity checks
    try:
        check_paths_abs({
            Backend.rtt_files_dir
        })
        check_paths_rel({
            Backend.COMMON_FILES_DIR,
            Backend.CACHE_DATA_DIR,
            Backend.CACHE_CONFIG_DIR,
            Backend.CREDENTIALS_DIR,
            Backend.RTT_EXECUTION_DIR,
            Backend.RANDOMNESS_TESTING_TOOLKIT_SRC_DIR,
            Backend.RTT_STATISTICAL_BATTERIES_SRC_DIR,
        })
        check_files_exists({
            CommonConst.BACKEND_CLEAN_CACHE_SCRIPT,
            CommonConst.BACKEND_RUN_JOBS_SCRIPT
        })
    except AssertionError as e:
        print_error("Invalid configuration. {}".format(e))
        sys.exit(1)

    os.makedirs(Backend.rtt_files_dir, 0o771, True)

    # Defined absolute paths to directories and files
    Backend.rand_test_tool_src_dir = \
        join(Backend.rtt_files_dir, Backend.RANDOMNESS_TESTING_TOOLKIT_SRC_DIR)
    Backend.rand_test_tool_dl_zip = \
        join(Backend.rtt_files_dir, Backend.RANDOMNESS_TESTING_TOOLKIT_GIT_NAME + ".zip")
    Backend.stat_batt_src_dir = \
        join(Backend.rtt_files_dir, Backend.RTT_STATISTICAL_BATTERIES_SRC_DIR)
    Backend.stat_batt_dl_zip = \
        join(Backend.rtt_files_dir, Backend.RTT_STATISTICAL_BATTERIES_GIT_NAME + ".zip")
    Backend.common_files_dir = \
        join(Backend.rtt_files_dir, Backend.COMMON_FILES_DIR)
    Backend.cache_conf_dir = \
        join(Backend.rtt_files_dir, Backend.CACHE_CONFIG_DIR)
    Backend.cache_data_dir = \
        join(Backend.rtt_files_dir, Backend.CACHE_DATA_DIR)
    Backend.credentials_dir = \
        join(Backend.rtt_files_dir, Backend.CREDENTIALS_DIR)
    Backend.rtt_exec_dir = \
        join(Backend.rtt_files_dir, Backend.RTT_EXECUTION_DIR)
    Backend.rtt_exec_nist_exp_dir = \
        join(Backend.rtt_exec_dir, Backend.NIST_STS_EXPERIMENTS_DIR)
    Backend.rtt_exec_nist_temp_dir = \
        join(Backend.rtt_exec_dir, Backend.NIST_STS_TEMPLATES_DIR)
    Backend.ssh_store_pkey = \
        join(Backend.credentials_dir, Backend.SSH_CREDENTIALS_KEY)
    Backend.ssh_store_pubkey = \
        join(Backend.credentials_dir, Backend.SSH_CREDENTIALS_KEY + ".pub")
    Backend.run_jobs_path = \
        join(Backend.rtt_files_dir, Backend.RUN_JOBS_SCRIPT)
    Backend.clean_cache_path = \
        join(Backend.rtt_files_dir, Backend.CLEAN_CACHE_SCRIPT)
    Backend.rtt_binary_path = \
        join(Backend.rtt_exec_dir, os.path.basename(Backend.RTT_BINARY_PATH))
    Backend.mysql_cred_ini_path = \
        join(Backend.credentials_dir, Backend.MYSQL_CREDENTIALS_FILE_INI)
    Backend.mysql_cred_json_path = \
        join(Backend.credentials_dir, Backend.MYSQL_CREDENTIALS_FILE_JSON)
    Backend.ssh_cred_ini_path = \
        join(Backend.credentials_dir, Backend.SSH_CREDENTIALS_FILE)
    Backend.config_ini_path = \
        join(Backend.rtt_files_dir, Backend.BACKEND_CONFIG_FILE)
    wgrp = Backend.RTT_ADMIN_GROUP

    try:
        # Adding rtt-admin group that is intended to manage
        # directories and files related to rtt without root access
        exec_sys_call_check("groupadd {}".format(Backend.RTT_ADMIN_GROUP), acc_codes=[0, 9])

        # Remove directories that was created previously
        if os.path.exists(Backend.rtt_files_dir):
            shutil.rmtree(Backend.rtt_files_dir)

        # Create and copy needed files into rtt-files
        create_dir(Backend.rtt_files_dir, 0o2770, grp=wgrp)

        # Set ACL on top directory - ensures all new files will have correct permissions
        exec_sys_call_check("setfacl -R -d -m g::rwx {}".format(Backend.rtt_files_dir))
        exec_sys_call_check("setfacl -R -d -m o::--- {}".format(Backend.rtt_files_dir))

        create_dir(Backend.cache_conf_dir, 0o2770, grp=wgrp)
        create_dir(Backend.cache_data_dir, 0o2770, grp=wgrp)
        create_dir(Backend.credentials_dir, 0o2770, grp=wgrp)
        create_dir(Backend.rtt_exec_dir, 0o2770, grp=wgrp)

        shutil.copy(CommonConst.BACKEND_CLEAN_CACHE_SCRIPT, Backend.clean_cache_path)
        chmod_chown(Backend.clean_cache_path, 0o770, grp=wgrp)

        shutil.copy(CommonConst.BACKEND_RUN_JOBS_SCRIPT, Backend.run_jobs_path)
        chmod_chown(Backend.run_jobs_path, 0o770, grp=wgrp)

        if os.path.exists(Backend.common_files_dir):
            shutil.rmtree(Backend.common_files_dir)

        shutil.copytree(CommonConst.COMMON_FILES_DIR, Backend.common_files_dir)
        recursive_chmod_chown(Backend.common_files_dir, mod_f=0o660, mod_d=0o2770, grp=wgrp)

        # Install packages
        install_debian_pkg("wget")
        install_debian_pkg("rsync")
        install_debian_pkg("unzip")
        install_debian_pkg("sudo")
        install_debian_pkg("acl")
        install_debian_pkg("git")
        install_debian_pkg("mailutils")
        if not args.no_email:
            install_debian_pkg("postfix")

        install_debian_pkg("libmysqlcppconn-dev")
        install_debian_pkg_at_least_one(["default-libmysqlclient-dev", "libmysqlclient-dev"])
        install_debian_pkg("python3-pip")
        install_debian_pkg("python3-cryptography")
        install_debian_pkg("python3-paramiko")

        install_python_pkg("mysqlclient")
        install_python_pkg("sarge")
        install_python_pkg("requests")
        install_python_pkg("shellescape")
        install_python_pkg("coloredlogs")
        install_python_pkg("filelock")
        install_python_pkg("sshtunnel")
        install_python_pkg("booltest")
        install_python_pkg("booltest-rtt")

        # Get current versions of needed tools from git
        # Statistical batteries
        if os.path.exists(Backend.stat_batt_src_dir):
            shutil.rmtree(Backend.stat_batt_src_dir)

        exec_sys_call_check("wget {} -O {}".format(Backend.RTT_STATISTICAL_BATTERIES_ZIP_URL,
                                                   Backend.stat_batt_dl_zip))
        exec_sys_call_check("unzip {} -d {}".format(Backend.stat_batt_dl_zip,
                                                    Backend.rtt_files_dir))
        os.remove(Backend.stat_batt_dl_zip)
        os.rename(join(Backend.rtt_files_dir, Backend.RTT_STATISTICAL_BATTERIES_GIT_NAME),
                  Backend.stat_batt_src_dir)

        # Randomness testing toolkit
        if os.path.exists(Backend.rand_test_tool_src_dir):
            shutil.rmtree(Backend.rand_test_tool_src_dir)

        if args.ph4_rtt:
            exec_sys_call_check("git clone --recursive https://github.com/ph4r05/randomness-testing-toolkit.git %s" % Backend.rand_test_tool_src_dir)

        else:
            exec_sys_call_check("wget {} -O {}".format(Backend.RANDOMNESS_TESTING_TOOLKIT_ZIP_URL,
                                                       Backend.rand_test_tool_dl_zip))
            exec_sys_call_check("unzip {} -d {}".format(Backend.rand_test_tool_dl_zip,
                                                        Backend.rtt_files_dir))
            os.remove(Backend.rand_test_tool_dl_zip)
            os.rename(join(Backend.rtt_files_dir, Backend.RANDOMNESS_TESTING_TOOLKIT_GIT_NAME),
                      Backend.rand_test_tool_src_dir)

        # Change into directory rtt-src and rtt-stat-batt-src and call make and ./INSTALL respectively.
        current_dir = os.path.abspath(os.path.curdir)

        # Build statistical batteries
        os.chdir(Backend.stat_batt_src_dir)

        exec_sys_call_check("./INSTALL")
        recursive_chmod_chown(Backend.stat_batt_src_dir, mod_f=0o660, mod_d=0o2770, grp=wgrp)
        chmod_chown(Backend.DIEHARDER_BINARY_PATH, 0o770)
        chmod_chown(Backend.NIST_STS_BINARY_PATH, 0o770)
        chmod_chown(Backend.TESTU01_BINARY_PATH, 0o770)
        build_static_dieharder(Backend.stat_batt_src_dir)
        os.chdir(Backend.stat_batt_src_dir)

        # Build randomness testing toolkit
        os.chdir(Backend.rand_test_tool_src_dir)
        rtt_env = None
        if args.ph4_rtt:
            lib_data = copy_rtt_libs(Backend.rand_test_tool_src_dir)
            rtt_env = get_rtt_build_env(Backend.rand_test_tool_src_dir, lib_data)

        exec_sys_call_check("make -j2", env=rtt_env, acc_codes=[0, 1, 2])
        recursive_chmod_chown(Backend.rand_test_tool_src_dir, mod_f=0o660, mod_d=0o2770, grp=wgrp)
        chmod_chown(Backend.RTT_BINARY_PATH, 0o770)

        # Build finished, go into original directory
        os.chdir(current_dir)

        # Link RTT binary into execution directory
        os.symlink(join(Backend.rand_test_tool_src_dir, Backend.RTT_BINARY_PATH),
                   Backend.rtt_binary_path)

        # Copy needed directories and files into execution directory
        shutil.copytree(join(Backend.stat_batt_src_dir, Backend.NIST_STS_TEMPLATES_DIR),
                        join(Backend.rtt_exec_dir,
                             os.path.basename(Backend.NIST_STS_TEMPLATES_DIR)))
        shutil.copytree(join(Backend.stat_batt_src_dir, Backend.NIST_STS_EXPERIMENTS_DIR),
                        join(Backend.rtt_exec_dir,
                             os.path.basename(Backend.NIST_STS_EXPERIMENTS_DIR)))

        rtt_settings = {
            "toolkit-settings": {
                "logger": {
                    "dir-prefix": join(Backend.rtt_files_dir, Backend.EXEC_LOGS_TOP_DIR),
                    "run-log-dir": Backend.EXEC_LOGS_RUN_LOG_DIR,
                    "dieharder-dir": Backend.EXEC_LOGS_DIEHARDER_DIR,
                    "nist-sts-dir": Backend.EXEC_LOGS_NIST_STS_DIR,
                    "tu01-smallcrush-dir": Backend.EXEC_LOGS_SMALLCRUSH_DIR,
                    "tu01-crush-dir": Backend.EXEC_LOGS_CRUSH_DIR,
                    "tu01-bigcrush-dir": Backend.EXEC_LOGS_BIGCRUSH_DIR,
                    "tu01-rabbit-dir": Backend.EXEC_LOGS_RABBIT_DIR,
                    "tu01-alphabit-dir": Backend.EXEC_LOGS_ALPHABIT_DIR,
                    "tu01-blockalphabit-dir": Backend.EXEC_LOGS_BLOCKALPHABIT_DIR
                },
                "result-storage": {
                    "file": {
                        "main-file": join(Backend.rtt_files_dir, Backend.EXEC_REPS_MAIN_FILE),
                        "dir-prefix": join(Backend.rtt_files_dir, Backend.EXEC_REPS_TOP_DIR),
                        "dieharder-dir": Backend.EXEC_REPS_DIEHARDER_DIR,
                        "nist-sts-dir": Backend.EXEC_REPS_NIST_STS_DIR,
                        "tu01-smallcrush-dir": Backend.EXEC_REPS_SMALLCRUSH_DIR,
                        "tu01-crush-dir": Backend.EXEC_REPS_CRUSH_DIR,
                        "tu01-bigcrush-dir": Backend.EXEC_REPS_BIGCRUSH_DIR,
                        "tu01-rabbit-dir": Backend.EXEC_REPS_RABBIT_DIR,
                        "tu01-alphabit-dir": Backend.EXEC_REPS_ALPHABIT_DIR,
                        "tu01-blockalphabit-dir": Backend.EXEC_REPS_ALPHABIT_DIR
                    },
                    "mysql-db": {
                        "address": Database.address,
                        "port": Database.mysql_port,
                        "name": Database.MYSQL_DB_NAME,
                        "credentials-file": Backend.mysql_cred_json_path
                    }
                },
                "binaries": {
                    "nist-sts": join(Backend.stat_batt_src_dir, Backend.NIST_STS_BINARY_PATH),
                    "dieharder": join(Backend.stat_batt_src_dir, Backend.DIEHARDER_BINARY_PATH),
                    "testu01": join(Backend.stat_batt_src_dir, Backend.TESTU01_BINARY_PATH)
                },
                "miscellaneous": {
                    "nist-sts": {
                        "main-result-dir": join(Backend.rtt_exec_dir, Backend.NIST_MAIN_RESULT_DIR)
                    }
                },
                "execution": {
                    "max-parallel-tests": int(Backend.exec_max_tests),
                    "test-timeout-seconds": int(Backend.exec_test_timeout)
                },
                "booltest": {
                    "default-cli": "--no-summary --json-out --log-prints --top 128 --no-comb-and --only-top-comb --only-top-deg --no-term-map --topterm-heap --topterm-heap-k 256 --best-x-combs 512",
                    "strategies": [
                        {
                            "name": "v1",
                            "cli": "",
                            "variations": [
                                {
                                    "bl": [128, 256, 384, 512],
                                    "deg": [1, 2, 3],
                                    "cdeg": [1, 2, 3],
                                    "exclusions": []
                                }
                            ]
                        },
                        {
                            "name": "halving",
                            "cli": "--halving",
                            "variations": [
                                {
                                    "bl": [128, 256, 384, 512],
                                    "deg": [1, 2, 3],
                                    "cdeg": [1, 2, 3],
                                    "exclusions": []
                                }
                            ]
                        }
                    ]
                }
            }
        }
        with open(join(Backend.rtt_exec_dir, Backend.RTT_SETTINGS_JSON), "w") as f:
            json.dump(rtt_settings, f, indent=4)

        # Get email configuration

        # Add configuration to file
        # inet_interface = loopback-only
        # inet_protocol = ipv4
        if not args.no_email:
            with open(Backend.POSTFIX_CFG_PATH) as mail_cfg:
                for line in mail_cfg.readlines():
                    if line.startswith(Backend.POSTFIX_HOST_OPT):
                        Backend.sender_email = line.split(sep=" = ")[1]

        if not args.no_email and Backend.sender_email is None:
            print_error("can't find option {} in file {}"
                        .format(Backend.POSTFIX_CFG_PATH, Backend.POSTFIX_HOST_OPT))
            sys.exit(1)

        Backend.sender_email = ("root@" + Backend.sender_email) if not args.no_email else 'rtt@crocs.fi.muni.cz'

        # Create backend configuration file
        backend_ini_cfg = configparser.ConfigParser()
        backend_ini_cfg.add_section("MySQL-Database")
        backend_ini_cfg.set("MySQL-Database", "Address", Database.address)
        backend_ini_cfg.set("MySQL-Database", "Port", Database.mysql_port)
        backend_ini_cfg.set("MySQL-Database", "Name", Database.MYSQL_DB_NAME)
        backend_ini_cfg.set("MySQL-Database", "Credentials-file",
                            Backend.mysql_cred_ini_path)
        backend_ini_cfg.add_section("Local-cache")
        backend_ini_cfg.set("Local-cache", "Data-directory", Backend.cache_data_dir)
        backend_ini_cfg.set("Local-cache", "Config-directory", Backend.cache_conf_dir)
        backend_ini_cfg.add_section("Backend")
        backend_ini_cfg.set("Backend", "Sender-email", Backend.sender_email)
        backend_ini_cfg.add_section("Storage")
        backend_ini_cfg.set("Storage", "Address", Storage.address)
        backend_ini_cfg.set("Storage", "Port", Storage.ssh_port)
        backend_ini_cfg.set("Storage", "Data-directory",
                            join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_DATA_DIR))
        backend_ini_cfg.set("Storage", "Config-directory",
                            join(Storage.CHROOT_HOME_DIR, Storage.CHROOT_CONF_DIR))
        backend_ini_cfg.set("Storage", "Credentials-file", Backend.ssh_cred_ini_path)
        backend_ini_cfg.add_section("RTT-Binary")
        backend_ini_cfg.set("RTT-Binary", "Binary-path",
                            Backend.rtt_binary_path)
        try:
            booltest_rtt_binary = subprocess.check_output(['which', 'booltest_rtt']).decode('utf8').strip()
        except Exception as e:
            booltest_rtt_binary = ""

        backend_ini_cfg.set("RTT-Binary", "booltest-rtt-path",
                            booltest_rtt_binary)  # TODO: auto-detect
        with open(Backend.config_ini_path, "w") as f:
            backend_ini_cfg.write(f)

        from common.rtt_registration import register_db_user
        from common.rtt_registration import add_authorized_key_to_server
        from common.rtt_registration import get_db_reg_command

        # Register machine to database
        db_pwd = args.db_passwd if args.db_passwd else get_rnd_pwd()
        cred_mysql_db_ini = configparser.ConfigParser()
        cred_mysql_db_ini.add_section("Credentials")
        cred_mysql_db_ini.set("Credentials", "Username", Backend.MYSQL_BACKEND_USER)
        cred_mysql_db_ini.set("Credentials", "Password", db_pwd)
        with open(Backend.mysql_cred_ini_path, "w") as f:
            cred_mysql_db_ini.write(f)

        cred_mysql_db_json = {
            "credentials": {
                "username": Backend.MYSQL_BACKEND_USER,
                "password": db_pwd
            }
        }
        with open(Backend.mysql_cred_json_path, "w") as f:
            json.dump(cred_mysql_db_json, f, indent=4)

        post_install_info = []
        db_addr_from = Backend.address if wbare else '%'
        if not args.no_db_reg:
            register_db_user(Database.ssh_root_user, Database.address, Database.ssh_port,
                             Backend.MYSQL_BACKEND_USER, db_pwd, db_addr_from,
                             Database.MYSQL_ROOT_USERNAME, Database.MYSQL_DB_NAME,
                             priv_select=True, priv_insert=True, priv_update=True)
        else:
            sql = get_db_reg_command(username=Database.MYSQL_ROOT_USERNAME, password=None,
                                     db_name=Database.MYSQL_DB_NAME, reg_name=Backend.MYSQL_BACKEND_USER,
                                     reg_address=db_addr_from, reg_pwd=db_pwd,
                                     priv_select=True, priv_insert=True, priv_update=True,
                                     db_host=Database.address, db_port=Database.ssh_port)
            post_install_info.append('* DB user not registered to the DB server. Make sure the following user:password has access: ')
            post_install_info.append(sql + '\n')

        # Register machine to storage
        key_pwd = args.ssh_passphrase if args.ssh_passphrase else get_rnd_pwd()
        if args.ssh_priv:
            shutil.copy(args.ssh_priv, Backend.ssh_store_pkey)
            shutil.copy(args.ssh_priv + '.pub', Backend.ssh_store_pubkey)
        else:
            exec_sys_call_check("ssh-keygen -q -b 2048 -t rsa -N {} -f {}"
                                .format(key_pwd, Backend.ssh_store_pkey))
        chmod_chown(Backend.ssh_store_pkey, 0o660, grp=wgrp)
        chmod_chown(Backend.ssh_store_pubkey, 0o660, grp=wgrp)
        with open(Backend.ssh_store_pubkey) as f:
            pub_key = f.read().rstrip()

        cred_ssh_store_ini = configparser.ConfigParser()
        cred_ssh_store_ini.add_section("Credentials")
        cred_ssh_store_ini.set("Credentials", "Username", Storage.storage_user)
        cred_ssh_store_ini.set("Credentials", "Private-key-file", Backend.ssh_store_pkey)
        cred_ssh_store_ini.set("Credentials", "Private-key-password", key_pwd)
        with open(Backend.ssh_cred_ini_path, "w") as f:
            cred_ssh_store_ini.write(f)

        authorized_keys_path = "{}{}".format(Storage.acc_chroot, join(Storage.CHROOT_HOME_DIR, Storage.SSH_DIR, Storage.AUTH_KEYS_FILE))
        if args.no_ssh_reg:
            post_install_info.append('* Register the following key on the storage server at %s' % (authorized_keys_path,))
            post_install_info.append('%s' % (pub_key,))
            post_install_info.append('')

        else:
            add_authorized_key_to_server(Storage.ssh_root_user, Storage.address, Storage.ssh_port,
                                         pub_key, authorized_keys_path)

        # Add cron jobs for cache cleaning and job running script
        if not args.no_cron:
            add_cron_job(Backend.clean_cache_path, Backend.config_ini_path,
                         join(Backend.rtt_files_dir, Backend.CLEAN_CACHE_LOG))

            add_cron_job(Backend.run_jobs_path, Backend.config_ini_path,
                         join(Backend.rtt_files_dir, Backend.RUN_JOBS_LOG))

        if post_install_info:
            print('='*80)
            for x in post_install_info:
                print(x)

    except BaseException as e:
        print_error("{}. Fix error and run the script again.".format(e))
        traceback.print_exc()


if __name__ == "__main__":
    print_start("deploy_backend")
    main()
    print_end()
