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
from common import rtt_utils
from common import rtt_constants


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
        for assoc in rtt_utils.get_associated_files(cache_data_file):
            rtt_utils.try_remove(assoc)
    else:
        print_info("File was already removed: {}".format(cache_data_file))

    if os.path.exists(cache_config_file):
        print_info("Deleting file {}".format(cache_config_file))
        os.remove(cache_config_file)
        for assoc in rtt_utils.get_associated_files(cache_config_file):
            rtt_utils.try_remove(assoc)
    else:
        print_info("File was already removed: {}".format(cache_config_file))


def try_clean_logs(log_dir):
    try:
        logger.info("Cleaning the log dir %s" % log_dir)
        res = rtt_utils.clean_log_files(log_dir)
        logger.info("Log dir cleaned up, files: %s, size: %.2f MB" % (res[0], res[1] / 1024 / 1024))

    except Exception as e:
        logger.error("Log dir cleanup exception", e)


def get_rtt_root_dir(config_dir):
    config_els = config_dir.split(os.sep)
    base_els = rtt_constants.Backend.CACHE_CONFIG_DIR.split(os.sep)
    return os.sep.join(config_els[:-1 * len(base_els)])


def clean_caches(main_cfg_file, mysql_params=None):
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

    rtt_root_dir = get_rtt_root_dir(cache_config_dir)
    rtt_log_dir = os.path.join(rtt_root_dir, rtt_constants.Backend.EXEC_LOGS_TOP_DIR)

    mysql_params = mysql_params if mysql_params else \
        mysql_load_params(main_cfg)
    db = connect_mysql_db(mysql_params)
    cursor = db.cursor()

    try:
        for data_file in os.listdir(cache_data_dir):
            if not data_file.endswith('.bin'):
                continue
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

    try_clean_logs(rtt_log_dir)


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

