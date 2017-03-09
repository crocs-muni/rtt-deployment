#! /usr/bin/python3

import sys
import re
from pwd import getpwnam
from common.rtt_deploy_utils import *
from common.rtt_constants import *

try:
    if len(sys.argv) != 2:
        print("Usage: ./add-rtt-user.py <username>")
        sys.exit(0)

    check_name_reg = re.compile(r'^[a-zA-Z0-9._-]+$')
    username = sys.argv[1]
    if check_name_reg.match(username) is None:
        raise BaseException("username can contain only characters a-z A-Z 0-9 . _ -")

    # Create user on main system
    exec_sys_call_check("useradd -d {} -g {} -s /bin/bash {}"
                        .format(os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username),
                                Frontend.RTT_USER_GROUP, username))
    uid = getpwnam(username).pw_uid

    # Create user and user directories in chroot
    real_root = os.open("/", os.O_RDONLY)
    # Change this to dynamic value based on config.
    os.chroot("/rtt-users-chroot")
    exec_sys_call_check("useradd -d {} -g {} -u {} -s /bin/bash {}"
                        .format(os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username),
                                Frontend.RTT_USER_GROUP, uid, username))
    create_dir(os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username),
               0o700, own=username, grp=Frontend.RTT_USER_GROUP)
    create_dir(os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username, Frontend.SSH_DIR),
               0o700, own=username, grp=Frontend.RTT_USER_GROUP)
    create_file(os.path.join(Frontend.CHROOT_RTT_USERS_HOME, username, Frontend.SSH_DIR,
                             Frontend.AUTH_KEYS_FILE),
                0o600, own=username, grp=Frontend.RTT_USER_GROUP)
    os.fchdir(real_root)
    os.chroot(".")
    os.close(real_root)

    # Creating password for user
    exec_sys_call_check("passwd {}".format(username))

except BaseException as e:
    print("Error: {}".format(e))
