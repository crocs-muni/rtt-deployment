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
import subprocess
import shlex
import time
import sys
import collections
import smtplib
import argparse
import requests
import logging
import coloredlogs
import traceback
import signal
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
sender_email = ""
backend_data = BackendData()
max_sec_per_test = 4000
worker_pid = os.getpid()


########################
# Function declaration #
########################
def get_job_info(connection):
    global backend_data
    cursor = connection.cursor()

    # Preparing sql expressions
    sql_upd_job_running = \
        """UPDATE jobs SET run_started=NOW(), status='running', run_heartbeat=NOW(), worker_id=%s, worker_pid=%s 
           WHERE id=%s"""
    sql_upd_experiment_running = \
        """UPDATE experiments SET run_started=NOW(), status='running' WHERE id=%s"""
    sql_sel_job = \
        """SELECT id, experiment_id, battery
           FROM jobs
           WHERE status='pending' AND experiment_id=%s"""
    sql_reset_job = \
        """
        UPDATE jobs set status='pending', retries=retries+1
        WHERE status='running' 
          AND run_started > DATE_SUB(NOW(), INTERVAL 3 DAY)
          AND run_heartbeat < DATE_SUB(NOW(), INTERVAL 1 HOUR)
          AND retries < 10
        """

    # Job reset
    cursor.execute(sql_reset_job)

    # Looking for jobs whose files are already present in local cache
    cursor.execute("SELECT experiment_id FROM jobs "
                   "WHERE status='pending' GROUP BY experiment_id "
                   "FOR UPDATE")

    # This terminates script if there are no pending jobs
    if cursor.rowcount == 0:
        connection.commit()
        print_info("No pending jobs")
        sys.exit(0)

    # Looking for experiments whose data are already cached
    # on the node
    for row in cursor.fetchall():
        experiment_id = row[0]
        cache_data = get_data_path(cache_data_dir, experiment_id)
        if os.path.exists(cache_data):
            cursor.execute(sql_sel_job, (experiment_id, ))
            row = cursor.fetchone()
            job_info = JobInfo(row[0], row[1], row[2])
            cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id))
            connection.commit()
            return job_info
    # If program gets here, no relevant cached files were found

    # Looking for experiments that have all their jobs set as pending. This will cause that
    # each experiment is computed by single node, given enough experiments are available
    cursor.execute("""SELECT id FROM experiments
                      WHERE status='pending'""")
    if cursor.rowcount != 0:
        row = cursor.fetchone()
        experiment_id = row[0]
        cursor.execute(sql_sel_job, (experiment_id, ))
        row = cursor.fetchone()
        job_info = JobInfo(row[0], row[1], row[2])
        cursor.execute(sql_upd_experiment_running, (experiment_id, ))
        cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id, ))
        connection.commit()
        return job_info

    # If program gets here it means that there are no experiments that haven't been
    # started by other nodes before. So now just pick one job and execute him.
    # No need for check for existence, table is locked and check is at the beginning
    cursor.execute("SELECT id, experiment_id, battery "
                   "FROM jobs WHERE status='pending'")
    row = cursor.fetchone()
    job_info = JobInfo(row[0], row[1], row[2])
    cursor.execute(sql_upd_job_running, (backend_data.id_key, os.getpid(), job_info.id, ))
    connection.commit()
    return job_info


def job_heartbeat(connection, job_info):
    cursor = connection.cursor()
    sql_upd_job_running = """UPDATE jobs SET run_heartbeat=NOW(), status='running', worker_pid=%s WHERE id=%s"""
    cursor.execute(sql_upd_job_running, (os.getpid(), job_info.id))
    connection.commit()


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

    sql_upd_seen = """UPDATE workers SET worker_last_seen=NOW(), worker_address=%s WHERE id=%s"""
    cursor.execute(sql_upd_seen, (backend_data.address, row[0],))
    connection.commit()
    return backend_data


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


def get_rtt_arguments(job_info, rtt_config=None, mysql_host=None, mysql_port=None):
    args = "{} -b {} -c {} -f {} -r db_mysql --eid {}" \
        .format(rtt_binary,
                job_info.battery,
                get_config_path(cache_config_dir, job_info.experiment_id),
                get_data_path(cache_data_dir, job_info.experiment_id),
                job_info.experiment_id)

    if rtt_config:
        args += ' -s %s' % rtt_config
    if mysql_host:
        args += ' --db-host %s' % mysql_host
    if mysql_port:
        args += ' --db-port %s' % mysql_port
    return args


