#################################################
# Script will transfer files into storage       #
# server and create appropriate jobs in db.     #
# Another script will execute jobs in db.       #
# It is meant to be executed by user.           #
#################################################

# How to compile the 'submit_experiment' binary:

"""
cd /opt/rtt-submit-experiment
/bin/rm -rf build/ dist/
pyinstaller -F submit_experiment.py
mv dist/submit_experiment .
chgrp rtt_admin submit_experiment
chmod g+s submit_experiment
cp submit_experiment /home/RTTWebInterface/submit_experiment_script/submit_experiment
chgrp rtt_admin /home/RTTWebInterface/submit_experiment_script/submit_experiment
chmod g+s /home/RTTWebInterface/submit_experiment_script/submit_experiment
"""

import configparser
import MySQLdb
import os
import sys
import argparse
import hashlib
import logging
import paramiko
from common.clilogging import *
from common.rtt_db_conn import *
from common.rtt_sftp_conn import *


logger = logging.getLogger(__name__)


################################
# Global variables declaration #
################################
abs_executable_path = os.path.dirname(os.path.abspath(sys.executable))
main_cfg_file = os.path.join(abs_executable_path, "frontend.ini")

battery_flags = {'nist_sts':             1,
                 'dieharder':            2,
                 'tu01_smallcrush':      4,
                 'tu01_crush':           8,
                 'tu01_bigcrush':        16,
                 'tu01_rabbit':          32,
                 'tu01_alphabit':        64,
                 'tu01_blockalphabit':   128,
                 'booltest_1':           256,
                 'booltest_2':           512,
                 }

storage_data_dir = ""
storage_config_dir = ""


########################
# Function declaration #
########################
# Calculates SHA256 of given file, returns
# digest encoded in hex
def sha256file(fname):
    sha256_hash = hashlib.sha256()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


# Will parse input arguments from user
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--email", required=False,
                        help="(optional) notification will be sent to entered address")
    parser.add_argument("-n", "--name", required=True,
                        help="name of the experiment")
    parser.add_argument("-c", "--cfg", required=True,
                        help="path to config file")
    parser.add_argument("-f", "--file", required=True,
                        help="path to data file")
    parser.add_argument("-a", "--all_batteries", action="store_true",
                        help="include all available batteries (except TestU01 Big Crush!)")
    parser.add_argument("--nist_sts", action="store_true",
                        help="switch inclusion of NIST STS battery")
    parser.add_argument("--dieharder", action="store_true",
                        help="switch inclusion of Dieharder battery")
    parser.add_argument("--tu01_smallcrush", action="store_true",
                        help="switch inclusion of TestU01 Small Crush battery")
    parser.add_argument("--tu01_crush", action="store_true",
                        help="switch inclusion of TestU01 Crush battery")
    parser.add_argument("--tu01_bigcrush", action="store_true",
                        help="switch inclusion of TestU01 Big Crush battery")
    parser.add_argument("--tu01_rabbit", action="store_true",
                        help="switch inclusion of TestU01 Rabbit battery")
    parser.add_argument("--tu01_alphabit", action="store_true",
                        help="switch inclusion of TestU01 Alphabit battery")
    parser.add_argument("--tu01_blockalphabit", action="store_true",
                        help="switch inclusion of TestU01 Block Alphabit battery")
    parser.add_argument("--booltest-1", dest='booltest1', action="store_true",
                        help="switch inclusion of BoolTest1 battery")
    parser.add_argument("--booltest-2", dest='booltest2', action="store_true",
                        help="switch inclusion of BoolTest2 battery")
    return parser.parse_args()


# Picks correct batteries based on user input
def pick_batteries(args):
    picked_batts = 0
    if args.all_batteries:
        picked_batts = sum(battery_flags.values()) - battery_flags['tu01_bigcrush']
    if args.nist_sts:
        picked_batts ^= battery_flags['nist_sts']
    if args.dieharder:
        picked_batts ^= battery_flags['dieharder']
    if args.tu01_smallcrush:
        picked_batts ^= battery_flags['tu01_smallcrush']
    if args.tu01_crush:
        picked_batts ^= battery_flags['tu01_crush']
    if args.tu01_bigcrush:
        picked_batts ^= battery_flags['tu01_bigcrush']
    if args.tu01_rabbit:
        picked_batts ^= battery_flags['tu01_rabbit']
    if args.tu01_alphabit:
        picked_batts ^= battery_flags['tu01_alphabit']
    if args.tu01_blockalphabit:
        picked_batts ^= battery_flags['tu01_blockalphabit']
    if args.booltest1:
        picked_batts ^= battery_flags['booltest_1']
    if args.booltest2:
        picked_batts ^= battery_flags['booltest_2']
    return picked_batts


