#! /usr/bin/python3

#################################################################
# Script will access database and will execute                  #
# jobs (if there are any). It is meant to be executed           #
# every few minutes by cron. Script will give priority to jobs  #
# files of whose are already in the cache. If there are no      #
# relevant files in cache, it will pick job from experiment     #
# that has all jobs pending. If there is no such experiment,    #
# it will pick any pending job.                                 #
#################################################################

import configparser
import os
import shlex
import time
import sys
import re
import collections
import smtplib
import argparse
import requests
import logging
import coloredlogs
import traceback
import random
import hashlib
import itertools
import binascii
import subprocess
from common.clilogging import *
from common.rtt_db_conn import *
from common.rtt_sftp_conn import *
from common import rtt_constants
from common import rtt_worker
from common import rtt_utils


logger = logging.getLogger(__name__)
coloredlogs.CHROOT_FILES = []
coloredlogs.install(level=logging.DEBUG, use_chroot=False)

################################
# Global variables declaration #
################################


class BackendData:
    def __init__(self):
        self.id_key = None
        self.id = None
        self.name = None
        self.type_longterm = False
        self.location = None
        self.aux = None
        self.address = None


JobInfo = collections.namedtuple("JobInfo", "id experiment_id battery")
cache_data_dir = ""
cache_config_dir = ""
storage_data_dir = ""
storage_config_dir = ""
rtt_binary = ""
booltest_rtt_binary = ""
sender_email = ""
backend_data = BackendData()
max_sec_per_test = 4000
worker_pid = os.getpid()


########################
# Function declaration #
########################
def rand_sleep(val=2.0, diff=0.5):
    time.sleep(max(0.0001, val + random.uniform(0, 2*diff) - diff))


def randomize_first_n(lst, n=100):
    pa, pb = lst[:n], lst[n:]
    random.shuffle(pa)
    return pa + pb


def reset_jobs(connection):
    logger.info("Job reset routine")
    cursor = connection.cursor()
    sql_select_reset_job = \
        """
        SELECT id, battery, experiment_id, lock_version FROM jobs
        WHERE status='running' 
          AND run_started > DATE_SUB(NOW(), INTERVAL 3 DAY)
          AND run_heartbeat < DATE_SUB(NOW(), INTERVAL 15 MINUTE)
          AND retries < 10
        """

    try:
        cursor.execute(sql_select_reset_job)
        if cursor.rowcount == 0:
            return

        logger.info("Going to reset %s jobs" % cursor.rowcount)
        for row in list(cursor.fetchall()):
            jid = row[0]

            logger.info("Base job reset %s" % jid)
            cursor.execute("UPDATE jobs SET status='error', retries=retries+1, lock_version=lock_version+1 "
                           "WHERE id=%s AND lock_version=%s AND status='running'", (jid, row[3]))

            if cursor.rowcount <= 0:
                logger.info("Update failed, opt lock not acquired")

            purge_unfinished_job(cursor, jid, eid=row[2], battery=row[1])

            cursor.execute("UPDATE jobs SET status='pending', lock_version=lock_version+1 "
                           "WHERE id=%s AND lock_version=%s AND status='error'", (jid, row[3] + 1))

        logger.info("Jobs cleaned")

    except Exception as e:
        logger.error("Exception in job cleaning: %s" % (e,))
        raise

    finally:
        connection.commit()
        logger.info("Jobs clean finished")


