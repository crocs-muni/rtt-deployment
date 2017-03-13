#! /usr/bin/python3

import sys
from common.clilogging import *


def main():
    if len(sys.argv) != 2:
        print_info("Usage: ./deploy_backend.py <backend-id>")
        sys.exit(1)


if __name__ == "__main__":
    print_start("deploy_backend")
    main()
    print_end()