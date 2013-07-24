from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.gateway import unwrap_spec, WrappedDefault
from pypy.objspace.std import slicetype
from pypy.objspace.std.inttype import wrapint
from pypy.objspace.std.sliceobject import W_SliceObject, normalize_simple_slice
from rpython.rlib import jit
from rpython.rlib.objectmodel import specialize
from rpython.rlib.rarithmetic import ovfcheck
from rpython.rlib.rstring import split, rsplit, replace, startswith, endswith


class StringMethods(object):
    _mixin_ = True

    def _sliced(self, space, s, start, stop, orig_obj):
        assert start >= 0
        assert stop >= 0
        #if start == 0 and stop == len(s) and space.is_w(space.type(orig_obj), space.w_str):
        #    return orig_obj
        return self._new(s[start:stop])

    @specialize.arg(4)
    def _convert_idx_params(self, space, w_start, w_end, upper_bound=False):
        value = self._val(space)
        lenself = len(value)
        start, end = slicetype.unwrap_start_stop(
                space, lenself, w_start, w_end, upper_bound=upper_bound)
        return (value, start, end)

    def descr_eq(self, space, w_other):
        try:
            return space.newbool(self._val(space) == self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented
            if (e.match(space, space.w_UnicodeDecodeError) or
                e.match(space, space.w_UnicodeEncodeError)):
                msg = ("Unicode equal comparison failed to convert both "
                       "arguments to Unicode - interpreting them as being "
                       "unequal")
                space.warn(space.wrap(msg), space.w_UnicodeWarning)
                return space.w_False
            raise

    def descr_ne(self, space, w_other):
        try:
            return space.newbool(self._val(space) != self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented
            if (e.match(space, space.w_UnicodeDecodeError) or
                e.match(space, space.w_UnicodeEncodeError)):
                msg = ("Unicode unequal comparison failed to convert both "
                       "arguments to Unicode - interpreting them as being "
                       "unequal")
                space.warn(space.wrap(msg), space.w_UnicodeWarning)
                return space.w_True
            raise

    def descr_lt(self, space, w_other):
        try:
            return space.newbool(self._val(space) < self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented

    def descr_le(self, space, w_other):
        try:
            return space.newbool(self._val(space) <= self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented

    def descr_gt(self, space, w_other):
        try:
            return space.newbool(self._val(space) > self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented

    def descr_ge(self, space, w_other):
        try:
            return space.newbool(self._val(space) >= self._op_val(space, w_other))
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented

    def descr_len(self, space):
        return space.wrap(self._len())

    #def descr_iter(self, space):
    #    pass

    def descr_contains(self, space, w_sub):
        from pypy.objspace.std.bytearrayobject import W_BytearrayObject
        if (isinstance(self, W_BytearrayObject) and
            space.isinstance_w(w_sub, space.w_int)):
            char = space.int_w(w_sub)
            if not 0 <= char < 256:
                raise OperationError(space.w_ValueError,
                                     space.wrap("byte must be in range(0, 256)"))
            for c in self.data:
                if ord(c) == char:
                    return space.w_True
            return space.w_False
        return space.newbool(self._val(space).find(self._op_val(space, w_sub)) >= 0)

    def descr_add(self, space, w_other):
        return self._new(self._val(space) + self._op_val(space, w_other))

    def descr_mul(self, space, w_times):
        try:
            times = space.getindex_w(w_times, space.w_OverflowError)
        except OperationError, e:
            if e.match(space, space.w_TypeError):
                return space.w_NotImplemented
            raise
        if times <= 0:
            return self.EMPTY
        if self._len() == 1:
            return self._new(self._val(space)[0] * times)
        return self._new(self._val(space) * times)

    def descr_getitem(self, space, w_index):
        if isinstance(w_index, W_SliceObject):
            selfvalue = self._val(space)
            length = len(selfvalue)
            start, stop, step, sl = w_index.indices4(space, length)
            if sl == 0:
                return self.EMPTY
            elif step == 1:
                assert start >= 0 and stop >= 0
                return self._sliced(space, selfvalue, start, stop, self)
            else:
                str = "".join([selfvalue[start + i*step] for i in range(sl)])
            return self._new(str)

        index = space.getindex_w(w_index, space.w_IndexError, "string index")
        selfvalue = self._val(space)
        selflen = len(selfvalue)
        if index < 0:
            index += selflen
        if index < 0 or index >= selflen:
            raise OperationError(space.w_IndexError,
                                 space.wrap("string index out of range"))
        from pypy.objspace.std.bytearrayobject import W_BytearrayObject
        if isinstance(self, W_BytearrayObject):
            return space.wrap(ord(selfvalue[index]))
        #return wrapchar(space, selfvalue[index])
        return self._new(selfvalue[index])

    def descr_getslice(self, space, w_start, w_stop):
        selfvalue = self._val(space)
        start, stop = normalize_simple_slice(space, len(selfvalue), w_start,
                                             w_stop)
        if start == stop:
            return self.EMPTY
        else:
            return self._sliced(space, selfvalue, start, stop, self)

    def descr_capitalize(self, space):
        value = self._val(space)
        if len(value) == 0:
            return self.EMPTY

        builder = self._builder(len(value))
        builder.append(self._upper(value[0]))
        for i in range(1, len(value)):
            builder.append(self._lower(value[i]))
        return self._new(builder.build())

    @unwrap_spec(width=int, w_fillchar=WrappedDefault(' '))
    def descr_center(self, space, width, w_fillchar):
        value = self._val(space)
        fillchar = self._op_val(space, w_fillchar)
        if len(fillchar) != 1:
            raise OperationError(space.w_TypeError,
                space.wrap("center() argument 2 must be a single character"))

        d = width - len(value)
        if d>0:
            offset = d//2 + (d & width & 1)
            fillchar = fillchar[0]    # annotator hint: it's a single character
            u_centered = offset * fillchar + value + (d - offset) * fillchar
        else:
            u_centered = value

        return self._new(u_centered)

    def descr_count(self, space, w_sub, w_start=None, w_end=None):
        value, start, end = self._convert_idx_params(space, w_start, w_end)
        return wrapint(space, value.count(self._op_val(space, w_sub), start, end))

    def descr_decode(self, space, w_encoding=None, w_errors=None):
        from pypy.objspace.std.unicodeobject import _get_encoding_and_errors, \
            unicode_from_string, decode_object
        encoding, errors = _get_encoding_and_errors(space, w_encoding, w_errors)
        if encoding is None and errors is None:
            return unicode_from_string(space, self)
        return decode_object(space, self, encoding, errors)

    def descr_encode(self, space, w_encoding=None, w_errors=None):
        from pypy.objspace.std.unicodeobject import _get_encoding_and_errors, \
            encode_object
        encoding, errors = _get_encoding_and_errors(space, w_encoding, w_errors)
        return encode_object(space, self, encoding, errors)

    @unwrap_spec(tabsize=int)
    def descr_expandtabs(self, space, tabsize=8):
        value = self._val(space)
        if not value:
            return self.EMPTY

        splitted = value.split(self._chr('\t'))
        try:
            ovfcheck(len(splitted) * tabsize)
        except OverflowError:
            raise OperationError(space.w_OverflowError,
                                 space.wrap("new string is too long"))
        expanded = oldtoken = splitted.pop(0)

        for token in splitted:
            expanded += self._chr(' ') * self._tabindent(oldtoken, tabsize) + token
            oldtoken = token

        return self._new(expanded)

    def _tabindent(self, token, tabsize):
        "calculates distance behind the token to the next tabstop"

        distance = tabsize
        if token:
            distance = 0
            offset = len(token)

            while 1:
                if token[offset-1] == "\n" or token[offset-1] == "\r":
                    break
                distance += 1
                offset -= 1
                if offset == 0:
                    break

            # the same like distance = len(token) - (offset + 1)
            distance = (tabsize - distance) % tabsize
            if distance == 0:
                distance = tabsize

        return distance

    def descr_find(self, space, w_sub, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start, w_end)
        res = value.find(self._op_val(space, w_sub), start, end)
        return space.wrap(res)

    def descr_rfind(self, space, w_sub, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start, w_end)
        res = value.rfind(self._op_val(space, w_sub), start, end)
        return space.wrap(res)

    def descr_index(self, space, w_sub, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start, w_end)
        res = value.find(self._op_val(space, w_sub), start, end)
        if res < 0:
            raise OperationError(space.w_ValueError,
                                 space.wrap("substring not found in string.index"))

        return space.wrap(res)

    def descr_rindex(self, space, w_sub, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start, w_end)
        res = value.rfind(self._op_val(space, w_sub), start, end)
        if res < 0:
            raise OperationError(space.w_ValueError,
                                 space.wrap("substring not found in string.rindex"))

        return space.wrap(res)

    @specialize.arg(2)
    def _is_generic(self, space, func_name):
        func = getattr(self, func_name)
        v = self._val(space)
        if len(v) == 0:
            return space.w_False
        if len(v) == 1:
            c = v[0]
            return space.newbool(func(c))
        else:
            return self._is_generic_loop(space, v, func_name)

    @specialize.arg(3)
    def _is_generic_loop(self, space, v, func_name):
        func = getattr(self, func_name)
        for idx in range(len(v)):
            if not func(v[idx]):
                return space.w_False
        return space.w_True

    def descr_isalnum(self, space):
        return self._is_generic(space, '_isalnum')

    def descr_isalpha(self, space):
        return self._is_generic(space, '_isalpha')

    def descr_isdigit(self, space):
        return self._is_generic(space, '_isdigit')

    def descr_islower(self, space):
        v = self._val(space)
        if len(v) == 1:
            c = v[0]
            return space.newbool(c.islower())
        cased = False
        for idx in range(len(v)):
            if v[idx].isupper():
                return space.w_False
            elif not cased and v[idx].islower():
                cased = True
        return space.newbool(cased)

    def descr_isspace(self, space):
        return self._is_generic(space, '_isspace')

    def descr_istitle(self, space):
        input = self._val(space)
        cased = False
        previous_is_cased = False

        for pos in range(0, len(input)):
            ch = input[pos]
            if ch.isupper():
                if previous_is_cased:
                    return space.w_False
                previous_is_cased = True
                cased = True
            elif ch.islower():
                if not previous_is_cased:
                    return space.w_False
                cased = True
            else:
                previous_is_cased = False

        return space.newbool(cased)

    def descr_isupper(self, space):
        v = self._val(space)
        if len(v) == 1:
            c = v[0]
            return space.newbool(c.isupper())
        cased = False
        for idx in range(len(v)):
            if v[idx].islower():
                return space.w_False
            elif not cased and v[idx].isupper():
                cased = True
        return space.newbool(cased)

    def descr_join(self, space, w_list):
        #l = space.listview_str(w_list)
        #if l is not None:
        #    if len(l) == 1:
        #        return space.wrap(l[0])
        #    return space.wrap(self._val(space).join(l))

        list_w = space.listview(w_list)
        size = len(list_w)

        if size == 0:
            return self.EMPTY

        if size == 1:
            w_s = list_w[0]
            # only one item, return it if it's not a subclass of str
            if self._join_return_one(space, w_s):
                return w_s

        return self._str_join_many_items(space, list_w, size)

    @jit.look_inside_iff(lambda self, space, list_w, size:
                         jit.loop_unrolling_heuristic(list_w, size))
    def _str_join_many_items(self, space, list_w, size):
        value = self._val(space)

        prealloc_size = len(value) * (size - 1)
        for i in range(size):
            w_s = list_w[i]
            check_item = self._join_check_item(space, w_s)
            if check_item == 1:
                raise operationerrfmt(
                    space.w_TypeError,
                    "sequence item %d: expected string, %s "
                    "found", i, space.type(w_s).getname(space))
            elif check_item == 2:
                return self._join_autoconvert(space, list_w)
            prealloc_size += len(self._op_val(space, w_s))

        sb = self._builder(prealloc_size)
        for i in range(size):
            if value and i != 0:
                sb.append(value)
            sb.append(self._op_val(space, list_w[i]))
        return self._new(sb.build())

    def _join_autoconvert(self, space, list_w):
        assert False, 'unreachable'

    @unwrap_spec(width=int, w_fillchar=WrappedDefault(' '))
    def descr_ljust(self, space, width, w_fillchar):
        value = self._val(space)
        fillchar = self._op_val(space, w_fillchar)
        if len(fillchar) != 1:
            raise OperationError(space.w_TypeError,
                space.wrap("ljust() argument 2 must be a single character"))

        d = width - len(value)
        if d > 0:
            fillchar = fillchar[0]    # annotator hint: it's a single character
            value += d * fillchar

        return self._new(value)

    @unwrap_spec(width=int, w_fillchar=WrappedDefault(' '))
    def descr_rjust(self, space, width, w_fillchar):
        value = self._val(space)
        fillchar = self._op_val(space, w_fillchar)
        if len(fillchar) != 1:
            raise OperationError(space.w_TypeError,
                space.wrap("rjust() argument 2 must be a single character"))

        d = width - len(value)
        if d > 0:
            fillchar = fillchar[0]    # annotator hint: it's a single character
            value = d * fillchar + value

        return self._new(value)

    def descr_lower(self, space):
        value = self._val(space)
        builder = self._builder(len(value))
        for i in range(len(value)):
            builder.append(self._lower(value[i]))
        return self._new(builder.build())

    def descr_partition(self, space, w_sub):
        value = self._val(space)
        sub = self._op_val(space, w_sub)
        if not sub:
            raise OperationError(space.w_ValueError,
                                 space.wrap("empty separator"))
        pos = value.find(sub)
        if pos == -1:
            return space.newtuple([self, self.EMPTY, self.EMPTY])
        else:
            from pypy.objspace.std.bytearrayobject import W_BytearrayObject
            if isinstance(self, W_BytearrayObject):
                w_sub = self._new(sub)
            return space.newtuple(
                [self._sliced(space, value, 0, pos, value), w_sub,
                 self._sliced(space, value, pos+len(sub), len(value), value)])

    def descr_rpartition(self, space, w_sub):
        value = self._val(space)
        sub = self._op_val(space, w_sub)
        if not sub:
            raise OperationError(space.w_ValueError,
                                 space.wrap("empty separator"))
        pos = value.rfind(sub)
        if pos == -1:
            return space.newtuple([self.EMPTY, self.EMPTY, self])
        else:
            from pypy.objspace.std.bytearrayobject import W_BytearrayObject
            if isinstance(self, W_BytearrayObject):
                w_sub = self._new(sub)
            return space.newtuple(
                [self._sliced(space, value, 0, pos, value), w_sub,
                 self._sliced(space, value, pos+len(sub), len(value), value)])

    @unwrap_spec(count=int)
    def descr_replace(self, space, w_old, w_new, count=-1):
        input = self._val(space)
        sub = self._op_val(space, w_old)
        by = self._op_val(space, w_new)
        try:
            res = replace(input, sub, by, count)
        except OverflowError:
            raise OperationError(space.w_OverflowError,
                                 space.wrap("replace string is too long"))
        return self._new(res)

    @unwrap_spec(maxsplit=int)
    def descr_split(self, space, w_sep=None, maxsplit=-1):
        res = []
        value = self._val(space)
        length = len(value)
        if space.is_none(w_sep):
            i = 0
            while True:
                # find the beginning of the next word
                while i < length:
                    if not value[i].isspace():
                        break   # found
                    i += 1
                else:
                    break  # end of string, finished

                # find the end of the word
                if maxsplit == 0:
                    j = length   # take all the rest of the string
                else:
                    j = i + 1
                    while j < length and not value[j].isspace():
                        j += 1
                    maxsplit -= 1   # NB. if it's already < 0, it stays < 0

                # the word is value[i:j]
                res.append(value[i:j])

                # continue to look from the character following the space after the word
                i = j + 1

            return self._newlist_unwrapped(space, res)

        by = self._op_val(space, w_sep)
        bylen = len(by)
        if bylen == 0:
            raise OperationError(space.w_ValueError, space.wrap("empty separator"))
        res = split(value, by, maxsplit)
        return self._newlist_unwrapped(space, res)

    @unwrap_spec(maxsplit=int)
    def descr_rsplit(self, space, w_sep=None, maxsplit=-1):
        res = []
        value = self._val(space)
        if space.is_none(w_sep):
            i = len(value)-1
            while True:
                # starting from the end, find the end of the next word
                while i >= 0:
                    if not value[i].isspace():
                        break   # found
                    i -= 1
                else:
                    break  # end of string, finished

                # find the start of the word
                # (more precisely, 'j' will be the space character before the word)
                if maxsplit == 0:
                    j = -1   # take all the rest of the string
                else:
                    j = i - 1
                    while j >= 0 and not value[j].isspace():
                        j -= 1
                    maxsplit -= 1   # NB. if it's already < 0, it stays < 0

                # the word is value[j+1:i+1]
                j1 = j + 1
                assert j1 >= 0
                res.append(value[j1:i+1])

                # continue to look from the character before the space before the word
                i = j - 1

            res.reverse()
            return self._newlist_unwrapped(space, res)

        by = self._op_val(space, w_sep)
        bylen = len(by)
        if bylen == 0:
            raise OperationError(space.w_ValueError, space.wrap("empty separator"))
        res = rsplit(value, by, maxsplit)
        return self._newlist_unwrapped(space, res)

    @unwrap_spec(keepends=bool)
    def descr_splitlines(self, space, keepends=False):
        data = self._val(space)
        selflen = len(data)
        strs = []
        i = j = 0
        while i < selflen:
            # Find a line and append it
            while i < selflen and data[i] != '\n' and data[i] != '\r':
                i += 1
            # Skip the line break reading CRLF as one line break
            eol = i
            i += 1
            if i < selflen and data[i-1] == '\r' and data[i] == '\n':
                i += 1
            if keepends:
                eol = i
            strs.append(data[j:eol])
            j = i

        if j < selflen:
            strs.append(data[j:len(data)])
        return self._newlist_unwrapped(space, strs)

    def descr_startswith(self, space, w_prefix, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start, w_end,
                                                       True)
        if space.isinstance_w(w_prefix, space.w_tuple):
            for w_prefix in space.fixedview(w_prefix):
                if self._startswith(space, value, w_prefix, start, end):
                    return space.w_True
            return space.w_False
        return space.newbool(self._startswith(space, value, w_prefix, start, end))

    def _startswith(self, space, value, w_prefix, start, end):
        return startswith(value, self._op_val(space, w_prefix), start, end)

    def descr_endswith(self, space, w_suffix, w_start=None, w_end=None):
        (value, start, end) = self._convert_idx_params(space, w_start,
                                                   w_end, True)

        if space.isinstance_w(w_suffix, space.w_tuple):
            for w_suffix in space.fixedview(w_suffix):
                if self._endswith(space, value, w_suffix, start, end):
                    return space.w_True
            return space.w_False
        return space.newbool(self._endswith(space, value, w_suffix, start, end))

    def _endswith(self, space, value, w_prefix, start, end):
        return endswith(value, self._op_val(space, w_prefix), start, end)

    def _strip(self, space, w_chars, left, right):
        "internal function called by str_xstrip methods"
        value = self._val(space)
        u_chars = self._op_val(space, w_chars)

        lpos = 0
        rpos = len(value)

        if left:
            #print "while %d < %d and -%s- in -%s-:"%(lpos, rpos, value[lpos],w_chars)
            while lpos < rpos and value[lpos] in u_chars:
                lpos += 1

        if right:
            while rpos > lpos and value[rpos - 1] in u_chars:
                rpos -= 1

        assert rpos >= lpos    # annotator hint, don't remove
        return self._sliced(space, value, lpos, rpos, self)

    def _strip_none(self, space, left, right):
        "internal function called by str_xstrip methods"
        value = self._val(space)

        lpos = 0
        rpos = len(value)

        if left:
            #print "while %d < %d and -%s- in -%s-:"%(lpos, rpos, value[lpos],w_chars)
            while lpos < rpos and value[lpos].isspace():
               lpos += 1

        if right:
            while rpos > lpos and value[rpos - 1].isspace():
               rpos -= 1

        assert rpos >= lpos    # annotator hint, don't remove
        return self._sliced(space, value, lpos, rpos, self)

    def descr_strip(self, space, w_chars=None):
        if space.is_none(w_chars):
            return self._strip_none(space, left=1, right=1)
        return self._strip(space, w_chars, left=1, right=1)

    def descr_lstrip(self, space, w_chars=None):
        if space.is_none(w_chars):
            return self._strip_none(space, left=1, right=0)
        return self._strip(space, w_chars, left=1, right=0)

    def descr_rstrip(self, space, w_chars=None):
        if space.is_none(w_chars):
            return self._strip_none(space, left=0, right=1)
        return self._strip(space, w_chars, left=0, right=1)

    def descr_swapcase(self, space):
        selfvalue = self._val(space)
        builder = self._builder(len(selfvalue))
        for i in range(len(selfvalue)):
            ch = selfvalue[i]
            if self._isupper(ch):
                builder.append(self._lower(ch))
            elif self._islower(ch):
                builder.append(self._upper(ch))
            else:
                builder.append(ch)
        return self._new(builder.build())

    def descr_title(self, space):
        selfval = self._val(space)
        if len(selfval) == 0:
            return self

        builder = self._builder(len(selfval))
        previous_is_cased = False
        for pos in range(len(selfval)):
            ch = selfval[pos]
            if not previous_is_cased:
                builder.append(self._upper(ch))
            else:
                builder.append(self._lower(ch))
            previous_is_cased = self._iscased(ch)
        return self._new(builder.build())

    DEFAULT_NOOP_TABLE = ''.join([chr(i) for i in range(256)])

    # for bytes and bytearray, overridden by unicode
    @unwrap_spec(w_deletechars=WrappedDefault(''))
    def descr_translate(self, space, w_table, w_deletechars):
        if space.is_w(w_table, space.w_None):
            table = self.DEFAULT_NOOP_TABLE
        else:
            table = self._op_val(space, w_table)
            if len(table) != 256:
                raise OperationError(
                    space.w_ValueError,
                    space.wrap("translation table must be 256 characters long"))

        string = self._val(space)
        deletechars = self._op_val(space, w_deletechars)
        if len(deletechars) == 0:
            buf = self._builder(len(string))
            for char in string:
                buf.append(table[ord(char)])
        else:
            buf = self._builder()
            deletion_table = [False] * 256
            for c in deletechars:
                deletion_table[ord(c)] = True
            for char in string:
                if not deletion_table[ord(char)]:
                    buf.append(table[ord(char)])
        return self._new(buf.build())

    def descr_upper(self, space):
        value = self._val(space)
        builder = self._builder(len(value))
        for i in range(len(value)):
            builder.append(self._upper(value[i]))
        return self._new(builder.build())

    @unwrap_spec(width=int)
    def descr_zfill(self, space, width):
        selfval = self._val(space)
        if len(selfval) == 0:
            return self._new(self._chr('0') * width)
        num_zeros = width - len(selfval)
        if num_zeros <= 0:
            # cannot return self, in case it is a subclass of str
            return self._new(selfval)

        builder = self._builder(width)
        if len(selfval) > 0 and (selfval[0] == '+' or selfval[0] == '-'):
            # copy sign to first position
            builder.append(selfval[0])
            start = 1
        else:
            start = 0
        builder.append_multiple_char(self._chr('0'), num_zeros)
        builder.append_slice(selfval, start, len(selfval))
        return self._new(builder.build())

    def descr_getnewargs(self, space):
        return space.newtuple([self._new(self._val(space))])
