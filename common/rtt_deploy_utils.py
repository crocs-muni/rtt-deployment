import random
import string
import os
import sys
import glob
import shutil
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
    entry = "\n* * * * *    /usr/bin/flock -n " \
            "/var/tmp/{}.lock {} {} >> {} 2>&1\n"\
        .format(script_base, script_path, ini_file_path, log_file_path)

    with open(tmp_file_name, "a") as tmp_file:
        exec_sys_call_check("crontab -l", stdout=tmp_file,
                            acc_codes=[0, 1])
        tmp_file.write(entry)

    exec_sys_call_check("crontab {}".format(tmp_file_name))
    os.remove(tmp_file_name)


def get_rnd_pwd(password_len=30):
    spec_chars = "!?$&@+<>^"
    characters = string.ascii_letters + string.digits + spec_chars
    while True:
        rval = "".join(random.SystemRandom().choice(characters) for _ in range(password_len))
        if any(spec in rval for spec in spec_chars):
            return rval


def install_debian_pkg(name):
    rval = call(["apt-get", "install", name, "--yes", "--force-yes"])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def install_debian_pkg_at_least_one(names):
    for name in names:
        try:
            install_debian_pkg(name)
            return True
        except Exception as e:
            pass
    raise EnvironmentError("Installing packages {} failed".format(names))


def install_python_pkg(name):
    rval = call(["pip3", "install", "-U", "--no-cache", name])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def exec_sys_call_check(command, stdin=None, stdout=None, acc_codes=[0], env=None, shell=False):
    rval = call(shlex.split(command), stdin=stdin, stdout=stdout, env=env, shell=shell)
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


def get_rtt_build_env(rtt_dir, libmariadbclient='/usr/lib/x86_64-linux-gnu/libmariadbclient.a'):
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = '%s:%s' % (os.getenv('LD_LIBRARY_PATH', ''), rtt_dir)
    env['LD_RUN_PATH'] = '%s:%s' % (os.getenv('LD_RUN_PATH', ''), rtt_dir)
    env['LINK_PTHREAD'] = '-Wl,-Bdynamic -lpthread'
    env['LINK_MYSQL'] = '-lmysqlcppconn -L%s -lmariadbclient' % libmariadbclient
    env['LDFLAGS'] = '%s -Wl,-Bdynamic -ldl -lz -Wl,-Bstatic -static-libstdc++ -static-libgcc -L %s' % (os.getenv('LDFLAGS', ''), rtt_dir)
    env['CXXFLAGS'] = '%s -Wl,-Bdynamic -ldl -lz -Wl,-Bstatic -static-libstdc++ -static-libgcc -L %s' % (os.getenv('CXXFLAGS', ''), rtt_dir)
    return env


def copy_rtt_libs(rtt_dir):
    from subprocess import Popen, PIPE

    tbase = 'libmysqlcppconn'
    target = 'libmysqlcppconn.so'
    cand_paths = [
        '/usr/lib/x86_64-linux-gnu',
        '/lib64',
        '/usr/lib',
        '/lib',
    ]

    def subcopy_fpath(fpath):
        paths = glob.glob('%s/%s*' % (os.path.dirname(fpath), tbase))
        for x in paths:
            shutil.copy(x, rtt_dir)
        print('Copied libs to RTT %s' % paths)
        return glob.glob('%s/%s*.a' % (os.path.dirname(fpath), tbase))[0]

    for cand in cand_paths:
        fpath = os.path.join(cand, target)
        if not os.path.exists(fpath):
            continue
        return subcopy_fpath(fpath)

    # Fallback to find
    cmd = 'find /usr/ /lib /lib64 /opt/ -name "libmysqlcppconn.so"'
    p = Popen(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
    output, err = p.communicate()

    results = output.decode('utf').split('\n')
    for fpath in results:
        fpath = fpath.strip()
        if not fpath:
            continue
        if not os.path.exists(fpath):
            continue
        return subcopy_fpath(fpath)

    raise EnvironmentError("Could not find %s library" % target)


def build_static_dieharder(bat_dir):
    ddir = glob.glob(os.path.join(bat_dir, 'dieharder-src/dieharder') + '*')
    if not ddir or not os.path.exists(ddir[0]):
        raise EnvironmentError("Could not find Dieharder sources in %s" % bat_dir)

    ddir = ddir[0]
    install_dir = os.path.join(ddir, '..', 'install')
    os.chdir(ddir)
    exec_sys_call_check("sed -i -e 's#dieharder_LDADD = .*#dieharder_LDFLAGS = -static\\ndieharder_LDADD = -lgsl -lgslcblas -lm  ../libdieharder/libdieharder.la#g' dieharder/Makefile.am")
    exec_sys_call_check("sed -i -e 's#dieharder_LDADD = .*#dieharder_LDADD = -lgsl -lgslcblas -lm -static ../libdieharder/libdieharder.la#g' dieharder/Makefile.in")
    exec_sys_call_check("autoreconf -i")
    exec_sys_call_check("./configure --enable-static --prefix=%s --enable-static=dieharder" % install_dir)
    exec_sys_call_check("make clean")
    exec_sys_call_check("make -j2", acc_codes=[0, 1, 2, 3])
    exec_sys_call_check("make -j2", acc_codes=[0, 1, 2, 3])
    exec_sys_call_check("make install")
