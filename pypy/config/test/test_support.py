
from cStringIO import StringIO
from pypy.config.support import detect_number_of_processors

cpuinfo = """
processor	: 0

processor	: 1
vendor_id	: GenuineIntel
cpu family	: 6
model		: 37
model name	: Intel(R) Core(TM) i7 CPU       L 620  @ 2.00GHz
stepping	: 2

processor	: 2
vendor_id	: GenuineIntel
cpu family	: 6
model		: 37
model name	: Intel(R) Core(TM) i7 CPU       L 620  @ 2.00GHz
stepping	: 2

processor	: 3
vendor_id	: GenuineIntel
cpu family	: 6
model		: 37
model name	: Intel(R) Core(TM) i7 CPU       L 620  @ 2.00GHz
stepping	: 2
cpu MHz		: 1199.000
cache size	: 4096 KB
physical id	: 0
siblings	: 4
"""

def test_cpuinfo():
    assert detect_number_of_processors(StringIO(cpuinfo)) == 4
    assert detect_number_of_processors('random crap that does not exist') == 1
