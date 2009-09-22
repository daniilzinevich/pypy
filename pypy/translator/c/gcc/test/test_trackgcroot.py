import py
import sys, re
from pypy.translator.c.gcc.trackgcroot import format_location
from pypy.translator.c.gcc.trackgcroot import format_callshape
from pypy.translator.c.gcc.trackgcroot import LOC_NOWHERE, LOC_REG
from pypy.translator.c.gcc.trackgcroot import LOC_EBP_BASED, LOC_ESP_BASED
from pypy.translator.c.gcc.trackgcroot import GcRootTracker
from pypy.translator.c.gcc.trackgcroot import FunctionGcRootTracker
from pypy.translator.c.gcc.trackgcroot import compress_callshape
from pypy.translator.c.gcc.trackgcroot import decompress_callshape
from pypy.translator.c.gcc.trackgcroot import OFFSET_LABELS
from StringIO import StringIO

this_dir = py.path.local(__file__).dirpath()


def test_format_location():
    assert format_location(LOC_NOWHERE) == '?'
    assert format_location(LOC_REG | (0<<2)) == '%ebx'
    assert format_location(LOC_REG | (1<<2)) == '%esi'
    assert format_location(LOC_REG | (2<<2)) == '%edi'
    assert format_location(LOC_REG | (3<<2)) == '%ebp'
    assert format_location(LOC_EBP_BASED + 0) == '(%ebp)'
    assert format_location(LOC_EBP_BASED + 4) == '4(%ebp)'
    assert format_location(LOC_EBP_BASED - 4) == '-4(%ebp)'
    assert format_location(LOC_ESP_BASED + 0) == '(%esp)'
    assert format_location(LOC_ESP_BASED + 4) == '4(%esp)'
    assert format_location(LOC_ESP_BASED - 4) == '-4(%esp)'

def test_format_callshape():
    expected = ('{4(%ebp) '               # position of the return address
                '| 8(%ebp), 12(%ebp), 16(%ebp), 20(%ebp) '  # 4 saved regs
                '| 24(%ebp), 28(%ebp)}')                    # GC roots
    assert format_callshape((LOC_EBP_BASED+4,
                             LOC_EBP_BASED+8,
                             LOC_EBP_BASED+12,
                             LOC_EBP_BASED+16,
                             LOC_EBP_BASED+20,
                             LOC_EBP_BASED+24,
                             LOC_EBP_BASED+28)) == expected

def test_compress_callshape():
    shape = (1, -3, 0x1234, -0x5678, 0x234567,
             -0x765432, 0x61626364, -0x41424344)
    bytes = list(compress_callshape(shape))
    print bytes
    assert len(bytes) == 1+1+2+3+4+4+5+5+1
    assert decompress_callshape(bytes) == list(shape)

def test_find_functions_elf():
    source = """\
\t.p2align 4,,15
.globl pypy_g_make_tree
\t.type\tpypy_g_make_tree, @function
\tFOO
\t.size\tpypy_g_make_tree, .-pypy_g_make_tree

\t.p2align 4,,15
.globl pypy_fn2
\t.type\tpypy_fn2, @function
\tBAR
\t.size\tpypy_fn2, .-pypy_fn2
\tMORE STUFF
"""
    lines = source.splitlines(True)
    parts = list(GcRootTracker().find_functions(iter(lines)))
    assert len(parts) == 5
    assert parts[0] == (False, lines[:2])
    assert parts[1] == (True,  lines[2:5])
    assert parts[2] == (False, lines[5:8])
    assert parts[3] == (True,  lines[8:11])
    assert parts[4] == (False, lines[11:])

