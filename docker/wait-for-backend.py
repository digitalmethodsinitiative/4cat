#!python3
import sys
from common.lib.exceptions import ConfigException

def main():
    """
    Tests to see if 4CAT's API is running.
    """
    try:
        # This catches a non-existant config.ini file 
        from common.lib.helpers import call_api
    except ConfigException:
        sys.exit(1)

    try:
        api_response = call_api("worker-status")
        if api_response["status"] == "success":
            sys.exit(0)
        else:
            sys.exit(1)
    except ConnectionRefusedError:
        sys.exit(1)

if __name__ == '__main__':
    main()