def experiment_finished(exp_id, connection):
    cursor = connection.cursor()
    cursor.execute("""SELECT status FROM jobs
                      WHERE experiment_id=%s""", (exp_id, ))
    if cursor.rowcount == 0:
        print_error("Experiment with id {} has no jobs.".format(exp_id))
        sys.exit(1)

    for row in cursor.fetchall():
        if row[0] != 'finished':
            return False

    return True


def try_clean_cache(config):
    try:
        import clean_cache_backend
        logger.info("Cleaning the cache...")
        clean_cache_backend.clean_caches(config)
        logger.info("Cache cleaned up")

    except Exception as e:
        logger.error("Cache cleanup exception", e)


def try_clean_logs(log_dir):
    try:
        logger.info("Cleaning the log dir %s" % log_dir)
        res = rtt_utils.clean_log_files(log_dir)
        logger.info("Log dir cleaned up, files: %s, size: %.2f MB" % (res[0], res[1]/1024/1024))

    except Exception as e:
        logger.error("Log dir cleanup exception", e)


def try_finalize_experiments(connection):
    sql_get_running_exps = "SELECT id FROM experiments WHERE status='running'"
    sql_upd_experiment_finished = "UPDATE experiments SET  run_finished=NOW(), status='finished' WHERE id=%s"

    try:
        cursor = connection.cursor()
        cursor.execute(sql_get_running_exps)
        logger.info("Experiment finalize check for %s records" % cursor.rowcount)

        for row in cursor.fetchall():
            eid = row[0]
            efinished = experiment_finished(eid, connection)
            if efinished:
                logger.info("Finishing experiment %s" % eid)
                cursor.execute(sql_upd_experiment_finished, (eid,))

    except Exception as e:
        logger.error("Exception in finalizing experiments: %s" % e, e)


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


