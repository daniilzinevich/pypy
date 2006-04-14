import sys
from pypy.translator.translator import TranslationContext
from pypy.rpython.lltypesystem.lltype import *
from pypy.rpython.lltypesystem.rlist import *
from pypy.rpython.lltypesystem.rslice import ll_newslice
from pypy.rpython.rint import signed_repr
from pypy.rpython.test.test_llinterp import interpret, interpret_raises
from pypy.translator.translator import TranslationContext
from pypy.objspace.flow.model import Constant, Variable

# undo the specialization parameter
for n1 in 'get set del'.split():
    for n2 in '','_nonneg':
        name = 'll_%sitem%s' % (n1, n2)
        globals()['_'+name] = globals()[name]
        exec """if 1:
            def %s(*args):
                return _%s(dum_checkidx, *args)
""" % (name, name)
del n1, n2, name

class BaseTestListImpl:

    def check_list(self, l1, expected):
        assert ll_len(l1) == len(expected)
        for i, x in zip(range(len(expected)), expected):
            assert ll_getitem_nonneg(l1, i) == x

    def test_rlist_basic(self):
        l = self.sample_list()
        assert ll_getitem(l, -4) == 42
        assert ll_getitem_nonneg(l, 1) == 43
        assert ll_getitem(l, 2) == 44
        assert ll_getitem(l, 3) == 45
        assert ll_len(l) == 4
        self.check_list(l, [42, 43, 44, 45])

    def test_rlist_set(self):
        l = self.sample_list()
        ll_setitem(l, -1, 99)
        self.check_list(l, [42, 43, 44, 99])
        ll_setitem_nonneg(l, 1, 77)
        self.check_list(l, [42, 77, 44, 99])

    def test_rlist_slice(self):
        l = self.sample_list()
        LIST = typeOf(l).TO
        self.check_list(ll_listslice_startonly(LIST, l, 0), [42, 43, 44, 45])
        self.check_list(ll_listslice_startonly(LIST, l, 1), [43, 44, 45])
        self.check_list(ll_listslice_startonly(LIST, l, 2), [44, 45])
        self.check_list(ll_listslice_startonly(LIST, l, 3), [45])
        self.check_list(ll_listslice_startonly(LIST, l, 4), [])
        for start in range(5):
            for stop in range(start, 8):
                s = ll_newslice(start, stop)
                self.check_list(ll_listslice(LIST, l, s), [42, 43, 44, 45][start:stop])

    def test_rlist_setslice(self):
        n = 100
        for start in range(5):
            for stop in range(start, 5):
                l1 = self.sample_list()
                l2 = self.sample_list()
                expected = [42, 43, 44, 45]
                for i in range(start, stop):
                    expected[i] = n
                    ll_setitem(l2, i, n)
                    n += 1
                s = ll_newslice(start, stop)
                l2 = ll_listslice(typeOf(l2).TO, l2, s)
                ll_listsetslice(l1, s, l2)
                self.check_list(l1, expected)

class TestListImpl(BaseTestListImpl):


    def sample_list(self):    # [42, 43, 44, 45]
        rlist = ListRepr(None, signed_repr)
        rlist.setup()
        l = ll_newlist(rlist.lowleveltype.TO, 3)
        ll_setitem(l, 0, 42)
        ll_setitem(l, -2, 43)
        ll_setitem_nonneg(l, 2, 44)
        ll_append(l, 45)
        return l

    def test_rlist_del(self):
        l = self.sample_list()
        ll_delitem_nonneg(l, 0)
        self.check_list(l, [43, 44, 45])
        ll_delitem(l, -2)
        self.check_list(l, [43, 45])
        ll_delitem(l, 1)
        self.check_list(l, [43])
        ll_delitem(l, 0)
        self.check_list(l, [])

    def test_rlist_extend_concat(self):
        l = self.sample_list()
        ll_extend(l, l)
        self.check_list(l, [42, 43, 44, 45] * 2)
        l1 = ll_concat(typeOf(l).TO, l, l)
        assert typeOf(l1) == typeOf(l)
        assert l1 != l
        self.check_list(l1, [42, 43, 44, 45] * 4)

    def test_rlist_delslice(self):
        l = self.sample_list()
        ll_listdelslice_startonly(l, 3)
        self.check_list(l, [42, 43, 44])
        ll_listdelslice_startonly(l, 0)
        self.check_list(l, [])
        for start in range(5):
            for stop in range(start, 8):
                l = self.sample_list()
                s = ll_newslice(start, stop)
                ll_listdelslice(l, s)
                expected = [42, 43, 44, 45]
                del expected[start:stop]
                self.check_list(l, expected)