def get_job_info(connection, num_workers=1000):
    global backend_data
    cursor = connection.cursor()

    # Preparing sql expressions
    sql_upd_job_running = \
        """UPDATE jobs SET run_started=NOW(), status='running', run_heartbeat=NOW(), 
           worker_id=%s, worker_pid=%s, lock_version=lock_version+1 
           WHERE id=%s AND lock_version=%s"""
    sql_upd_experiment_running = \
        """UPDATE experiments SET run_started=NOW(), status='running' WHERE status='pending' AND id=%s"""
    sql_sel_job = \
        """SELECT id, experiment_id, battery, lock_version 
           FROM jobs
           WHERE status='pending' AND experiment_id=%s 
           """
    sql_sel_exps = \
        """SELECT experiment_id FROM jobs 
        WHERE status='pending' GROUP BY experiment_id 
        ORDER BY experiment_id LIMIT %d 
        """ % (4 * num_workers,)
    sql_sel_exp_pending = \
        """SELECT id FROM experiments 
           WHERE status='pending' 
           ORDER BY id LIMIT %d
         """ % (4 * num_workers,)
    sql_sel_jobs_pending = \
        """SELECT id, experiment_id, battery, lock_version 
           FROM jobs WHERE status='pending' 
           ORDER BY id LIMIT %d
           """ % (4 * num_workers,)

    # Looking for jobs whose files are already present in local cache
    time_exp_cached = -time.time()
    cursor.execute(sql_sel_exps)
    time_exp_cached += time.time()

    # This terminates script if there are no pending jobs
    if cursor.rowcount == 0:
        connection.commit()
        print_info("No pending jobs, query time: %.2f" % time_exp_cached)
        sys.exit(0)

    # Looking for experiments whose data are already cached
    # on the node
    logger.info("Pending jobs by experiment ID: %s, loaded in: %.2f" % (cursor.rowcount, time_exp_cached))
    pending_exps = randomize_first_n(list(cursor.fetchall()), num_workers)
    for row in pending_exps:
        experiment_id = row[0]
        cache_data = get_data_path(cache_data_dir, experiment_id)
        if not os.path.exists(cache_data):
            continue

        logger.debug("Trying to acquire random job with exp_id=%s" % (experiment_id, ))
        cursor.execute(sql_sel_job, (experiment_id, ))
        if cursor.rowcount == 0:
            logger.info("All pending jobs for cached data are gone, retry later, query time: %.2f" % time_exp_cached)
            continue

        crows = randomize_first_n(list(cursor.fetchall()), num_workers)
        for crow in crows:
            job_info = JobInfo(crow[0], crow[1], crow[2])

            logger.debug("Trying to acquire job %s" % (crow,))
            cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id, crow[3]))
            if cursor.rowcount <= 0:
                continue  # taken already

            connection.commit()
            return job_info
    rand_sleep()

    # If program gets here, no relevant cached files were found

    # Looking for experiments that have all their jobs set as pending. This will cause that
    # each experiment is computed by single node, given enough experiments are available
    logger.debug("Selecting pending experiments...")
    time_exp_pending = -time.time()
    cursor.execute(sql_sel_exp_pending)
    time_exp_pending += time.time()

    logger.debug("Number of pending experiments: %s, loaded in %.2f s" % (cursor.rowcount, time_exp_pending))
    pending_exps = randomize_first_n(list(cursor.fetchall()), num_workers)
    for row in pending_exps:
        experiment_id = row[0]
        logger.debug("Trying to acquire random job with exp_id=%s" % (experiment_id,))
        cursor.execute(sql_sel_job, (experiment_id, ))
        if cursor.rowcount == 0:
            logger.info("All pending jobs are gone for this experiment %s, retry later, query time: %.2f" % (experiment_id, time_exp_pending))
            continue

        crows = randomize_first_n(list(cursor.fetchall()), num_workers)
        for crow in crows:
            job_info = JobInfo(crow[0], crow[1], crow[2])

            logger.debug("Trying to acquire job %s" % (crow, ))
            cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id, crow[3]))
            if cursor.rowcount <= 0:
                continue  # taken already

            cursor.execute(sql_upd_experiment_running, (experiment_id, ))
            connection.commit()
            return job_info

    rand_sleep()

    # If program gets here it means that there are no experiments that haven't been
    # started by other nodes before. So now just pick one job and execute him.
    # No need for check for existence, table is locked and check is at the beginning
    logger.debug("Selecting pending jobs...")
    time_job_pending = -time.time()
    cursor.execute(sql_sel_jobs_pending)
    time_job_pending += time.time()

    logger.debug("Number of pending jobs: %s, loaded in %.2f s" % (cursor.rowcount, time_job_pending))
    pending_jobs = randomize_first_n(list(cursor.fetchall()), num_workers)
    for row in pending_jobs:
        logger.debug("Trying to acquire job with id=%s" % (row[0],))

        job_info = JobInfo(row[0], row[1], row[2])
        cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id, row[3]))
        if cursor.rowcount <= 0:
            continue  # not pending now, maybe taken. go to the next one...

        connection.commit()
        return job_info

    connection.rollback()
    raise SystemExit("No jobs")


def job_heartbeat(connection, job_info):
    for idx in range(15):
        try:
            cursor = connection.cursor()
            sql_upd_job_running = """UPDATE jobs SET run_heartbeat=NOW(), status='running', worker_pid=%s WHERE id=%s"""
            cursor.execute(sql_upd_job_running, (os.getpid(), job_info.id))
            connection.commit()
            return
        except Exception as e:
            logger.error("Exception in heartbeat: %s, iter: %s" % (e, idx))
            rand_sleep()


def deactivate_worker(connection, backend_data):
    logger.info("Deactivating worker %s" % backend_data.id_key)
    cursor = connection.cursor()
    sql_deactivate_worker = """UPDATE workers SET worker_active=0, worker_last_seen=NOW() WHERE id=%s"""
    cursor.execute(sql_deactivate_worker, (backend_data.id_key,))
    connection.commit()


def ensure_backend_record(connection, backend_data):
    cursor = connection.cursor()
    sql_get_rec = \
        """SELECT id, worker_id
           FROM workers
           WHERE worker_id=%s"""

    sql_insert_rec = \
        """INSERT INTO workers(worker_id, worker_name, worker_type, worker_added, worker_last_seen, 
        worker_active, worker_address, worker_location, worker_aux)
        VALUES (%s, %s, %s, NOW(), NOW(), 1, %s, %s, %s)
        """

    cursor.execute(sql_get_rec, (backend_data.id,))
    if cursor.rowcount == 0:
        cursor.execute(sql_insert_rec, (backend_data.id, backend_data.name,
                                        'longterm' if backend_data.type_longterm else 'shortterm',
                                        backend_data.address,
                                        backend_data.location,
                                        backend_data.aux))
        connection.commit()

        # Load again so we have the ID
        cursor.execute(sql_get_rec, (backend_data.id,))

    row = cursor.fetchone()
    backend_data.id_key = row[0]

    sql_upd_seen = """UPDATE workers SET worker_last_seen=NOW(), worker_address=%s, worker_active=1 WHERE id=%s"""
    cursor.execute(sql_upd_seen, (backend_data.address, row[0],))
    connection.commit()
    return backend_data


