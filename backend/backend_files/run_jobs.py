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
from common.clilogging import *
from common.rtt_db_conn import *
from common.rtt_sftp_conn import *

################################
# Global variables declaration #
################################
JobInfo = collections.namedtuple("JobInfo", "id experiment_id battery")
cache_data_dir = ""
cache_config_dir = ""
storage_data_dir = ""
storage_config_dir = ""
rtt_binary = ""
sender_email = ""

########################
# Function declaration #
########################
def get_job_info(connection):
    cursor = connection.cursor()

    # Preparing sql expressions
    sql_upd_job_running = \
        """UPDATE jobs SET status='running' WHERE id=%s"""
    sql_upd_experiment_running = \
        """UPDATE experiments SET status='running' WHERE id=%s"""
    sql_sel_job = \
        """SELECT id, experiment_id, battery
           FROM jobs
           WHERE status='pending' AND experiment_id=%s"""

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
            cursor.execute(sql_upd_job_running, (job_info.id, ))
            connection.commit()
            return job_info
    # If program gets here, no relevant cached files were found

    # Looking for experiments that have all their jobs set as pending. This will cause that
    # each experiment is computed by single node, given enough experiments are available
    # cursor.execute("SELECT experiment_id FROM jobs "
    #                "GROUP BY experiment_id HAVING "
    #                "MIN(status) = 'pending' AND MAX(status) = 'pending'")
    # if cursor.rowcount != 0:
    #     row = cursor.fetchone()
    #     experiment_id = row[0]
    #     cursor.execute(sql_sel_job, (experiment_id, ))
    #     row = cursor.fetchone()
    #     job_info = JobInfo(row[0], row[1], row[2])
    #     cursor.execute(sql_upd_job_running, (job_info.id, ))
    #     connection.commit()
    #     return job_info
    cursor.execute("""SELECT id FROM experiments
                      WHERE status='pending'""")
    if cursor.rowcount != 0:
        row = cursor.fetchone()
        experiment_id = row[0]
        cursor.execute(sql_sel_job, (experiment_id, ))
        row = cursor.fetchone()
        job_info = JobInfo(row[0], row[1], row[2])
        cursor.execute(sql_upd_experiment_running, (experiment_id, ))
        cursor.execute(sql_upd_job_running, (job_info.id, ))
        connection.commit()
        return job_info

    # If program gets here it means that there are no experiments that haven't been
    # started by other nodes before. So now just pick one job and execute him.
    # No need for check for existence, table is locked and check is at the beginning
    cursor.execute("SELECT id, experiment_id, battery "
                   "FROM jobs WHERE status='pending'")
    row = cursor.fetchone()
    job_info = JobInfo(row[0], row[1], row[2])
    cursor.execute(sql_upd_job_running, (job_info.id, ))
    connection.commit()
    return job_info


def fetch_data(experiment_id, sftp):
    storage_data_path = get_data_path(storage_data_dir, experiment_id)
    storage_config_path = get_config_path(storage_config_dir, experiment_id)
    cache_data_path = get_data_path(cache_data_dir, experiment_id)
    cache_config_path = get_config_path(cache_config_dir, experiment_id)

    if not os.path.exists(cache_data_path):
        print_info("Downloading remote file {} into {}"
                   .format(storage_data_path, cache_data_path))
        sftp.get(storage_data_path, cache_data_path)
        print_info("Download complete.")
    else:
        print_info("File {} is already in cache.".format(cache_data_path))

    if not os.path.exists(cache_config_path):
        print_info("Downloading remote file {} into {}"
                   .format(storage_config_path, cache_config_path))
        sftp.get(storage_config_path, cache_config_path)
        print_info("Download complete.")
    else:
        print_info("File {} is already in cache.".format(cache_config_path))


def get_data_path(data_dir, experiment_id):
    return os.path.join(data_dir, "{}.bin".format(experiment_id))


def get_config_path(config_dir, experiment_id):
    return os.path.join(config_dir, "{}.json".format(experiment_id))


def get_rtt_arguments(job_info):
    return "{} -b {} -c {} -f {} --mysql {}" \
        .format(rtt_binary,
                job_info.battery,
                get_config_path(cache_config_dir, job_info.experiment_id),
                get_data_path(cache_data_dir, job_info.experiment_id),
                job_info.experiment_id)


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

    # Get path to main config from console
    if len(sys.argv) != 2:
        print_info("[USAGE] {} <path-to-main-config-file>".format(sys.argv[0]))
        sys.exit(1)

    main_cfg_file = sys.argv[1]
    
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
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    ##########################
    # Connecting to database #
    ##########################
    db = create_mysql_db_conn(main_cfg)
    cursor = db.cursor()

    ##########################
    # Connecting to storage  #
    ##########################
    sftp = create_sftp_storage_conn(main_cfg)

    file_null = open(os.devnull, 'w')
    # Changing working directory so RTT will find files it needs
    # to run
    os.chdir(os.path.dirname(rtt_binary))

    ############################################################
    # Execution try block. If error happens during execution   #
    # database is rollback'd to last commit. Already finished  #
    # jobs are left intact. Job during which error happened is #
    # left with status running. This might cause some problems #
    # in the future (???)                                      #
    ############################################################
    try:
        sql_upd_job_finished = """UPDATE jobs SET status='finished' WHERE id=%s"""
        sql_upd_experiment_finished = """UPDATE experiments SET status='finished' WHERE id=%s"""
        # Do this until get_job_info uses sys.exit(0) =>
        # => there are no pending jobs
        # Otherwise loop is without break, so code will always
        # jump into SystemExit catch
        while True:
            job_info = get_job_info(db)
            fetch_data(job_info.experiment_id, sftp)
            rtt_args = get_rtt_arguments(job_info)
            print_info("Executing job: job_id {}, experiment_id {}"
                       .format(job_info.id, job_info.experiment_id))
            print_info("CMD: {}".format(rtt_args))
            subprocess.call(shlex.split(rtt_args), stdout=file_null, stderr=subprocess.STDOUT)
            print_info("Execution complete.")
            cursor.execute(sql_upd_job_finished, (job_info.id, ))

            finished = experiment_finished(job_info.experiment_id, db)
            if finished:
                cursor.execute(sql_upd_experiment_finished, (job_info.experiment_id, ))
                send_email_to_author(job_info.experiment_id, db)

            db.commit()            

    except SystemExit:
        print_info("Terminating.")
        cursor.close()
        db.close()
        sftp.close()
    except BaseException as e:
        print_error("Job execution: {}".format(e))
        db.rollback()
        cursor.close()
        db.close()
        sys.exit(1)


if __name__ == "__main__":
    print_start("run-jobs")
    main()
    print_end()