class TestFixedSizeListImpl(BaseTestListImpl):

    def sample_list(self):    # [42, 43, 44, 45]
        rlist = FixedSizeListRepr(None, signed_repr)
        rlist.setup()
        l = ll_fixed_newlist(rlist.lowleveltype.TO, 4)
        ll_setitem(l, 0, 42)
        ll_setitem(l, -3, 43)
        ll_setitem_nonneg(l, 2, 44)
        ll_setitem(l, 3, 45)
        return l

    def test_rlist_extend_concat(self):
        l = self.sample_list()
        lvar = TestListImpl.sample_list(TestListImpl())
        ll_extend(lvar, l)
        self.check_list(lvar, [42, 43, 44, 45] * 2)

        l1 = ll_concat(typeOf(l).TO, lvar, l)
        assert typeOf(l1) == typeOf(l)
        assert l1 != l
        self.check_list(l1, [42, 43, 44, 45] * 3)

        l1 = ll_concat(typeOf(l).TO, l, lvar)
        assert typeOf(l1) == typeOf(l)
        assert l1 != l
        self.check_list(l1, [42, 43, 44, 45] * 3)

        lvar1 = ll_concat(typeOf(lvar).TO, lvar, l)
        assert typeOf(lvar1) == typeOf(lvar)
        assert lvar1 != lvar
        self.check_list(l1, [42, 43, 44, 45] * 3)

        lvar1 = ll_concat(typeOf(lvar).TO, l, lvar)
        assert typeOf(lvar1) == typeOf(lvar)
        assert lvar1 != lvar
        self.check_list(lvar1, [42, 43, 44, 45] * 3)


# ____________________________________________________________

