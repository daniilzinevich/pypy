from pypy.jit.metainterp.optimizeopt.optimizer import *
from pypy.jit.metainterp.resoperation import rop, ResOperation
from pypy.jit.metainterp.compile import ResumeGuardDescr
from pypy.jit.metainterp.resume import Snapshot

class OptUnroll(Optimization):
    """Unroll the loop into two iterations. The first one will
    become the preamble or entry bridge (don't think there is a
    distinction anymore)"""
    
    def setup(self):
        self.cloned_operations = []
        for op in self.optimizer.loop.operations:
            self.cloned_operations.append(op.clone())
        
            
    def propagate_forward(self, op):

        if op.getopnum() == rop.JUMP:
            self.force_at_end_of_preamble()
            loop = self.optimizer.loop
            assert op.getdescr() is loop.token
            loop.preamble.operations = self.optimizer.newoperations
            self.optimizer.newoperations = []
            jump_args = op.getarglist()
            op.initarglist([])
            # Exceptions not caught in one iteration should not propagate to the next
            self.optimizer.exception_might_have_happened = False
            inputargs = self.inline(self.cloned_operations,
                                    loop.inputargs, jump_args)
            loop.inputargs = inputargs
            jmp = ResOperation(rop.JUMP, loop.inputargs[:], None)
            jmp.setdescr(loop.token)
            loop.preamble.operations.append(jmp)
        else:
            self.emit_operation(op)

    def inline(self, loop_operations, loop_args, jump_args):
        self.argmap = argmap = {}
        assert len(loop_args) == len(jump_args)
        for i in range(len(loop_args)):
           argmap[loop_args[i]] = jump_args[i]

        for v in self.optimizer.values.values():
            v.last_guard_index = -1 # FIXME: Are there any more indexes stored?
            if not v.is_constant() and v.box:
                v.fromstart = True # XXX do we really need to use an attribute?

        for op in self.optimizer.pure_operations.values():
            v = self.getvalue(op.result)
            v.fromstart = True

        self.snapshot_map = {None: None}
        inputargs = []
        seen_inputargs = {}
        for arg in jump_args:
            boxes = []
            self.getvalue(arg).enum_forced_boxes(boxes, seen_inputargs)
            for a in boxes:
                if not isinstance(a, Const):
                    inputargs.append(a)

        # this loop is equivalent to the main optimization loop in
        # Optimizer.propagate_all_forward
        for newop in loop_operations:
            newop.initarglist([self.inline_arg(a) for a in newop.getarglist()])
            if newop.result:
                old_result = newop.result
                newop.result = newop.result.clonebox()
                argmap[old_result] = newop.result

            descr = newop.getdescr()
            if isinstance(descr, ResumeGuardDescr):
                descr.rd_snapshot = self.inline_snapshot(descr.rd_snapshot)
                
            if newop.getopnum() == rop.JUMP:
                args = []
                for arg in inputargs:
                    arg = argmap[arg]
                    args.append(self.getvalue(arg).force_box())
                newop.initarglist(args + inputargs[len(args):])

            #print 'P: ', str(newop)
            self.emit_operation(newop)

        jmp = self.optimizer.newoperations[-1]
        assert jmp.getopnum() == rop.JUMP
        jumpargs = jmp.getarglist()
        for op in self.optimizer.newoperations:
            #print 'E: ', str(op)
            args = op.getarglist()
            if op.is_guard():
                args = args + op.getfailargs()
            
            for a in args:
                if not isinstance(a, Const) and a in self.optimizer.values:
                    v = self.getvalue(a)
                    if v.fromstart and not v.is_constant():
                        b = v.force_box()
                        if b not in inputargs:
                        #boxes = []
                        #v.enum_forced_boxes(boxes, seen_inputargs)
                        #for b in boxes:
                            inputargs.append(b)
                            newval = self.getvalue(argmap[b])
                            jumpargs.append(newval.force_box())

        jmp.initarglist(jumpargs)
        return inputargs

    def inline_arg(self, arg):
        if isinstance(arg, Const):
            return arg
        return self.argmap[arg]

    def inline_snapshot(self, snapshot):
        if snapshot in self.snapshot_map:
            return self.snapshot_map[snapshot]
        boxes = []
        for a in snapshot.boxes:
            if isinstance(a, Const):
                boxes.append(a)
            else:
                boxes.append(self.inline_arg(a))
        new_snapshot = Snapshot(self.inline_snapshot(snapshot.prev), boxes[:])
        self.snapshot_map[snapshot] = new_snapshot
        return new_snapshot
    

        
        
        
