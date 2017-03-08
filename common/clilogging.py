import time


def print_time_mess(mess):
    tm = time.localtime()
    print("[{}-{:02d}-{:02d}, {:02d}:{:02d}:{:02d}] {}"
          .format(tm[0], tm[1], tm[2], tm[3], tm[4], tm[5], mess))


def print_start(app_name):
    print_time_mess("Application start - {}".format(app_name))


def print_end():
    print_time_mess("Application end.")


def print_info(mess):
    print_time_mess("info - {}".format(mess))


def print_error(mess):
    print_time_mess("error - {}".format(mess))