class BaseTestListRtyping:

    def test_simple(self):
        def dummyfn():
            l = [10, 20, 30]
            return l[2]
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 30

    def test_append(self):
        def dummyfn():
            l = []
            l.append(50)
            l.append(60)
            l.append(70)
            l.append(80)
            l.append(90)
            return len(l), l[0], l[-1]
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res.item0 == 5 
        assert res.item1 == 50
        assert res.item2 == 90

    def test_len(self):
        def dummyfn():
            l = [5, 10]
            return len(l)
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 2

        def dummyfn():
            l = [5]
            l.append(6)
            return len(l)
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 2

    def test_iterate(self):
        def dummyfn():
            total = 0
            for x in [1, 3, 5, 7, 9]:
                total += x
            return total
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 25
        def dummyfn():
            total = 0
            l = [1, 3, 5, 7]
            l.append(9)
            for x in l:
                total += x
            return total
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 25

    def test_recursive(self):
        def dummyfn(N):
            l = []
            while N > 0:
                l = [l]
                N -= 1
            return len(l)
        res = interpret(dummyfn, [5], type_system=self.ts)
        assert res == 1

        def dummyfn(N):
            l = []
            while N > 0:
                l.append(l)
                N -= 1
            return len(l)
        res = interpret(dummyfn, [5])
        assert res == 5

    def test_add(self):
        def dummyfn():
            l = [5]
            l += [6,7]
            return l + [8]
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res) == [5, 6, 7, 8]

        def dummyfn():
            l = [5]
            l += [6,7]
            l2 =  l + [8]
            l2.append(9)
            return l2
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res) == [5, 6, 7, 8, 9]

    def test_slice(self):
        if self.ts == 'ootype':
            py.test.skip("ootypesystem doesn't support returning tuples of lists, yet")
        def dummyfn():
            l = [5, 6, 7, 8, 9]
            return l[:2], l[1:4], l[3:]
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res.item0) == [5, 6]
        assert self.ll_to_list(res.item1) == [6, 7, 8]
        assert self.ll_to_list(res.item2) == [8, 9]

        def dummyfn():
            l = [5, 6, 7, 8]
            l.append(9)
            return l[:2], l[1:4], l[3:]
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res.item0) == [5, 6]
        assert self.ll_to_list(res.item1) == [6, 7, 8]
        assert self.ll_to_list(res.item2) == [8, 9]

    def test_set_del_item(self):
        def dummyfn():
            l = [5, 6, 7]
            l[1] = 55
            l[-1] = 66
            return l
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res) == [5, 55, 66]

        def dummyfn():
            l = []
            l.append(5)
            l.append(6)
            l.append(7)
            l[1] = 55
            l[-1] = 66
            return l
        res = interpret(dummyfn, [], type_system=self.ts)
        assert self.ll_to_list(res) == [5, 55, 66]

        def dummyfn():
            l = [5, 6, 7]
            l[1] = 55
            l[-1] = 66
            del l[0]
            del l[-1]
            del l[:]
            return len(l)
        res = interpret(dummyfn, [], type_system=self.ts)
        assert res == 0

    def test_setslice(self):
        if self.ts == 'ootype':
            py.test.skip("ootypesystem doesn't support returning tuples of lists, yet")        
        def dummyfn():
            l = [10, 9, 8, 7]
            l[:2] = [6, 5]
            return l[0], l[1], l[2], l[3]
        res = interpret(dummyfn, (), type_system=self.ts)
        assert res.item0 == 6
        assert res.item1 == 5
        assert res.item2 == 8
        assert res.item3 == 7

        def dummyfn():
            l = [10, 9, 8]
            l.append(7)
            l[:2] = [6, 5]
            return l[0], l[1], l[2], l[3]
        res = interpret(dummyfn, (), type_system=self.ts)
        assert res.item0 == 6
        assert res.item1 == 5
        assert res.item2 == 8
        assert res.item3 == 7

    def test_bltn_list(self):
        def dummyfn():
            l1 = [42]
            l2 = list(l1)
            l2[0] = 0
            return l1[0]
        res = interpret(dummyfn, (), type_system=self.ts)
        assert res == 42

    def test_is_true(self):
        def is_true(lst):
            if lst:
                return True
            else:
                return False
        def dummyfn1():
            return is_true(None)
        def dummyfn2():
            return is_true([])
        def dummyfn3():
            return is_true([0])
        assert interpret(dummyfn1, (), type_system=self.ts) == False
        assert interpret(dummyfn2, (), type_system=self.ts) == False
        assert interpret(dummyfn3, (), type_system=self.ts) == True

    def test_list_index_simple(self):
        def dummyfn(i):
            l = [5,6,7,8]
            return l.index(i)
        
        res = interpret(dummyfn, (6,), type_system=self.ts)
        assert res == 1
        interpret_raises(ValueError, dummyfn, [42], type_system=self.ts)


def test_insert_pop():
    def dummyfn():
        l = [6, 7, 8]
        l.insert(0, 5)
        l.insert(1, 42)
        l.pop(2)
        l.pop(0)
        l.pop(-1)
        l.pop()
        return l[-1]
    res = interpret(dummyfn, ())#, view=True)
    assert res == 42

def test_insert_bug():
    def dummyfn(n):
        l = [1]
        l = l[:]
        l.pop(0)
        if n < 0:
            l.insert(0, 42)
        else:
            l.insert(n, 42)
        return l
    res = interpret(dummyfn, [0])
    assert res.ll_length() == 1
    assert res.ll_items()[0] == 42
    res = interpret(dummyfn, [-1])
    assert res.ll_length() == 1
    assert res.ll_items()[0] == 42

def test_inst_pop():
    class A:
        pass
    l = [A(), A()]
    def f(idx):
        try:
            return l.pop(idx)
        except IndexError:
            return None
    res = interpret(f, [1])
    assert ''.join(res.super.typeptr.name) == 'A\00'
        

def test_reverse():
    def dummyfn():
        l = [5, 3, 2]
        l.reverse()
        return l[0]*100 + l[1]*10 + l[2]
    res = interpret(dummyfn, ())
    assert res == 235

    def dummyfn():
        l = [5]
        l.append(3)
        l.append(2)
        l.reverse()
        return l[0]*100 + l[1]*10 + l[2]
    res = interpret(dummyfn, ())
    assert res == 235

