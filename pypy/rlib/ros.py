"""
Helper file for Python equivalents of os specific calls.
"""

import os
from pypy.rlib.streamio import fdopen_as_stream

def putenv(name_eq_value):
    # we fake it with the real one
    global _initial_items
    name, value = name_eq_value.split('=', 1)
    os.environ[name] = value
    _initial_items = os.environ.items()
putenv._annenforceargs_ = (str,)

_initial_items = os.environ.items()

def environ(idx):
    # we simulate the environ list
    if idx < len(_initial_items):
        return '%s=%s' % _initial_items[idx]

def getenv(name):
    # slowish, ok for non-repeated use
    pattern = name + '='
    idx = 0
    while 1:
        s = environ(idx)
        if s is None:
            break
        if s.startswith(pattern):
            value = s[len(pattern):]
            return value
        idx += 1
    return None
getenv._annenforceargs_ = (str,)


class DIR(object):
    # a simulated DIR structure from C, i.e. a directory opened by
    # opendir() from which we can enumerate the entries with readdir().
    # Like readdir(), this version does not hide the '.' and '..' entries.
    def __init__(self, dirname):
        self._entries = iter(['.', '..'] + os.listdir(dirname))

    def readdir(self):
        try:
            return self._entries.next()
        except StopIteration:
            return None

    def closedir(self):
        pass

def opendir(dirname):
    return DIR(dirname)
opendir._annenforceargs_ = (str,)

# probably we can get an annotation support for not having both implementations
# here, but let's leave it for now
def utime_null(path):
    os.utime(path, None)

def utime_tuple(path, tp):
    os.utime(path, tp)

# ARGH! strange hack to allow os.tmpfile not to be deleted
# (it should guess it based on getting file desc)
# this is only when run on top of cpython
# this will eventually lead to two closes (when this list is deleted), but
# well.., unsure we can do anything with that.
KEEP_ME_ALIVE_PLEASE = []

def _tmpfile():
    tmpfile = os.tmpfile()
    KEEP_ME_ALIVE_PLEASE.append(tmpfile)
    return tmpfile.fileno()

def tmpfile():
    return fdopen_as_stream(_tmpfile(), "w+b", True)
