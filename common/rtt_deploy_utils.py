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


def add_cron_job(script_path, ini_file_path, log_file_path):
    tmp_file_name = "cron.tmp"
    script_base = os.path.splitext(os.path.basename(script_path))[0]
    entry = "\n* * * * *    /usr/bin/flock " \
            "/var/tmp/{}.lock {} {} >> {} 2>&1\n"\
        .format(script_base, script_path, ini_file_path, log_file_path)

    with open(tmp_file_name, "a") as tmp_file:
        exec_sys_call_check("crontab -l", stdout=tmp_file,
                            acc_codes=[0, 1])
        tmp_file.write(entry)

    exec_sys_call_check("crontab {}".format(tmp_file_name))
    os.remove(tmp_file_name)


def get_rnd_pwd(password_len=30):
    spec_chars = "!?$%&@+<>^"
    characters = string.ascii_letters + string.digits + spec_chars
    while True:
        rval = "".join(random.SystemRandom().choice(characters) for _ in range(password_len))
        if any(spec in rval for spec in spec_chars):
            return rval


def install_debian_pkg(name):
    rval = call(["apt-get", "install", name, "--yes"])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def install_python_pkg(name):
    rval = call(["pip3", "install", name])
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
