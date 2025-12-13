#!/usr/bin/env python3
"""
Simple keyring helper CLI for storing and retrieving secrets in macOS Keychain

Usage:
  python scripts/keyring_helpers.py set SERVICE ACCOUNT
  python scripts/keyring_helpers.py get SERVICE ACCOUNT
  python scripts/keyring_helpers.py delete SERVICE ACCOUNT

Examples:
  python scripts/keyring_helpers.py set CFD3_TELEGRAM token
  python scripts/keyring_helpers.py get CFD3_TELEGRAM token

This script uses the python-keyring package (macOS Keychain backend).
"""
import sys
import getpass
import keyring


def usage():
    print(__doc__)


def cmd_set(service, account):
    val = getpass.getpass(f'Enter value for {service}/{account} (hidden): ')
    keyring.set_password(service, account, val)
    print(f'Stored {service}/{account} in keyring.')


def cmd_get(service, account):
    val = keyring.get_password(service, account)
    if val is None:
        print(f'No entry found for {service}/{account}')
        return 2
    print(val)
    return 0


def cmd_delete(service, account):
    try:
        keyring.delete_password(service, account)
        print(f'Deleted {service}/{account} from keyring.')
        return 0
    except Exception as e:
        print('Delete failed:', e)
        return 2


def main(argv):
    if len(argv) < 3:
        usage()
        return 2
    cmd = argv[0]
    service = argv[1]
    account = argv[2]
    if cmd == 'set':
        return cmd_set(service, account)
    elif cmd == 'get':
        return cmd_get(service, account)
    elif cmd == 'delete':
        return cmd_delete(service, account)
    else:
        usage()
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
