"""Stands in for `keyring` in every child process the tests start.

The tests put this directory first on a child's import path. The child then cannot import
keyring, so it cannot open the OS keychain, and the package answers as it does on a machine
whose keychain cannot be read. tests/test_suite_isolation.py checks that this holds.
"""

raise ImportError("the test suite never opens the OS keychain")