def refresh_backend_record(connection, backend_data: BackendData):
    cursor = connection.cursor()
    try:
        sql_upd_seen = """UPDATE workers SET worker_last_seen=NOW(), worker_active=1 WHERE id=%s"""
        cursor.execute(sql_upd_seen, (backend_data.id_key,))
        connection.commit()
        return backend_data

    except Exception as e:
        logger.error("Exception in worker rec refresh: %s" % (e,))
        rand_sleep()


def fetch_data(experiment_id, sftp, force=False):
    storage_data_path = get_data_path(storage_data_dir, experiment_id)
    storage_config_path = get_config_path(storage_config_dir, experiment_id)
    cache_data_path = get_data_path(cache_data_dir, experiment_id)
    cache_config_path = get_config_path(cache_config_dir, experiment_id)

    downloader = LockedDownloader(sftp, cache_data_path)
    downloader.download(storage_data_path, force=force)

    downloader = LockedDownloader(sftp, cache_config_path)
    downloader.download(storage_config_path, force=force)


def get_data_path(data_dir, experiment_id):
    return os.path.join(data_dir, "{}.bin".format(experiment_id))


def get_config_path(config_dir, experiment_id):
    return os.path.join(config_dir, "{}.json".format(experiment_id))


def get_rtt_arguments(job_info, rtt_config=None, mysql_host=None, mysql_port=None, exp_dir=None):
    args = "{} -b {} -c {} -f {} -r db_mysql --eid {} --jid {}" \
        .format(rtt_binary,
                job_info.battery,
                get_config_path(cache_config_dir, job_info.experiment_id),
                get_data_path(cache_data_dir, job_info.experiment_id),
                job_info.experiment_id,
                job_info.id)

    if rtt_config:
        args += ' -s %s' % rtt_config
    if mysql_host:
        args += ' --db-host %s' % mysql_host
    if mysql_port:
        args += ' --db-port %s' % mysql_port
    if exp_dir:
        args += ' --rpath "%s"' % exp_dir
    return args


def get_booltest_rtt_arguments(job_info, rtt_config=None, mysql_host=None, mysql_port=None, exp_dir=None):
    if not booltest_rtt_binary:
        logger.error("BoolTest RTT wraper not found")
        return None

    args = "{} -b {} -c {} -f {} --eid {} --jid {}" \
        .format(booltest_rtt_binary,
                job_info.battery,
                get_config_path(cache_config_dir, job_info.experiment_id),
                get_data_path(cache_data_dir, job_info.experiment_id),
                job_info.experiment_id,
                job_info.id)

    if rtt_config:
        args += ' -s %s' % rtt_config
    if mysql_host:
        args += ' --db-host %s' % mysql_host
    if mysql_port:
        args += ' --db-port %s' % mysql_port
    return args


def try_experiment_finished(exp_id, connection):
    for idx in range(15):
        try:
            return experiment_finished(exp_id, connection)
        except Exception as e:
            logger.error("Exception in try_experiment_finished: %s, iter: %s" % (e, idx))
            rand_sleep()
    raise ValueError("Could not set experiment finished")


def experiment_finished(exp_id, connection):
    cursor = connection.cursor()
    cursor.execute("""SELECT status FROM jobs
                      WHERE experiment_id=%s""", (exp_id, ))
    if cursor.rowcount == 0:
        print_error("Experiment with id {} has no jobs.".format(exp_id))
        sys.exit(1)

    for row in cursor.fetchall():
        if row[0] != 'finished' and row[0] != 'error':
            return False

    return True


def try_clean_cache(config, mysql_params=None):
    try:
        import clean_cache_backend
        logger.info("Cleaning the cache...")
        clean_cache_backend.clean_caches(config, mysql_params=mysql_params)
        logger.info("Cache cleaned up")

    except Exception as e:
        logger.error("Cache cleanup exception", e)
        rand_sleep()


def try_clean_logs(log_dir):
    rtt_utils.try_clean_logs(log_dir)


def purge_unfinished_job(cursor, job_id, eid, battery):
    try:
        logger.info("Purging job ID: %s, experiment ID: %s, battery: %s" % (job_id, eid, battery))
        exp_batt = rtt_worker.job_battery_to_experiment(battery)
        cursor.execute("SELECT id FROM batteries WHERE experiment_id=%s AND name=%s", (eid, exp_batt))

        if cursor.rowcount == 0:
            logger.info("No batteries results to purge")
            return

        logger.info("Going to purge %s batteries" % cursor.rowcount)
        for row in list(cursor.fetchall()):
            bid = row[0]
            logger.info("Purging battery results with ID: %s, name: %s" % (bid, exp_batt))

            cursor.execute("DELETE FROM batteries WHERE id=%s", (bid,))

    except Exception as e:
        logger.error("Exception in purge_unfinished_job: %s" % (e,), e)
        rand_sleep()


