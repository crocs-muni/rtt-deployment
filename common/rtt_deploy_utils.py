import random
import string
import os
import sys
import glob
import shutil
import shlex
from subprocess import call, Popen, PIPE
from common.clilogging import *
from common.rtt_constants import *


def try_fnc(fnc):
    try:
        return fnc()
    except:
        pass


def verify_output(ret_code, accept=[0], cmd=None):
    if ret_code not in accept:
        raise EnvironmentError("Command %s failed with code %s" % (cmd, accept))


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
    spec_chars = "-_.!?+<>^="
    characters = string.ascii_letters + string.digits + spec_chars
    while True:
        rval = "".join(random.SystemRandom().choice(characters) for _ in range(password_len))
        if any(spec in rval for spec in spec_chars):
            return rval


def create_file_wperms(fpath=None, mask=0o600, mode='w'):
    # The default umask is 0o22 which turns off write permission of group and others
    prev = os.umask(0)
    try:
        return open(os.open(fpath, os.O_CREAT | os.O_RDWR | os.O_EXCL, mask), mode)
    finally:
        os.umask(prev)


def backup_file(fpath, remove=False):
    if not os.path.exists(fpath):
        return

    fdir = os.path.dirname(fpath)
    fname = os.path.basename(fpath)
    stat = os.stat(fpath)
    mask = stat.st_mode & 0o777

    ctr = 0
    while True:
        ctr += 1
        cand = os.path.join(fdir, '%s.%03d' % (fname, ctr))
        try:
            with create_file_wperms(cand, mask) as fdst, open(fpath, 'r') as fsrc:
                shutil.copyfileobj(fsrc, fdst)
            os.chown(cand, uid=stat.st_uid, gid=stat.st_gid)
            if remove:
                os.unlink(fpath)
            return cand

        except Exception as e:
            if ctr > 10000:
                raise EnvironmentError("Could not create file: %s" % (e,))
            continue


def install_debian_pkg(name):
    rval = call(["apt-get", "install", name, "--yes", "--force-yes"])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def install_debian_pkgs(names):
    rval = call(["apt-get", "install", *names, "--yes", "--force-yes"])
    if rval != 0:
        raise EnvironmentError("Installing packages {}, error code: {}".format(names, rval))


def install_debian_pkg_at_least_one(names):
    for name in names:
        try:
            install_debian_pkg(name)
            return True
        except Exception as e:
            pass
    raise EnvironmentError("Installing packages {} failed".format(names))


def install_python_pkg(name, no_cache=True):
    cache = ['--no-cache'] if no_cache else []
    rval = call(["pip3", "install", "-U", *cache, name])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(name, rval))


def install_python_pkgs(names):
    rval = call(["pip3", "install", "-U", "--no-cache", *names])
    if rval != 0:
        raise EnvironmentError("Installing package {}, error code: {}".format(names, rval))


def exec_sys_call(command, stdin=None, stdout=None, env=None, shell=False):
    return call(shlex.split(command), stdin=stdin, stdout=stdout, env=env, shell=shell)


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


def submit_experiment_deploy(cdir):
    install_python_pkgs([
        "pyinstaller", "filelock", "jsonpath-ng", "booltest", "booltest-rtt"
    ])
    submit_experiment_build(cdir)


def submit_experiment_build(cdir):
    current_dir = os.path.abspath(os.path.curdir)
    try:
        os.chdir(cdir)
        submit_exp_base_name = os.path.splitext(Frontend.SUBMIT_EXPERIMENT_SCRIPT)[0]
        exec_sys_call_check("pyinstaller -F {}".format(Frontend.SUBMIT_EXPERIMENT_SCRIPT))
        shutil.move("dist/{}".format(submit_exp_base_name),
                    Frontend.SUBMIT_EXPERIMENT_BINARY)
        chmod_chown(Frontend.SUBMIT_EXPERIMENT_BINARY, 0o2775, grp=Frontend.RTT_ADMIN_GROUP)
        shutil.rmtree("dist")
        shutil.rmtree("build")
        shutil.rmtree("__pycache__")
        os.remove("{}.spec".format(submit_exp_base_name))
    finally:
        os.chdir(current_dir)


def cryptostreams_get_repo(ph4=False):
    if ph4:
        return CommonConst.CRYPTOSTREAMS_REPO_PH4, CommonConst.CRYPTOSTREAMS_REPO_BRANCH_PH4
    else:
        return CommonConst.CRYPTOSTREAMS_REPO, CommonConst.CRYPTOSTREAMS_REPO_BRANCH


def cryptostreams_clone(repo, branch, dst=None):
    return exec_sys_call_check("git clone --recursive --branch %s %s %s" % (branch, repo, dst if dst else ''))


def cryptostreams_build(cdir=None):
    current_dir = os.path.abspath(os.path.curdir)

    if cdir:
        os.chdir(cdir)

    try:
        BUILD_DIR = 'build'
        try_fnc(lambda: shutil.rmtree(BUILD_DIR))
        os.makedirs(BUILD_DIR)
        os.chdir(BUILD_DIR)
        exec_sys_call_check("cmake ..",  acc_codes=[0, 1, 2])
        exec_sys_call_check("make -j2",  acc_codes=[0, 1, 2])
        exec_sys_call_check("make -j2",  acc_codes=[0, 1, 2])
        return os.path.abspath('./crypto-streams')

    finally:
        os.chdir(current_dir)


def cryptostreams_link(crypto_dir, crypto_bin, ph4=False, res_bin_dir='/usr/bin'):
    cmd = 'git -C "%s" rev-parse HEAD' % crypto_dir
    p = Popen(shlex.split(cmd), stdout=PIPE, stderr=PIPE)
    output, err = p.communicate()
    verify_output(p.returncode, cmd="CryptoStreams git rev-parse HEAD")
    output = output.decode("utf8").strip()

    ph4mod = '-ph4' if ph4 else ''
    bname = 'crypto-streams-v3.0%s-%s' % (ph4mod, output[:12])
    cpath = os.path.join(res_bin_dir, bname)
    try_fnc(lambda: os.unlink(cpath))
    shutil.copy(crypto_bin, cpath)
    os.chmod(cpath, 0o755)

    lnks = [
        os.path.join(res_bin_dir, 'crypto-streams-v3.0'),
        os.path.join(res_bin_dir, 'crypto-streams')]
    for lnk in lnks:
        try_fnc(lambda: os.unlink(lnk))
        os.symlink(cpath, lnk)
    return [cpath, *lnks]


def cryptostreams_complete_deploy(ph4=False, res_bin_dir='/usr/bin', src_dir=CommonConst.USR_SRC,
                                  crypto_dir=CommonConst.CRYPTOSTREAMS_SRC_DIR):
    install_debian_pkgs(["cmake"])
    current_dir = os.path.abspath(os.path.curdir)
    try:
        os.chdir(src_dir)
        crypto_repo, crypto_branch = cryptostreams_get_repo(ph4)
        if os.path.exists(crypto_dir):
            shutil.rmtree(crypto_dir)

        cryptostreams_clone(crypto_repo, crypto_branch, crypto_dir)
        cbin = cryptostreams_build(crypto_dir)
        return cryptostreams_link(crypto_dir, cbin, ph4=ph4, res_bin_dir=res_bin_dir)

    finally:
        os.chdir(current_dir)

