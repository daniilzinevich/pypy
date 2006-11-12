import py
from pypy.lang.prolog.interpreter import engine, helper, term, error
from pypy.lang.prolog.builtin.register import expose_builtin

# ___________________________________________________________________
# arithmetic


def impl_between(engine, lower, upper, varorint, continuation):
    if isinstance(varorint, term.Var):
        for i in range(lower, upper):
            oldstate = engine.frame.branch()
            try:
                varorint.unify(term.Number(i), engine.frame)
                return continuation.call(engine)
            except error.UnificationFailed:
                engine.frame.revert(oldstate)
        varorint.unify(term.Number(upper), engine.frame)
        return continuation.call(engine)
    else:
        integer = helper.unwrap_int(varorint)
        if not (lower <= integer <= upper):
            raise error.UnificationFailed
    return continuation.call(engine)
expose_builtin(impl_between, "between", unwrap_spec=["int", "int", "obj"],
               handles_continuation=True)

def impl_is(engine, var, num):
    var.unify(num, engine.frame)
expose_builtin(impl_is, "is", unwrap_spec=["raw", "arithmetic"])

for ext, prolog, python in [("eq", "=:=", "=="),
                            ("ne", "=\\=", "!="),
                            ("lt", "<", "<"),
                            ("le", "=<", "<="),
                            ("gt", ">", ">"),
                            ("ge", ">=", ">=")]:
    exec py.code.Source("""
def impl_arith_%s(engine, num1, num2):
    eq = False
    if isinstance(num1, term.Number):
        if isinstance(num2, term.Number):
            eq = num1.num %s num2.num
    elif isinstance(num1, term.Float):
        if isinstance(num2, term.Float):
            eq = num1.num %s num2.num
    if not eq:
        raise error.UnificationFailed()""" % (ext, python, python)).compile()
    expose_builtin(globals()["impl_arith_%s" % (ext, )], prolog,
                   unwrap_spec=["arithmetic", "arithmetic"])
 