def test_prebuilt_list():
    klist = ['a', 'd', 'z', 'k']
    def dummyfn(n):
        return klist[n]
    res = interpret(dummyfn, [0])
    assert res == 'a'
    res = interpret(dummyfn, [3])
    assert res == 'k'
    res = interpret(dummyfn, [-2])
    assert res == 'z'

    klist = ['a', 'd', 'z']
    def mkdummyfn():
        def dummyfn(n):
            klist.append('k')
            return klist[n]
        return dummyfn
    res = interpret(mkdummyfn(), [0])
    assert res == 'a'
    res = interpret(mkdummyfn(), [3])
    assert res == 'k'
    res = interpret(mkdummyfn(), [-2])
    assert res == 'z'

def test_bound_list_method():
    klist = [1, 2, 3]
    # for testing constant methods without actually mutating the constant
    def dummyfn(n):
        klist.extend([])
    interpret(dummyfn, [7])

def test_list_is():
    def dummyfn():
        l1 = []
        return l1 is l1
    res = interpret(dummyfn, [])
    assert res is True
    def dummyfn():
        l2 = [1, 2]
        return l2 is l2
    res = interpret(dummyfn, [])
    assert res is True
    def dummyfn():
        l1 = [2]
        l2 = [1, 2]
        return l1 is l2
    res = interpret(dummyfn, [])
    assert res is False
    def dummyfn():
        l1 = [1, 2]
        l2 = [1]
        l2.append(2)
        return l1 is l2
    res = interpret(dummyfn, [])
    assert res is False

    def dummyfn():
        l1 = None
        l2 = [1, 2]
        return l1 is l2
    res = interpret(dummyfn, [])
    assert res is False

    def dummyfn():
        l1 = None
        l2 = [1]
        l2.append(2)
        return l1 is l2
    res = interpret(dummyfn, [])
    assert res is False

def test_list_compare():
    def fn(i, j, neg=False):
        s1 = [[1, 2, 3], [4, 5, 1], None]
        s2 = [[1, 2, 3], [4, 5, 1], [1], [1, 2], [4, 5, 1, 6],
              [7, 1, 1, 8, 9, 10], None]
        if neg: return s1[i] != s2[i]
        return s1[i] == s2[j]
    for i in range(3):
        for j in range(7):
            for case in False, True:
                res = interpret(fn, [i,j,case])
                assert res is fn(i, j, case)

    def fn(i, j, neg=False):
        s1 = [[1, 2, 3], [4, 5, 1], None]
        l = []
        l.extend([1,2,3])
        s2 = [l, [4, 5, 1], [1], [1, 2], [4, 5, 1, 6],
              [7, 1, 1, 8, 9, 10], None]
        if neg: return s1[i] != s2[i]
        return s1[i] == s2[j]
    for i in range(3):
        for j in range(7):
            for case in False, True:
                res = interpret(fn, [i,j,case])
                assert res is fn(i, j, case)


def test_list_comparestr():
    def fn(i, j, neg=False):
        s1 = [["hell"], ["hello", "world"]]
        s1[0][0] += "o" # ensure no interning
        s2 = [["hello"], ["world"]]
        if neg: return s1[i] != s2[i]
        return s1[i] == s2[j]
    for i in range(2):
        for j in range(2):
            for case in False, True:
                res = interpret(fn, [i,j,case])
                assert res is fn(i, j, case)

class Foo: pass

class Bar(Foo): pass

def test_list_compareinst():
    def fn(i, j, neg=False):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        s1 = [[foo1], [foo2], [bar1]]
        s2 = s1[:]
        if neg: return s1[i] != s2[i]
        return s1[i] == s2[j]
    for i in range(3):
        for j in range(3):
            for case in False, True:
                res = interpret(fn, [i, j, case])
                assert res is fn(i, j, case)

    def fn(i, j, neg=False):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        s1 = [[foo1], [foo2], [bar1]]
        s2 = s1[:]

        s2[0].extend([])
        
        if neg: return s1[i] != s2[i]
        return s1[i] == s2[j]
    for i in range(3):
        for j in range(3):
            for case in False, True:
                res = interpret(fn, [i, j, case])
                assert res is fn(i, j, case)


def test_list_contains():
    def fn(i, neg=False):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        bar2 = Bar()
        lis = [foo1, foo2, bar1]
        args = lis + [bar2]
        if neg : return args[i] not in lis
        return args[i] in lis
    for i in range(4):
        for case in False, True:
            res = interpret(fn, [i, case])
            assert res is fn(i, case)

    def fn(i, neg=False):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        bar2 = Bar()
        lis = [foo1, foo2, bar1]
        lis.append(lis.pop())
        args = lis + [bar2]
        if neg : return args[i] not in lis
        return args[i] in lis
    for i in range(4):
        for case in False, True:
            res = interpret(fn, [i, case])
            assert res is fn(i, case)


