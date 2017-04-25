#! /usr/bin/python3

import sys
import re
import os
import configparser
from pwd import getpwnam
from common.clilogging import *
from common.rtt_deploy_utils import *
from common.rtt_constants import *

frontend_ini_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                 Frontend.FRONT_CONFIG_FILE)

try:
    if len(sys.argv) != 2:
        print("Usage: ./add_rtt_user.py <username>")
        sys.exit(1)
        
    frontend_ini = configparser.ConfigParser()
    try:
        frontend_ini.read(frontend_ini_file)
        Frontend.rtt_users_chroot = get_no_empty(frontend_ini, "Frontend", "RTT-Users-Chroot")
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    check_name_reg = re.compile(r'^[a-zA-Z0-9._-]+$')
    username = sys.argv[1]
    if check_name_reg.match(username) is None:
        raise BaseException("username can contain only characters a-z A-Z 0-9 . _ -")

    chroot_user_home = os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username)
    # Create user on main system
    exec_sys_call_check("useradd -d {} -g {} -s /bin/bash {}"
                        .format(chroot_user_home, Frontend.RTT_USER_GROUP, username))
    uid = getpwnam(username).pw_uid

    # Create user and user directories in chroot
    real_root = os.open("/", os.O_RDONLY)
    # Change this to dynamic value based on config.
    os.chroot(Frontend.rtt_users_chroot)
    exec_sys_call_check("useradd -d {} -g {} -u {} -s /bin/bash {}"
                        .format(chroot_user_home, Frontend.RTT_USER_GROUP, uid, username))
    create_dir(chroot_user_home, 0o700, own=username, grp=Frontend.RTT_USER_GROUP)
    create_dir(os.path.join(chroot_user_home, Frontend.SSH_DIR),
               0o700, own=username, grp=Frontend.RTT_USER_GROUP)
    create_file(os.path.join(chroot_user_home, Frontend.SSH_DIR, Frontend.AUTH_KEYS_FILE),
                0o600, own=username, grp=Frontend.RTT_USER_GROUP)
    os.fchdir(real_root)
    os.chroot(".")
    os.close(real_root)
    
    # Adding location of submit-experiment script into user PATH
    profile_file = "{}{}".format(Frontend.rtt_users_chroot,
                                 os.path.join(chroot_user_home, ".profile"))
    create_file(profile_file, mode=0o600, own=username, grp=Frontend.RTT_USER_GROUP)
    with open(profile_file, mode='a') as f:
        f.write("PATH=$PATH:{}\n".format(Frontend.CHROOT_RTT_FILES))
        f.write("umask 077\n")

    # Creating password for user
    exec_sys_call_check("passwd {}".format(username))

except BaseException as e:
    print("Error: {}".format(e))