#################
# MAIN FUNCTION #
#################
def main():
    global cache_data_dir
    global cache_config_dir
    global storage_data_dir
    global storage_config_dir
    global rtt_binary
    global sender_email
    global backend_data
    global max_sec_per_test

    parser = argparse.ArgumentParser(description='RttWorker')
    parser.add_argument('-i', '--id', dest='id', default=None,
                        help='Worker ID to use')
    parser.add_argument('--name', dest='name', default=None,
                        help='Worker name to use, e.g., random 32B')
    parser.add_argument('--longterm', dest='longterm', default=None, type=int,
                        help='Worker longterm type')
    parser.add_argument('--deactivate', dest='deactivate', default=None, type=int,
                        help='Deactivate after worker is ending')
    parser.add_argument('--location', dest='location', default=None, type=int,
                        help='Worker location info')
    parser.add_argument('--aux', dest='aux', default=None, type=int,
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
    parser.add_argument('--db-host', dest='db_host', default=None,
                        help='MySQL host override')
    parser.add_argument('--db-port', dest='db_port', default=None, type=int,
                        help='MySQL port override')
    parser.add_argument('config', default=None,
                        help='Config file')
    args = parser.parse_args()

    # Get path to main config from console
    if not args.config:
        print_info("[USAGE] {} <path-to-main-config-file>".format(sys.argv[0]))
        sys.exit(1)

    # All the new generated files will have permissions rwxrwx---
    old_mask = os.umask(0o007)
    main_cfg_file = args.config
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
        rtt_root_dir = get_rtt_root_dir(cache_config_dir)
        rtt_log_dir = os.path.join(rtt_root_dir, rtt_constants.Backend.EXEC_LOGS_TOP_DIR)
        backend_data.id = args.id if args.id else main_cfg.get('Backend', 'backend-id')
        backend_data.name = args.name if args.name else main_cfg.get('Backend', 'backend-name', fallback=None)
        backend_data.location = args.location if args.location else main_cfg.get('Backend', 'backend-loc', fallback=None)
        backend_data.type_longterm = args.longterm if args.longterm else main_cfg.getint('Backend', 'backend-longterm', fallback=False)
        backend_data.aux = args.aux if args.aux else main_cfg.get('Backend', 'backend-aux', fallback=None)
        max_sec_per_test = args.job_time if args.job_time else main_cfg.getint('Backend', 'Maximum-seconds-per-test', fallback=3800)
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    ##########################
    # Connecting to database #
    ##########################
    db = create_mysql_db_conn(main_cfg, host_override=args.db_host, port_override=args.db_port)
    cursor = db.cursor()

    ##########################
    # Connecting to storage  #
    ##########################
    sftp = create_sftp_storage_conn(main_cfg)

    # Changing working directory so RTT will find files it needs
    # to run
    os.chdir(os.path.dirname(rtt_binary))

    # Get public IP address
    try:
        backend_data.address = requests.get('https://checkip.amazonaws.com').text.strip()
    except Exception as e:
        logger.error("IP fetch exception", e)

    # Ensure the worker is stored in the database so we can reference it
    ensure_backend_record(db, backend_data)
    killer = rtt_utils.GracefulKiller()

    ############################################################
    # Execution try block. If error happens during execution   #
    # database is rollback'd to last commit. Already finished  #
    # jobs are left intact. Job during which error happened is #
    # left with status running. This might cause some problems #
    # in the future (???)                                      #
    ############################################################
    try:
        sql_upd_job_finished = """UPDATE jobs SET run_finished=NOW(), status='finished' WHERE id=%s"""
        sql_upd_experiment_finished = """UPDATE experiments SET  run_finished=NOW(), status='finished' WHERE id=%s"""
        # Do this until get_job_info uses sys.exit(0) =>
        # => there are no pending jobs
        # Otherwise loop is without break, so code will always
        # jump into SystemExit catch
        while True:
            raise SystemExit()
            if killer.is_killed():
                logger.info("Terminating due to kill")
                raise SystemExit()

            # Check if we have enough time to run
            if args.run_time and time.time() - time_start < max_sec_per_test:
                logger.info("Time remaining: %s, terminating" % (time.time() - time_start))
                raise SystemExit()

            # If we should spend all allocated time ignore the exit
            job_info = None
            try:
                job_info = get_job_info(db)
            except SystemExit as e:
                if args.run_time and args.all_time:
                    time.sleep(1)
                    continue
                else:
                    raise

            fetch_data(job_info.experiment_id, sftp)
            rtt_args = get_rtt_arguments(job_info, mysql_host=args.db_host, mysql_port=args.db_port)
            rtt_env = {'LD_LIBRARY_PATH': rtt_utils.extend_lib_path(os.path.dirname(rtt_binary))}

            print_info("Executing job: job_id {}, experiment_id {}"
                       .format(job_info.id, job_info.experiment_id))
            print_info("CMD: {}".format(rtt_args))

            time_job_start = time.time()
            async_runner = rtt_worker.AsyncRunner(shlex.split(rtt_args), cwd=os.path.dirname(rtt_binary),
                                                  shell=False, env=rtt_env)
            async_runner.log_out_after = False

            logger.info("Starting async command")
            last_heartbeat = 0
            async_runner.start()
            while async_runner.is_running:
                if time.time() - last_heartbeat > 20:
                    logger.debug('Heartbeat for job id: %s, running for %s s'
                                 % (job_info.id, time.time() - time_job_start))

                    job_heartbeat(db, job_info)
                    last_heartbeat = time.time()
                time.sleep(1)

            logger.info("Async command finished")
            print_info("Execution complete.")
            cursor.execute(sql_upd_job_finished, (job_info.id, ))

            finished = experiment_finished(job_info.experiment_id, db)
            if finished:
                cursor.execute(sql_upd_experiment_finished, (job_info.experiment_id, ))
                send_email_to_author(job_info.experiment_id, db)

            db.commit()            

    except SystemExit as e:
        logger.error(e)

        try_finalize_experiments(db)
        if args.deactivate:
            deactivate_worker(db, backend_data)

        cursor.close()
        db.close()
        sftp.close()

        if args.clean_cache:
            try_clean_cache(main_cfg_file)
        if args.clean_logs:
            try_clean_logs(rtt_log_dir)

        logger.info("System exit, terminating")
        print_info("Terminating.")
        os.umask(old_mask)

    except BaseException as e:
        logger.error(e)
        print_error("Job execution: {}".format(e))
        traceback.print_exc()
        db.rollback()
        cursor.close()
        db.close()
        os.umask(old_mask)
        sys.exit(1)


if __name__ == "__main__":
    print_start("run-jobs")
    main()
    print_end()

