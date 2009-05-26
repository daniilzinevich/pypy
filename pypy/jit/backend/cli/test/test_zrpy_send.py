import py
from pypy.jit.backend.cli.test.test_zrpy_basic import CliTranslatedJitMixin
from pypy.jit.metainterp.test import test_send


class TestSend(CliTranslatedJitMixin, test_send.TestOOtype):
    # for the individual tests see
    # ====> ../../../metainterp/test/test_send.py

    def test_recursive_call_to_portal_from_blackhole(self):
        py.test.skip('string return values are not supported')

