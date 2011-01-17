
# Package initialisation
from pypy.interpreter.mixedmodule import MixedModule

names_and_docstrings = {
    'sqrt': "Return the square root of x.",
    'acos': "Return the arc cosine of x.",
    'acosh': "Return the hyperbolic arc cosine of x.",
    'asin': "Return the arc sine of x.",
    'asinh': "Return the hyperbolic arc sine of x.",
    'atan': "Return the arc tangent of x.",
    'atanh': "Return the hyperbolic arc tangent of x.",
    'log': ("log(x[, base]) -> the logarithm of x to the given base.\n"
            "If the base not specified, returns the natural logarithm "
            "(base e) of x."),
    'log10': "Return the base-10 logarithm of x.",
    'exp': "Return the exponential value e**x.",
    }


class Module(MixedModule):
    appleveldefs = {
    }

    interpleveldefs = dict([(name, 'interp_cmath.wrapped_' + name)
                            for name in names_and_docstrings])