def try_finalize_experiments(connection):
    sql_get_running_exps = "SELECT id FROM experiments WHERE status='running'"
    sql_upd_experiment_finished = "UPDATE experiments SET  run_finished=NOW(), status='finished' WHERE id=%s"

    try:
        cursor = connection.cursor()
        cursor.execute(sql_get_running_exps)
        logger.info("Experiment finalize check for %s records" % cursor.rowcount)

        for row in cursor.fetchall():
            eid = row[0]
            efinished = try_experiment_finished(eid, connection)
            if efinished:
                logger.info("Finishing experiment %s" % eid)
                cursor.execute(sql_upd_experiment_finished, (eid,))
        connection.commit()

    except Exception as e:
        logger.error("Exception in finalizing experiments: %s" % (e,), e)
        rand_sleep()


def try_upd_job_finished(cursor, job_info, state='finished'):
    sql_upd_job_finished = """UPDATE jobs SET run_finished=NOW(), status=%s WHERE id=%s"""
    for idx in range(15):
        try:
            cursor.execute(sql_upd_job_finished, (state, job_info.id,))
            return
        except Exception as e:
            logger.error("Exception in try_upd_job_finished: %s" % (e,), e)
            rand_sleep()
    raise ValueError("Could not finish try_upd_job_finished")


def try_upd_experiment_finished(cursor, job_info):
    sql_upd_experiment_finished = """UPDATE experiments SET  run_finished=NOW(), status='finished' WHERE id=%s"""
    for idx in range(15):
        try:
            cursor.execute(sql_upd_experiment_finished, (job_info.experiment_id,))
            return
        except Exception as e:
            logger.error("Exception in try_upd_experiment_finished: %s" % (e,), e)
            rand_sleep()
    raise ValueError("Could not finish try_upd_experiment_finished")


def try_make_finalized(cursor, job_info, db):
    try_upd_job_finished(cursor, job_info)
    finished = try_experiment_finished(job_info.experiment_id, db)
    if finished:
        try:
            try_upd_experiment_finished(cursor, job_info)
            send_email_to_author(job_info.experiment_id, db)
        except Exception as e:
            logger.error("Exception in try_make_finalized: %s" % (e,), e)
            rand_sleep()


def check_experiment_results(connection, from_id=None):
    pass


def pathfix(inp):
    inp = re.sub(r'[^a-zA-Z0-9._-]', '-', inp)
    inp = re.sub(r'-{2,}', '-', inp)
    return inp


def create_worker_exp_dir(worker_base_dir, backend_data: BackendData, scratch_dir=None):
    scratch_dir = scratch_dir if scratch_dir else worker_base_dir
    wname = pathfix(backend_data.name or "")
    waddr = pathfix(backend_data.address or "")
    wid = pathfix(backend_data.id[:8] or "")
    exp_dir = os.path.join(scratch_dir, 'workers', '%s-%s-%s' % (waddr, wname, wid))
    rtt_worker.create_experiments_dir(exp_dir)
    rtt_worker.copy_templates_dir(worker_base_dir, exp_dir)
    return exp_dir


def send_email_to_author(exp_id, connection):
    cursor = connection.cursor()
    cursor.execute("SELECT author_email, id, name, created, config_file, data_file, data_file_sha256 "
                   "FROM experiments WHERE id=%s", (exp_id, ))
    if cursor.rowcount == 0:
        print_error("Experiment with id {} should exist but does not.".format(exp_id))
        sys.exit(1)

    row = cursor.fetchone()
    # User entered his email when creating experiment. Send him email that we are finished
    if row[0] is not None:
        recipient = row[0]
        message = "From: RTT Experiments <noreply@rtt-mail.com>\n" \
                  "To: <{row[0]}>\n" \
                  "Subject: Experiment \"{row[2]}\" was finished\n" \
                  "\n" \
                  "Hello,\n" \
                  "your data analysis is complete. You can find basic experiment\n" \
                  "information and results below.\n" \
                  "\n" \
                  "=== Experiment information ===\n" \
                  "ID: {row[1]}\n" \
                  "Name: {row[2]}\n" \
                  "Time of creation: {row[3]:%H:%M:%S, %B %d, %Y}\n" \
                  "Configuration file: {row[4]}\n" \
                  "Data file: {row[5]}\n" \
                  "Data hash (SHA-256): {row[6]}\n" \
                  "\n" \
                  "=== Analysis results ===\n".format(row=row)

        cursor.execute("SELECT name, passed_tests, total_tests "
                       "FROM batteries WHERE experiment_id=%s", (exp_id, ))

        for row in cursor.fetchall():
            single_res = "Battery name: {row[0]}\n" \
                         "\tPassed tests: {row[1]}\n" \
                         "\tTotal tests: {row[2]}\n" \
                         "\n".format(row=row)
            message += single_res

        message += "\n" \
                   "Regards,\n" \
                   "RTT Team\n" \
                   "__________\n" \
                   "This e-mail was automatically generated. If you have any questions,\n" \
                   "please contact me at lubomir.obratil@gmail.com\n" \
                   "\n"

        smtpobj = smtplib.SMTP('localhost')
        smtpobj.sendmail(sender_email, [recipient], message)

        print_info("Mail sent to {}.".format(recipient))


