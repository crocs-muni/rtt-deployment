#! /usr/bin/python3

######################################################################
# Script will clean useless files in the storage cache.              #
# Files are deemed useless when there exist job/s with corresponding #
# experiment_id and all of them are marked as finished.              #
# Files without corresponding jobs CANNOT be deleted,                #
# it is possible that jobs will be created for the                   #
# files later.                                                       #
######################################################################

import os
import configparser
import sys
import logging
import coloredlogs
from common.clilogging import *
from common.rtt_db_conn import *
from common.rtt_deploy_utils import *

logger = logging.getLogger(__name__)
coloredlogs.CHROOT_FILES = []
coloredlogs.install(level=logging.DEBUG, use_chroot=False)


################################
# Global variables declaration #
################################
cache_data_dir = ""
cache_config_dir = ""


#########################
# Functions declaration #
#########################
def delete_cache_files(exp_id):
    cache_data_file = os.path.join(cache_data_dir, "{}.bin".format(exp_id))
    cache_config_file = os.path.join(cache_config_dir, "{}.json".format(exp_id))
    if os.path.exists(cache_data_file):
        print_info("Deleting file {}".format(cache_data_file))
        os.remove(cache_data_file)
    else:
        print_info("File was already removed: {}".format(cache_data_file))

    if os.path.exists(cache_config_file):
        print_info("Deleting file {}".format(cache_config_file))
        os.remove(cache_config_file)
    else:
        print_info("File was already removed: {}".format(cache_config_file))


def clean_caches(main_cfg_file):
    global cache_data_dir
    global cache_config_dir

    ###################################
    # Reading configuration from file #
    ###################################
    main_cfg = configparser.ConfigParser()

    try:
        main_cfg.read(main_cfg_file)
        if len(main_cfg.sections()) == 0:
            print_error("Can't read configuration: {}".format(main_cfg_file))
            sys.exit(1)

        cache_data_dir = get_no_empty(main_cfg, 'Local-cache', 'Data-directory')
        cache_config_dir = get_no_empty(main_cfg, 'Local-cache', 'Config-directory')
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    db = create_mysql_db_conn(main_cfg)
    cursor = db.cursor()

    try:
        for data_file in os.listdir(cache_data_dir):
            exp_id = int(os.path.splitext(os.path.basename(data_file))[0])
            cursor.execute("SELECT status FROM experiments WHERE id=%s",
                           (exp_id,))

            if cursor.rowcount == 1:
                row = cursor.fetchone()
                if row[0] == 'finished':
                    print_info("Deleting files of experiment: {}".format(exp_id))
                    delete_cache_files(exp_id)

        cursor.close()
        db.close()

    except BaseException as e:
        print_error("Cache files deletion: {}".format(e))
        cursor.close()
        db.close()


#################
# MAIN FUNCTION #
#################
def main():
    # Get path to main config from console
    if len(sys.argv) != 2:
        print_info("[USAGE] {} <path-to-main-config-file>".format(sys.argv[0]))
        sys.exit(1)

    main_cfg_file = sys.argv[1]
    clean_caches(main_cfg_file)


if __name__ == "__main__":
    print_start("clean-cache")
    main()
    print_end()

