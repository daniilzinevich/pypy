# For Windows only.
# https://bitbucket.org/pypy/pypy/issue/1944/ctypes-on-windows-getlasterror

import os

_MS_WINDOWS = os.name == "nt"


if _MS_WINDOWS:
    from rpython.rlib import rwin32
    from pypy.interpreter.executioncontext import Executioncontext


    ExecutionContext._rawffi_last_error = 0

    def restore_last_error(space):
        ec = space.getexecutioncontext()
        lasterror = ec._rawffi_last_error
        rwin32.SetLastError(lasterror)

    def save_last_error(space):
        lasterror = rwin32.GetLastError()
        ec = space.getexecutioncontext()
        ec._rawffi_last_error = lasterror

else:

    def restore_last_error(space):
        pass

    def save_last_error(space):
        pass
