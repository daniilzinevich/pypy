import os
from pypy.rlib.debug import have_debug_prints
from pypy.rlib.debug import debug_start, debug_stop, debug_print
from pypy.rlib.objectmodel import we_are_translated
from pypy.rpython.lltypesystem import lltype, llmemory, rffi
from pypy.jit.metainterp.resoperation import rop
from pypy.jit.metainterp.history import Const, ConstInt, Box, \
     BoxInt, ConstFloat, BoxFloat, AbstractFailDescr

class Logger(object):

    def __init__(self, metainterp_sd, guard_number=False):
        self.metainterp_sd = metainterp_sd
        self.guard_number = guard_number

    def log_loop(self, inputargs, operations, number=0, type=None):
        if type is None:
            debug_start("jit-log-noopt-loop")
            logops = self._log_operations(inputargs, operations)
            debug_stop("jit-log-noopt-loop")
        else:
            debug_start("jit-log-opt-loop")
            debug_print("# Loop", number, ":", type,
                        "with", len(operations), "ops")
            logops = self._log_operations(inputargs, operations)
            debug_stop("jit-log-opt-loop")
        return logops

    def log_bridge(self, inputargs, operations, number=-1):
        if number == -1:
            debug_start("jit-log-noopt-bridge")
            logops = self._log_operations(inputargs, operations)
            debug_stop("jit-log-noopt-bridge")
        else:
            debug_start("jit-log-opt-bridge")
            debug_print("# bridge out of Guard", number,
                        "with", len(operations), "ops")
            logops = self._log_operations(inputargs, operations)
            debug_stop("jit-log-opt-bridge")
        return logops

    def log_short_preamble(self, inputargs, operations):
        debug_start("jit-log-short-preamble")
        logops = self._log_operations(inputargs, operations)
        debug_stop("jit-log-short-preamble")
        return logops

    def _log_operations(self, inputargs, operations):
        if not have_debug_prints():
            return None
        logops = LogOperations(self.metainterp_sd, self.guard_number)
        logops.log_operations(inputargs, operations)
        return logops


class LogOperations(object):
    """
    ResOperation logger.  Each instance contains a memo giving numbers
    to boxes, and is typically used to log a single loop.
    """
    def __init__(self, metainterp_sd, guard_number):
        self.metainterp_sd = metainterp_sd
        self.ts = metainterp_sd.cpu.ts
        self.guard_number = guard_number
        self.memo = {}

    def repr_of_descr(self, descr):
        return descr.repr_of_descr()

    def repr_of_arg(self, arg):
        try:
            mv = self.memo[arg]
        except KeyError:
            mv = len(self.memo)
            self.memo[arg] = mv
        if isinstance(arg, ConstInt):
            if int_could_be_an_address(arg.value):
                addr = arg.getaddr()
                name = self.metainterp_sd.get_name_from_address(addr)
                if name:
                    return 'ConstClass(' + name + ')'
            return str(arg.value)
        elif isinstance(arg, BoxInt):
            return 'i' + str(mv)
        elif isinstance(arg, self.ts.ConstRef):
            # XXX for ootype, this should also go through get_name_from_address
            return 'ConstPtr(ptr' + str(mv) + ')'
        elif isinstance(arg, self.ts.BoxRef):
            return 'p' + str(mv)
        elif isinstance(arg, ConstFloat):
            return str(arg.getfloat())
        elif isinstance(arg, BoxFloat):
            return 'f' + str(mv)
        elif arg is None:
            return 'None'
        else:
            return '?'

    def repr_of_op(self, op):
        args = ", ".join([self.repr_of_arg(op.getarg(i)) for i in range(op.numargs())])
        if op.result is not None:
            res = self.repr_of_arg(op.result) + " = "
        else:
            res = ""
        is_guard = op.is_guard()
        if op.getdescr() is not None:
            descr = op.getdescr()
            if is_guard and self.guard_number:
                index = self.metainterp_sd.cpu.get_fail_descr_number(descr)
                r = "<Guard%d>" % index
            else:
                r = self.repr_of_descr(descr)
            args += ', descr=' +  r
        if is_guard and op.getfailargs() is not None:
            fail_args = ' [' + ", ".join([self.repr_of_arg(arg)
                                          for arg in op.getfailargs()]) + ']'
        else:
            fail_args = ''
        return res + op.getopname() + '(' + args + ')' + fail_args

    def log_operations(self, inputargs, operations):
        if inputargs is not None:
            args = ", ".join([self.repr_of_arg(arg) for arg in inputargs])
            debug_print('[' + args + ']')
        for i in range(len(operations)):
            op = operations[i]
            if op.getopnum() == rop.DEBUG_MERGE_POINT:
                loc = op.getarg(0)._get_str()
                reclev = op.getarg(1).getint()
                debug_print("debug_merge_point('%s', %s)" % (loc, reclev))
                continue
            debug_print(self.repr_of_op(op))

def int_could_be_an_address(x):
    if we_are_translated():
        x = rffi.cast(lltype.Signed, x)       # force it
        return not (-32768 <= x <= 32767)
    else:
        return isinstance(x, llmemory.AddressAsInt)