def test_not_a_char_list_after_all():
    def fn():
        l = ['h', 'e', 'l', 'l', 'o']
        return 'world' in l
    res = interpret(fn, [])
    assert res is False

def test_list_index():
    def fn(i):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        bar2 = Bar()
        lis = [foo1, foo2, bar1]
        args = lis + [bar2]
        return lis.index(args[i])
    for i in range(4):
        for varsize in False, True:
            try:
                res2 = fn(i)
                res1 = interpret(fn, [i])
                assert res1 == res2
            except Exception, e:
                interpret_raises(e.__class__, fn, [i])

    def fn(i):
        foo1 = Foo()
        foo2 = Foo()
        bar1 = Bar()
        bar2 = Bar()
        lis = [foo1, foo2, bar1]
        args = lis + [bar2]
        lis.append(lis.pop())
        return lis.index(args[i])
    for i in range(4):
        for varsize in False, True:
            try:
                res2 = fn(i)
                res1 = interpret(fn, [i])
                assert res1 == res2
            except Exception, e:
                interpret_raises(e.__class__, fn, [i])


def test_list_str():
    def fn():
        return str([1,2,3])
    
    res = interpret(fn, [])
    assert ''.join(res.chars) == fn()

    def fn():
        return str([[1,2,3]])
    
    res = interpret(fn, [])
    assert ''.join(res.chars) == fn()

    def fn():
        l = [1,2]
        l.append(3)
        return str(l)
    
    res = interpret(fn, [])
    assert ''.join(res.chars) == fn()

    def fn():
        l = [1,2]
        l.append(3)
        return str([l])
    
    res = interpret(fn, [])
    assert ''.join(res.chars) == fn()

def test_list_or_None():
    empty_list = []
    nonempty_list = [1, 2]
    def fn(i):
        test = [None, empty_list, nonempty_list][i]
        if test:
            return 1
        else:
            return 0

    res = interpret(fn, [0])
    assert res == 0
    res = interpret(fn, [1])
    assert res == 0
    res = interpret(fn, [2])
    assert res == 1


    nonempty_list = [1, 2]
    def fn(i):
        empty_list = [1]
        empty_list.pop()
        nonempty_list = []
        nonempty_list.extend([1,2])
        test = [None, empty_list, nonempty_list][i]
        if test:
            return 1
        else:
            return 0

    res = interpret(fn, [0])
    assert res == 0
    res = interpret(fn, [1])
    assert res == 0
    res = interpret(fn, [2])
    assert res == 1
 

def test_inst_list():
    def fn():
        l = [None]
        l[0] = Foo()
        l.append(Bar())
        l2 = [l[1], l[0], l[0]]
        l.extend(l2)
        for x in l2:
            l.append(x)
        x = l.pop()
        x = l.pop()
        x = l.pop()
        x = l2.pop()
        return str(x)+";"+str(l)
    res = interpret(fn, [])
    assert ''.join(res.chars) == '<Foo object>;[<Foo object>, <Bar object>, <Bar object>, <Foo object>, <Foo object>]'

    def fn():
        l = [None] * 2
        l[0] = Foo()
        l[1] = Bar()
        l2 = [l[1], l[0], l[0]]
        l = l + [None] * 3
        i = 2
        for x in l2:
            l[i] = x
            i += 1
        return str(l)
    res = interpret(fn, [])
    assert ''.join(res.chars) == '[<Foo object>, <Bar object>, <Bar object>, <Foo object>, <Foo object>]'

def test_list_slice_minusone():
    def fn(i):
        lst = [i, i+1, i+2]
        lst2 = lst[:-1]
        return lst[-1] * lst2[-1]
    res = interpret(fn, [5])
    assert res == 42

    def fn(i):
        lst = [i, i+1, i+2, 7]
        lst.pop()
        lst2 = lst[:-1]
        return lst[-1] * lst2[-1]
    res = interpret(fn, [5])
    assert res == 42