def get_rtt_root_dir(config_dir):
    config_els = config_dir.split(os.sep)
    base_els = rtt_constants.Backend.CACHE_CONFIG_DIR.split(os.sep)
    return os.sep.join(config_els[:-1 * len(base_els)])


def create_forwarder(main_config, mysql_param=None) -> (rtt_worker.SSHForwarder, MySQLParams):
    logger.info("Creating SSH forwarder to mysql server")
    ssh_param = ssh_load_params(main_config)
    mysql_param = mysql_param if mysql_param else mysql_load_params(main_config)
    forwarder = rtt_worker.SSHForwarderLinux(ssh_params=ssh_param,
                                             remote_server=mysql_param.host,
                                             remote_port=mysql_param.port)
    forwarder.start()
    logger.info("Forwarder started, port: %s" % forwarder.local_port)

    mysql_param.host = '127.0.0.1'
    mysql_param.port = forwarder.local_port
    return forwarder, mysql_param


def load_rtt_settings(db):
    sql = "SELECT id, `name`, `value` from rtt_settings"
    try:
        settings = {}
        cursor = db.cursor()
        cursor.execute(sql)

        for row in cursor.fetchall():
            settings[row[1]] = row[2]

        return settings

    except Exception as e:
        logger.error("Exception in loading settings: %s" % (e,), e)
        rand_sleep()


def test_rtt_binary_compatibility():
    for idx in range(3):
        try:
            logger.info("Testing RTT binary compatibility...")
            runner = rtt_worker.get_rtt_runner(rtt_binary, os.path.dirname(rtt_binary))
            runner.start()
            tstart = time.time()
            while runner.is_running and time.time() - tstart < 60:
                time.sleep(0.2)
            runner.shutdown()

            outs = runner.out_acc + runner.err_acc
            found = len(list(itertools.dropwhile(lambda x: 'Randomness Testing Toolkit' not in x, outs))) > 0

            if not found:
                logger.info("RTT not binary compatible, it seems, idx: %s" % idx)
                time.sleep(5)
                rand_sleep()
            else:
                logger.info("RTT is binary compatible")
                return

        except Exception as e:
            logger.error("Exception in RTT binary compatibility test %s" % (e,))

    raise ValueError("RTT is not binary compatible with this system")


def pack_log_dir(worker_exp_dir, exp_log_dir, job_info, backend_data):
    arch_base = os.path.join(exp_log_dir, '%s-%s' % (job_info.id, backend_data.id_key))

    exp_dir = worker_exp_dir.rstrip('/')
    exp_parent, exp_dname = os.path.split(exp_dir)
    args = 'tar -czvf %s.tar.gz --exclude \'templates/*\' %s' % (arch_base, exp_dname)

    async_runner = rtt_worker.AsyncRunner(args, cwd=exp_parent, shell=True)
    async_runner.log_out_after = False
    async_runner.preexec_setgrp = True
    async_runner.start()

    tstart = time.time()
    timeout = 5 * 60
    while async_runner.is_running and time.time() - tstart < timeout:
        time.sleep(0.2)

    if async_runner.is_running:
        logger.error("Compress process still running")
        async_runner.shutdown()
        return

    logger.info("Result packer finished in %s, ret code: %s" % (time.time() - tstart, async_runner.ret_code))
    return async_runner.ret_code


def try_hash_file(fname):
    try:
        return rtt_utils.hash_file(fname=fname)

    except Exception as e:
        logger.error("Exception in hashing file %s: %s" % (fname, e))
        return b""


def scratch_dir_get(fallback, pbspro=False):
    if not pbspro:
        return fallback
    scratch = os.getenv('SCRATCHDIR')

    if not scratch:
        logger.warning('SCRATCHDIR dir not set')
        return fallback

    if not os.path.exists(scratch):
        logger.warning('SCRATCHDIR dir does not exist: %s' % (scratch, ))
        return fallback
    return scratch


