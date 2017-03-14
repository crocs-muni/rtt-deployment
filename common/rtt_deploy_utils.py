import random
import string
import os
import sys
import shlex
from subprocess import call
from common.clilogging import *


def check_paths_abs(paths):
    for p in paths:
        if not os.path.isabs(p):
            raise AssertionError("Path must be absolute: {}".format(p))


def check_paths_rel(paths):
    for p in paths:
        if os.path.isabs(p):
            raise AssertionError("Path must be relative: {}".format(p))


def check_files_exists(paths):
    for p in paths:
        if not os.path.exists(p):
            raise AssertionError("File does not exist: {}".format(p))


def get_no_empty(cfg, section, option):
    rval = cfg.get(section, option)
    if len(rval) == 0:
        raise ValueError("option {} in section {} is empty."
                         .format(option, section))
    
    return rval


def get_rnd_pwd(password_len = 30):
    characters = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(characters) for _ in range(password_len))


def install_pkg(name, pkg_mngr="apt-get"):
    rval = call([pkg_mngr, "install", name])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def exec_sys_call_check(command, stdin=None, stdout=None, acc_codes=[0]):
    rval = call(shlex.split(command), stdin=stdin, stdout=stdout)
    if rval not in acc_codes:
        raise EnvironmentError("Executing command \'{}\', error code: {}"
                               .format(command, rval))


def chmod_chown(path, mode, own="", grp=""):
    chown_str = own
    if grp != "":
        chown_str += ":{}".format(grp)

    if chown_str != "":
        exec_sys_call_check("chown {} \'{}\'".format(chown_str, path))
    
    os.chmod(path, mode)


def create_dir(path, mode, own="", grp=""):
    if not os.path.exists(path):
        os.mkdir(path)
    
    chmod_chown(path, mode, own, grp)


def create_file(path, mode, own="", grp=""):
    open(path, "a").close()
    chmod_chown(path, mode, own, grp)


def recursive_chmod_chown(path, mod_f, mod_d, own="", grp=""):
    if os.path.isdir(path):
        chmod_chown(path, mod_d, own, grp)
    
        for sub in os.listdir(path):
            recursive_chmod_chown(os.path.join(path, sub),
                                  mod_f, mod_d, own, grp)
    else:
        chmod_chown(path, mod_f, own, grp)
    
