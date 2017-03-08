#! /usr/bin/python3

import sys
import re
from pwd import getpwnam
from common.rtt_deploy_utils import *

rtt_user_grp = "rtt-user"

try:
    if len(sys.argv) != 2:
        print("Usage: ./add-rtt-user.py <username>")
        sys.exit(0)

    check_name_reg = re.compile(r'^[a-zA-Z0-9._-]+$')
    username = sys.argv[1]
    if check_name_reg.match(username) is None:
        raise BaseException("username can contain only characters a-z A-Z 0-9 . _ -")

    # Create user on main system
    exec_sys_call_check("useradd -d /home/{0} -g rtt-user -s /bin/bash {0}"
                        .format(username))
    uid = getpwnam(username).pw_uid

    # Create user and user directories in chroot
    real_root = os.open("/", os.O_RDONLY)
    os.chroot("/rtt-users-chroot")
    exec_sys_call_check("useradd -d /home/{0} -g rtt-user -u {1} -s /bin/bash {0}"
                        .format(username, uid))
    create_dir("/home/{}".format(username), 0o700, own=username, grp=rtt_user_grp)
    create_dir("/home/{}/.ssh".format(username), 0o700, own=username, grp=rtt_user_grp)
    create_file("/home/{}/.ssh/authorized_keys".format(username), 0o600, own=username, grp=rtt_user_grp)
    os.fchdir(real_root)
    os.chroot(".")
    os.close(real_root)

    # Creating password for user
    exec_sys_call_check("passwd {}".format(username))

except BaseException as e:
    print("Error: {}".format(e))