#################
# MAIN FUNCTION #
#################
def main():
    global cache_data_dir
    global cache_config_dir
    global storage_data_dir
    global storage_config_dir
    global rtt_binary
    global booltest_rtt_binary
    global sender_email
    global backend_data
    global max_sec_per_test

    parser = argparse.ArgumentParser(description='RttWorker')
    parser.add_argument('-i', '--id', dest='id', default=None,
                        help='Worker ID to use')
    parser.add_argument('--name', dest='name', default=None,
                        help='Worker name to use, e.g., random 32B')
    parser.add_argument('--id-randomize', dest='id_rand', default=None, type=int,
                        help='Creates ID by hashing the name')
    parser.add_argument('--longterm', dest='longterm', default=None, type=int,
                        help='Worker longterm type')
    parser.add_argument('--deactivate', dest='deactivate', default=None, type=int,
                        help='Deactivate after worker is ending')
    parser.add_argument('--location', dest='location', default=None,
                        help='Worker location info')
    parser.add_argument('--aux', dest='aux', default=None,
                        help='Worker aux info to store to the DB')
    parser.add_argument('--run-time', dest='run_time', default=None, type=int,
                        help='Number of seconds the script will run since start')
    parser.add_argument('--job-time', dest='job_time', default=None, type=int,
                        help='Number of seconds the single test will run (max)')
    parser.add_argument('--all-time', dest='all_time', default=None, type=int,
                        help='Spend all time checking for jobs')
    parser.add_argument('--clean-cache', dest='clean_cache', default=None, type=int,
                        help='Clean cache after script termination')
    parser.add_argument('--clean-logs', dest='clean_logs', default=None, type=int,
                        help='Clean experiment logs after termination')
    parser.add_argument('--log-dir', dest='log_dir', default=None,
                        help='Experiment log dir')
    parser.add_argument('--db-host', dest='db_host', default=None,
                        help='MySQL host override')
    parser.add_argument('--db-port', dest='db_port', default=None, type=int,
                        help='MySQL port override')
    parser.add_argument('--forwarded-mysql', dest='forwarded_mysql', default=None, type=int,
                        help='Use SSH-forwarded MySQL connection')
    parser.add_argument('--cleanup-only', dest='cleanup_only', default=None, type=int,
                        help='Cleanup only')
    parser.add_argument('--clean-jobs', dest='clean_jobs', default=None, type=int,
                        help='Cleanup jobs stucked in running state')
    parser.add_argument('--pbspro', dest='pbspro', action='store_const', const=True, default=False,
                        help='Enables PBSpro features, such as scratch space usage')
    parser.add_argument('config', default=None,
                        help='Config file')
    args = parser.parse_args()

    # Get path to main config from console
    if not args.config:
        print_info("[USAGE] {} <path-to-main-config-file>".format(sys.argv[0]))
        sys.exit(1)

    # All the new generated files will have permissions rwxrwx---
    num_workers = 1000
    old_mask = os.umask(0o007)
    main_cfg_file = args.config
    exp_log_dir = None
    time_start = time.time()
    rtt_utils.install_filelock_filter()
    
    ###################################
    # Reading configuration from file #
    ###################################
    # Main configuration settings
    main_cfg = configparser.ConfigParser()
    main_cfg.read(main_cfg_file)
    if len(main_cfg.sections()) == 0:
        print_error("Can't read configuration file: {}".format(main_cfg_file))
        sys.exit(1)

    try:
        cache_data_dir = main_cfg.get('Local-cache', 'Data-directory')
        cache_config_dir = main_cfg.get('Local-cache', 'Config-directory')
        storage_data_dir = main_cfg.get('Storage', 'Data-directory')
        storage_config_dir = main_cfg.get('Storage', 'Config-directory')
        sender_email = main_cfg.get('Backend', 'Sender-email')
        rtt_binary = main_cfg.get('RTT-Binary', 'Binary-path')
        booltest_rtt_binary = main_cfg.get('RTT-Binary', 'booltest-rtt-path')
        rtt_root_dir = get_rtt_root_dir(cache_config_dir)
        rtt_log_dir = os.path.join(rtt_root_dir, rtt_constants.Backend.EXEC_LOGS_TOP_DIR)
        rtt_work_dir = os.path.join(rtt_root_dir, rtt_constants.Backend.RTT_EXECUTION_DIR, 'workers')
        backend_data.id = args.id if args.id else main_cfg.get('Backend', 'backend-id')
        backend_data.name = args.name if args.name else main_cfg.get('Backend', 'backend-name', fallback=None)
        backend_data.location = args.location if args.location else main_cfg.get('Backend', 'backend-loc', fallback=None)
        backend_data.type_longterm = args.longterm if args.longterm is not None else main_cfg.getint('Backend', 'backend-longterm', fallback=False)
        backend_data.aux = args.aux if args.aux else main_cfg.get('Backend', 'backend-aux', fallback=None)
        max_sec_per_test = args.job_time if args.job_time else main_cfg.getint('Backend', 'Maximum-seconds-per-test', fallback=3800)
        exp_log_dir = args.log_dir if args.log_dir else main_cfg.get('Backend', 'log-dir', fallback=None)
        if args.id_rand:
            backend_data.id = hashlib.md5(backend_data.name.encode('utf8')).hexdigest()
            logger.info("Generated worker ID: %s" % backend_data.id)

        if not booltest_rtt_binary:
            try:
                booltest_rtt_binary = subprocess.check_output(['which', 'booltest_rtt'])
            except Exception as e:
                pass

    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    # Test if the rtt binary can run on this machine
    test_rtt_binary_compatibility()

    ##########################
    # Connecting to database #
    ##########################
    db, mysql_params, mysql_forwarder = None, None, None

    # Retry connector to mysql - for cloud workers
    for conn_retry in range(10):
        try:
            logger.info("Connecting to mysql...")
            mysql_params = mysql_load_params(main_cfg, host_override=args.db_host, port_override=args.db_port)
            if args.forwarded_mysql:
                mysql_forwarder, mysql_params = create_forwarder(main_cfg, mysql_param=mysql_params)
                logger.info("Using forwarded mysql: %s:%s" % (mysql_params.host, mysql_params.port))

            db = connect_mysql_db(mysql_params)
            logger.info("MySQL connected")
            break

        except Exception as e:
            db = None
            logger.error("Error in starting mysql connection, iter: %s, err: %s" % (conn_retry, e))
            if mysql_forwarder:
                mysql_forwarder.shutdown()

            time.sleep(2 + conn_retry * 0.2 + random.uniform(0, 2000) / 1000.0)

    if not db:
        raise ValueError("Could not connect to the MySQL")

    cursor = db.cursor()

    ##########################
    # Connecting to storage  #
    ##########################
    sftp = None
    for conn_retry in range(10):
        try:
            logger.info("Connecting to SFTP...")
            sftp = create_sftp_storage_conn(main_cfg)
            logger.info("SFTP connection created")
            break

        except Exception as e:
            sftp = None
            logger.error("Error in starting sftp connection, iter: %s, err: %s" % (conn_retry, e))
            time.sleep(2 + conn_retry * 0.2 + random.uniform(0, 2000) / 1000.0)

    if not sftp:
        raise ValueError("Could not create SFTP connection")

    # Changing working directory so RTT will find files it needs
    # to run
    worker_base_dir = os.path.dirname(rtt_binary)
    os.chdir(worker_base_dir)

    # Get public IP address
    try:
        # backend_data.address = requests.get('https://checkip.amazonaws.com', timeout=30).text.strip()
        backend_data.address = socket.gethostname()
    except Exception as e:
        logger.error("IP fetch exception", e)

    # Ensure the worker is stored in the database so we can reference it
    logger.info("Checking worker record")
    if not args.cleanup_only:
        ensure_backend_record(db, backend_data)

    killer = rtt_utils.GracefulKiller()
    time_last_report = time.time() - 10
    time_last_cleanup = time.time() - 30
    cleanup_interval = 5*60
    ############################################################
    # Execution try block. If error happens during execution   #
    # database is rollback'd to last commit. Already finished  #
    # jobs are left intact. Job during which error happened is #
    # left with status running. This might cause some problems #
    # in the future (???)                                      #
    ############################################################
    logger.info("Starting job load loop")
    worker_exp_dir = None

    try:
        rand_sleep()
        if args.cleanup_only:
            reset_jobs(db)
            raise SystemExit()

        scratch_dir = scratch_dir_get(worker_base_dir, args.pbspro)
        logger.info("Creating worker scratch dir under: %s" % (scratch_dir, ))
        worker_exp_dir = create_worker_exp_dir(worker_base_dir, backend_data, scratch_dir)
        worker_exp_dir = os.path.abspath(worker_exp_dir)
        logger.info("Worker scratch dir: %s" % worker_exp_dir)

        # Do this until get_job_info uses sys.exit(0) =>
        # => there are no pending jobs
        # Otherwise loop is without break, so code will always
        # jump into SystemExit catch
        while True:
            rand_sleep(0.1, 0.05)
            if killer.is_killed():
                logger.info("Terminating due to kill")
                raise SystemExit()

            if time.time() - time_last_report > 600:
                logger.info("Main loop running")
                time_last_report = time.time()

            # Check if we have enough time to run
            if args.run_time:
                time_running = time.time() - time_start
                time_left = args.run_time - time_running

                # Correct job termination only if allocated time is at least 1.5x longest job
                # otherwise we just stop too early so let them run...
                if args.run_time > 1.5 * max_sec_per_test and time_left < max_sec_per_test:
                    logger.info("Time running: %.2f remaining: %.2f, terminating" % (time_running, time_left))
                    raise SystemExit()

                if time_left < 60*10:
                    logger.info("Time running: %.2f remaining: %.2f, terminating" % (time_running, time_left))
                    raise SystemExit()

            # refresh worker keep-alive
            refresh_backend_record(db, backend_data)

            # Settings
            csettings = load_rtt_settings(db)
            if not backend_data.type_longterm and 'shortterm-disable' in csettings:
                should_disable = int(csettings['shortterm-disable'])
                if should_disable and should_disable >= time.time():
                    logger.info("Shorrterm disabled until %s, remaining: %.2f" % (should_disable, should_disable - time.time()))
                    rand_sleep(30, 5)
                    continue

            if backend_data.type_longterm and 'longterm-disable' in csettings:
                should_disable = int(csettings['longterm-disable'])
                if should_disable and should_disable >= time.time():
                    logger.info(
                        "Longterm disabled until %s, remaining: %.2f" % (should_disable, should_disable - time.time()))
                    rand_sleep(30, 5)
                    continue

            if 'terminate-older' in csettings:
                terminate_older = int(csettings['terminate-older'])
                if terminate_older and terminate_older >= time_start:
                    logger.info(
                        "Terminating as this job is old %s vs started %s" % (terminate_older, time_start))
                    raise SystemExit()

            if 'cleanup-interval' in csettings:
                cleanup_interval = int(csettings['cleanup-interval'])

            if 'num-workers' in csettings:
                num_workers = int(csettings['num-workers'])

            # Cleanup
            # Reset unfinished jobs, only by long-term workers to avoid locking on cleanup actions
            if args.clean_jobs and time.time() - time_last_cleanup > cleanup_interval:
                try:
                    reset_jobs(db)
                    time_last_cleanup = time.time()

                except Exception as e:
                    logger.error("Job reset exception: %s" % (e,))
                    rand_sleep()

            # If we should spend all allocated time ignore the exit
            job_info = None
            try:
                logger.info("Loading jobs to process")
                job_info = get_job_info(db, num_workers=num_workers)  # type: JobInfo

            except SystemExit as e:
                logger.debug("No jobs to process")
                if args.run_time and args.all_time:
                    rand_sleep(40, 5)
                    continue

                else:
                    raise

            except Exception as e:
                is_timeout = rtt_utils.is_lock_timeout_exception(e)
                logger.info("Exception in job fetch: %s (%s), is timeout: %s" % (e, type(e), is_timeout))
                if not is_timeout:
                    rand_sleep(25, 3)
                continue

            logger.info("Job fetched, ID: %s, expId: %s" % (job_info.id, job_info.experiment_id))
            fetch_data(job_info.experiment_id, sftp)
            data_file_path = get_data_path(cache_data_dir, job_info.experiment_id)
            data_hash_preexec = try_hash_file(data_file_path)

            logger.info("Executing job: job_id {}, experiment_id {}, file {}, hash {}"
                        .format(job_info.id, job_info.experiment_id,
                                data_file_path, binascii.hexlify(data_hash_preexec)))

            async_runner = None
            is_booltest = False
            time_job_start = time.time()
            if 'booltest' in job_info.battery.lower():
                rtt_settings = os.path.join(worker_base_dir, rtt_constants.Backend.RTT_SETTINGS_JSON)
                rtt_args = get_booltest_rtt_arguments(job_info, rtt_config=rtt_settings,
                                                      mysql_host=mysql_params.host, mysql_port=mysql_params.port,
                                                      exp_dir=worker_exp_dir)
                if not rtt_args:
                    rand_sleep()
                    continue

                logger.info("CMD: {}".format(rtt_args))
                async_runner = rtt_worker.get_booltest_rtt_runner(shlex.split(rtt_args))
                is_booltest = True

            else:
                rtt_args = get_rtt_arguments(job_info, mysql_host=mysql_params.host,
                                             mysql_port=mysql_params.port, exp_dir=worker_exp_dir)
                logger.info("CMD: {}".format(rtt_args))
                async_runner = rtt_worker.get_rtt_runner(shlex.split(rtt_args), cwd=os.path.dirname(rtt_binary))

            logger.info("Starting async command")
            last_heartbeat = time_job_start - 5
            test_failed = False
            async_runner.start()
            logger.info("Async command started")

            while async_runner.is_running:
                if time.time() - last_heartbeat > 20:
                    logger.debug('Heartbeat for job id: %s, running for %.2f s'
                                 % (job_info.id, time.time() - time_job_start))

                    job_heartbeat(db, job_info)
                    last_heartbeat = time.time()

                cjob_time_limit = 2.2 * max_sec_per_test if is_booltest else max_sec_per_test
                if time.time() - time_job_start > cjob_time_limit:
                    logger.error("Current test takes too long, either reconfigure the param or fix the test. Terminating...")
                    test_failed = True
                    async_runner.shutdown()

                time.sleep(1)

            logger.info("Async command finished")

            data_hash_postexec = try_hash_file(data_file_path)
            logger.info("Data file hash: %s" % binascii.hexlify(data_hash_postexec))
            if data_hash_preexec != data_hash_postexec:
                logger.error("Data file hashes differ!")

            if "nist" in job_info.battery and exp_log_dir:
                logger.info("Packing worker dir %s to %s" % (worker_exp_dir, exp_log_dir))
                pack_log_dir(worker_exp_dir, exp_log_dir, job_info, backend_data)

            if async_runner.ret_code != 0 or test_failed:
                logger.error("RTT return code is not zero: %s (or timed out)" % async_runner.ret_code)
                db.commit()
                continue

            try_make_finalized(cursor, job_info, db)
            logger.info("Experiment finalized in the DB")
            db.commit()            

    except SystemExit as e:
        logger.error(e)

        try_finalize_experiments(db)
        if args.deactivate:
            deactivate_worker(db, backend_data)

        cursor.close()
        db.close()
        sftp.close()

        if args.clean_cache or args.cleanup_only:
            try_clean_cache(main_cfg_file, mysql_params=mysql_params)
        if args.clean_logs or args.cleanup_only:
            try_clean_logs(rtt_log_dir)
        if args.clean_logs or args.cleanup_only:
            rtt_utils.try_clean_workers(rtt_work_dir)
        if mysql_forwarder:
            mysql_forwarder.shutdown()
        rtt_utils.try_remove_rf(worker_exp_dir)

        logger.info("System exit, terminating")
        os.umask(old_mask)

    except BaseException as e:
        logger.error(e)
        print_error("Job execution: {}".format(e))
        traceback.print_exc()
        db.rollback()
        cursor.close()
        db.close()
        os.umask(old_mask)
        rtt_utils.try_remove_rf(worker_exp_dir)

        if mysql_forwarder:
            mysql_forwarder.shutdown()

        sys.exit(1)


if __name__ == "__main__":
    print_start("run-jobs")
    main()
    print_end()