def test_list_multiply():
    def fn(i):
        lst = [i] * i
        ret = len(lst)
        if ret:
            ret *= lst[-1]
        return ret
    for arg in (1, 9, 0, -1, -27):
        res = interpret(fn, [arg])
        assert res == fn(arg)
    def fn(i):
        lst = [i, i + 1] * i
        ret = len(lst)
        if ret:
            ret *= lst[-1]
        return ret
    for arg in (1, 9, 0, -1, -27):
        res = interpret(fn, [arg])
        assert res == fn(arg)

def test_list_inplace_multiply():
    def fn(i):
        lst = [i]
        lst *= i
        ret = len(lst)
        if ret:
            ret *= lst[-1]
        return ret
    for arg in (1, 9, 0, -1, -27):
        res = interpret(fn, [arg])
        assert res == fn(arg)
    def fn(i):
        lst = [i, i + 1]
        lst *= i
        ret = len(lst)
        if ret:
            ret *= lst[-1]
        return ret
    for arg in (1, 9, 0, -1, -27):
        res = interpret(fn, [arg])
        assert res == fn(arg)

def test_indexerror():
    def fn(i):
        l = [5, 8, 3]
        try:
            l[i] = 99
        except IndexError:
            pass
        try:
            del l[i]
        except IndexError:
            pass
        try:
            return l[2]    # implicit int->PyObj conversion here
        except IndexError:
            return "oups"
    res = interpret(fn, [6])
    assert res._obj.value == 3
    res = interpret(fn, [-2])
    assert res._obj.value == "oups"

    def fn(i):
        l = [5, 8]
        l.append(3)
        try:
            l[i] = 99
        except IndexError:
            pass
        try:
            del l[i]
        except IndexError:
            pass
        try:
            return l[2]    # implicit int->PyObj conversion here
        except IndexError:
            return "oups"
    res = interpret(fn, [6])
    assert res._obj.value == 3
    res = interpret(fn, [-2])
    assert res._obj.value == "oups"

def list_is_clear(lis, idx):
    items = lis._obj.items._obj.items
    for i in range(idx, len(items)):
        if items[i]._obj is not None:
            return False
    return True

def test_no_unneeded_refs():
    def fndel(p, q):
        lis = ["5", "3", "99"]
        assert q >= 0
        assert p >= 0
        del lis[p:q]
        return lis
    def fnpop(n):
        lis = ["5", "3", "99"]
        while n:
            lis.pop()
            n -=1
        return lis
    for i in range(2, 3+1):
        lis = interpret(fndel, [0, i])
        assert list_is_clear(lis, 3-i)
    for i in range(3):
        lis = interpret(fnpop, [i])
        assert list_is_clear(lis, 3-i)

def test_list_basic_ops():
    def list_basic_ops(i=int, j=int):
        l = [1,2,3]
        l.insert(0, 42)
        del l[1]
        l.append(i)
        listlen = len(l)
        l.extend(l) 
        del l[listlen:]
        l += [5,6] 
        l[1] = i
        return l[j]
    for i in range(6): 
        for j in range(6):
            res = interpret(list_basic_ops, [i, j])
            assert res == list_basic_ops(i, j)

def test_valueerror():
    def fn(i):
        l = [4, 7, 3]
        try:
            j = l.index(i)
        except ValueError:
            j = 100
        return j
    res = interpret(fn, [4])
    assert res == 0
    res = interpret(fn, [7])
    assert res == 1
    res = interpret(fn, [3])
    assert res == 2
    res = interpret(fn, [6])
    assert res == 100

    def fn(i):
        l = [5, 8]
        l.append(3)
        try:
            l[i] = 99
        except IndexError:
            pass
        try:
            del l[i]
        except IndexError:
            pass
        try:
            return l[2]    # implicit int->PyObj conversion here
        except IndexError:
            return "oups"
    res = interpret(fn, [6])
    assert res._obj.value == 3
    res = interpret(fn, [-2])
    assert res._obj.value == "oups"

def test_memoryerror():
    def fn(i):
        lst = [0] * i
        lst[i-1] = 5
        return lst[0]
    res = interpret(fn, [1])
    assert res == 5
    res = interpret(fn, [2])
    assert res == 0
    interpret_raises(MemoryError, fn, [sys.maxint])