# Will transfer data to the storage server
def upload_data(local_data_file, local_config_file, experiment_id, sftp):
    storage_data_file = os.path.join(storage_data_dir, "{}.bin".format(experiment_id))
    storage_config_file = os.path.join(storage_config_dir, "{}.json".format(experiment_id))
    print_info("Transferring files...")
    sftp.put(local_data_file, storage_data_file)
    sftp.put(local_config_file, storage_config_file)
    print_info("File transfer complete.")


def try_execute(fnc, attempts=40, msg=""):
    for att in range(attempts):
        try:
            fnc()
            return

        except Exception as e:
            logger.error("Exception in executing function, %s, att=%s, msg=%s" % (e, att, msg))
            if att - 1 == attempts:
                raise
    raise ValueError("Should not happen, failstop")


#################
# MAIN FUNCTION #
#################
def main():
    global storage_data_dir
    global storage_config_dir
    ###################################
    # Reading configuration from file #
    ###################################
    # Main configuration settings
    main_cfg = configparser.ConfigParser()
    main_cfg.read(main_cfg_file)
    if len(main_cfg.sections()) == 0:
        print_error("Can't read configuration: {}".format(main_cfg_file))
        sys.exit(1)

    try:
        storage_data_dir = main_cfg.get('Storage', 'Data-directory')
        storage_config_dir = main_cfg.get('Storage', 'Config-directory')
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    ########################
    # CLI Argument parsing #
    ########################
    args = parse_arguments()
    #####################
    # Picking batteries #
    #####################
    picked_batts = pick_batteries(args)
    #################
    # Sanity checks #
    #################
    if not os.path.exists(args.file):
        print_error("Data file does not exist: {}".format(args.file))
        sys.exit(1)
    if not os.path.exists(args.cfg):
        print_error("Config does not exist: {}".format(args.cfg))
        sys.exit(1)
    if picked_batts == 0:
        print_error("No batteries have been chosen.")
        sys.exit(0)

    ##########################
    # Connecting to database #
    ##########################
    db = create_mysql_db_conn(main_cfg)
    cursor = db.cursor()

    ##########################
    # Connecting to storage  #
    ##########################
    sftp = create_sftp_storage_conn(main_cfg)

    #####################################################
    # Data are first transferred to the storage server. #
    # After successful upload, jobs for requested       #
    # batteries will be inserted into db. If anything   #
    # happens, jobs will not be created. Data can still #
    # remain on the storage server.                     #
    #####################################################
    try:
        # Creating experiment
        sql_ins_experiment = "INSERT INTO experiments " \
                             "(name, author_email, config_file, data_file, data_file_sha256) " \
                             "VALUES(%s,%s,%s,%s,%s)"

        try_execute(lambda: cursor.execute(sql_ins_experiment, (args.name, args.email, args.cfg, args.file, sha256file(args.file))),
                    msg="Experiment insert %s" % args.file)

        experiment_id = cursor.lastrowid
        print_info("Created new experiment with id {}".format(experiment_id))
        # Uploading data to storage server
        upload_data(args.file, args.cfg, experiment_id, sftp)
        # Creating jobs
        sql_ins_job = "INSERT INTO jobs " \
                      "(battery, experiment_id) " \
                      "VALUES(%s,%s)"
        for key in battery_flags:
            if picked_batts & battery_flags[key]:
                try_execute(lambda: cursor.execute(sql_ins_job, (key, experiment_id)),
                            msg="Job insert, %s, %s" % (args.file, key))

                print_info("Created job with id {}.".format(cursor.lastrowid))
        
        # Final commit - the jobs and experiment will be now visible
        db.commit()
        cursor.close()
        db.close()
        sftp.close()
    except BaseException as e:
        print_error("Job creation: {}".format(e))
        db.rollback()
        cursor.close()
        db.close()
        sftp.close()
        sys.exit(1)

    print_info("All jobs successfully created.")
    

if __name__ == "__main__":
    print_start("submit-experiment")
    main()
    print_end()