def test_find_functions_darwin():
    source = """\
\t.text
\t.align 4,0x90
.globl _pypy_g_ll_str__StringR_Ptr_GcStruct_rpy_strin_rpy_strin
_pypy_g_ll_str__StringR_Ptr_GcStruct_rpy_strin_rpy_strin:
L0:
\tFOO
\t.align 4,0x90
_static:
\tSTATIC
\t.align 4,0x90
.globl _pypy_g_ll_issubclass__object_vtablePtr_object_vtablePtr
_pypy_g_ll_issubclass__object_vtablePtr_object_vtablePtr:
\tBAR
\t.cstring
\t.ascii "foo"
\t.text
\t.align 4,0x90
.globl _pypy_g_RPyRaiseException
_pypy_g_RPyRaiseException:
\tBAZ
\t.section stuff
"""
    lines = source.splitlines(True)
    parts = list(GcRootTracker(format='darwin').find_functions(iter(lines)))
    assert len(parts) == 7
    assert parts[0] == (False, lines[:3])
    assert parts[1] == (True,  lines[3:7])
    assert parts[2] == (True,  lines[7:11])
    assert parts[3] == (True,  lines[11:13])
    assert parts[4] == (False, lines[13:18])
    assert parts[5] == (True,  lines[18:20])
    assert parts[6] == (False, lines[20:])

def test_find_functions_mingw32():
    source = """\
\t.text
\t.globl _pypy_g_funccall_valuestack__AccessDirect_None
_pypy_g_funccall_valuestack__AccessDirect_None:
\tpushl %ebp
\tmovl %esp, %ebp
\tsubl $40, %esp
L410:
\tmovl $10, %eax
\tmovl %eax, -12(%ebp)
\tmovl -4(%ebp), %eax
\tmovl L9341(%eax), %eax
\tjmp *%eax
\t.section .rdata,"dr"
\t.align 4
L9341:
\t.long\tL9331
\t.long\tL9332
\t.long\tL9333
\t.long\tL9334
\t.long\tL9335
\t.text
L9331:
L9332:
L9333:
L9334:
L9335:
\tmovl -12(%ebp), %eax
/APP
\t/* GCROOT %eax */
/NO_APP
\tcall\t_someFunction
\tleave
\tret
"""
    lines = source.splitlines(True)
    parts = list(GcRootTracker(format='mingw32').find_functions(iter(lines)))
    assert len(parts) == 2
    assert parts[0] == (False, lines[:2])
    assert parts[1] == (True,  lines[2:])
    lines = parts[1][1]
    tracker = FunctionGcRootTracker(lines, format='mingw32')
    tracker.computegcmaptable(verbose=sys.maxint)

def test_computegcmaptable():
    tests = []
    for format in ('elf', 'darwin'):
        for path in this_dir.join(format).listdir("track*.s"):
            n = path.purebasename[5:]
            try:
                n = int(n)
            except ValueError:
                pass
            tests.append((format, n, path))
    tests.sort()
    for format, _, path in tests:
        yield check_computegcmaptable, format, path

r_globallabel = re.compile(r"([\w]+)=[.]+")
r_expected = re.compile(r"\s*;;\s*expected\s+([{].+[}])")

def check_computegcmaptable(format, path):
    print
    print path.basename
    lines = path.readlines()
    expectedlines = lines[:]
    tracker = FunctionGcRootTracker(lines, format=format)
    table = tracker.computegcmaptable(verbose=sys.maxint)
    tabledict = {}
    seen = {}
    for entry in table:
        print '%s: %s' % (entry[0], format_callshape(entry[1]))
        tabledict[entry[0]] = entry[1]
    # find the ";; expected" lines
    prevline = ""
    for i, line in enumerate(lines):
        match = r_expected.match(line)
        if match:
            expected = match.group(1)
            prevmatch = r_globallabel.match(prevline)
            assert prevmatch, "the computed table is not complete"
            label = prevmatch.group(1)
            assert label in tabledict
            got = tabledict[label]
            assert format_callshape(got) == expected
            seen[label] = True
            expectedlines.insert(i-2, '\t.globl\t%s\n' % (label,))
            expectedlines.insert(i-1, '%s=.+%d\n' % (label, OFFSET_LABELS))
        prevline = line
    assert len(seen) == len(tabledict), (
        "computed table contains unexpected entries:\n%r" %
        [key for key in tabledict if key not in seen])
    assert lines == expectedlines