def test_list_builder():
    def fixed_size_case():
        return [42]
    def variable_size_case():
        lst = []
        lst.append(42)
        return lst

    from pypy.rpython import rgenop
    from pypy.rpython.module import support

    class DummyBlockBuilder:

        def __init__(self):
            self.newblock = rgenop.newblock()
            self.bareblock = support.from_opaque_object(self.newblock.obj)

        def genop(self, opname, args, RESULT_TYPE):
            return rgenop.genop(self.newblock, opname, args,
                                rgenop.constTYPE(RESULT_TYPE))

        def genconst(self, llvalue):
            return rgenop.genconst(llvalue)

        # inspection
        def __getitem__(self, index):
            return self.bareblock.operations[index]

        def __len__(self):
            return len(self.bareblock.operations)


    for fn in [fixed_size_case, variable_size_case]:
        t = TranslationContext()
        t.buildannotator().build_types(fn, [])
        t.buildrtyper().specialize()
        LIST = t.graphs[0].getreturnvar().concretetype.TO
        llop = DummyBlockBuilder()
        v0 = Constant(42)
        v0.concretetype = Signed
        opq_v0 = support.to_opaque_object(v0)
        v1 = Variable()
        v1.concretetype = Signed
        opq_v1 = support.to_opaque_object(v1)
        vr = LIST.list_builder(llop, [opq_v0, opq_v1])
        vr = rgenop.reveal(vr)
        assert len(llop) == 3
        assert llop[0].opname == 'direct_call'
        assert len(llop[0].args) == 3
        assert llop[0].args[1].concretetype == Void
        assert llop[0].args[1].value == LIST
        assert llop[0].args[2].concretetype == Signed
        assert llop[0].args[2].value == 2
        assert llop[0].result is vr
        for op, i, vi in [(llop[1], 0, v0), (llop[2], 1, v1)]:
            assert op.opname == 'direct_call'
            assert len(op.args) == 5
            assert op.args[1].value is dum_nocheck
            assert op.args[2] is vr
            assert op.args[3].concretetype == Signed
            assert op.args[3].value == i
            assert op.args[4] is vi
            assert op.result.concretetype is Void

class Freezing:
    def _freeze_(self):
        return True

def test_voidlist_prebuilt():
    frlist = [Freezing()] * 17
    def mylength(l):
        return len(l)
    def f():
        return mylength(frlist)
    res = interpret(f, [])
    assert res == 17

def test_voidlist_fixed():
    fr = Freezing()
    def f():
        return len([fr, fr])
    res = interpret(f, [])
    assert res == 2

def test_voidlist_nonfixed():
    class Freezing:
        def _freeze_(self):
            return True
    fr = Freezing()
    def f():
        lst = [fr, fr]
        lst.append(fr)
        del lst[1]
        assert lst[0] is fr
        return len(lst)
    res = interpret(f, [])
    assert res == 2


def test_type_erase_fixed_size():
    class A(object):
        pass
    class B(object):
        pass

    def f():
        return [A()], [B()]

    t = TranslationContext()
    s = t.buildannotator().build_types(f, [])
    rtyper = t.buildrtyper()
    rtyper.specialize()

    s_A_list = s.items[0]
    s_B_list = s.items[1]
    
    r_A_list = rtyper.getrepr(s_A_list)
    assert isinstance(r_A_list, FixedSizeListRepr)
    r_B_list = rtyper.getrepr(s_B_list)
    assert isinstance(r_B_list, FixedSizeListRepr)    

    assert r_A_list.lowleveltype == r_B_list.lowleveltype

def test_type_erase_var_size():
    class A(object):
        pass
    class B(object):
        pass

    def f():
        la = [A()]
        lb = [B()]
        la.append(None)
        lb.append(None)
        return la, lb

    t = TranslationContext()
    s = t.buildannotator().build_types(f, [])
    rtyper = t.buildrtyper()
    rtyper.specialize()

    s_A_list = s.items[0]
    s_B_list = s.items[1]
    
    r_A_list = rtyper.getrepr(s_A_list)
    assert isinstance(r_A_list, ListRepr)    
    r_B_list = rtyper.getrepr(s_B_list)
    assert isinstance(r_B_list, ListRepr)    

    assert r_A_list.lowleveltype == r_B_list.lowleveltype


class TestLltypeRtyping(BaseTestListRtyping):

    ts = "lltype"

    def ll_to_list(self, l):
        return map(None, l.ll_items())[:l.ll_length()]

class TestOotypeRtyping(BaseTestListRtyping):

    ts = "ootype"

    def ll_to_list(self, l):
        return l._list[:]
