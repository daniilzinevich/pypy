""" This is a mini-tutorial on iterators, strides, and
memory layout. It assumes you are familiar with the terms, see
http://docs.scipy.org/doc/numpy/reference/arrays.ndarray.html
for a more gentle introduction.

Given an array x: x.shape == [5,6], where each element occupies one byte

At which byte in x.data does the item x[3,4] begin?
if x.strides==[1,5]:
    pData = x.pData + (x.start + 3*1 + 4*5)*sizeof(x.pData[0])
    pData = x.pData + (x.start + 24) * sizeof(x.pData[0])
so the offset of the element is 24 elements after the first

What is the next element in x after coordinates [3,4]?
if x.order =='C':
   next == [3,5] => offset is 28
if x.order =='F':
   next == [4,4] => offset is 24
so for the strides [1,5] x is 'F' contiguous
likewise, for the strides [6,1] x would be 'C' contiguous.

Iterators have an internal representation of the current coordinates
(indices), the array, strides, and backstrides. A short digression to
explain backstrides: what is the coordinate and offset after [3,5] in
the example above?
if x.order == 'C':
   next == [4,0] => offset is 4
if x.order == 'F':
   next == [4,5] => offset is 25
Note that in 'C' order we stepped BACKWARDS 24 while 'overflowing' a
shape dimension
  which is back 25 and forward 1,
  which is x.strides[1] * (x.shape[1] - 1) + x.strides[0]
so if we precalculate the overflow backstride as
[x.strides[i] * (x.shape[i] - 1) for i in range(len(x.shape))]
we can go faster.
All the calculations happen in next()

next_skip_x(steps) tries to do the iteration for a number of steps at once,
but then we cannot gaurentee that we only overflow one single shape
dimension, perhaps we could overflow times in one big step.
"""

from pypy.module.micronumpy.base import W_NDimArray
from pypy.module.micronumpy import support
from rpython.rlib import jit


class PureShapeIterator(object):
    def __init__(self, shape, idx_w):
        self.shape = shape
        self.shapelen = len(shape)
        self.indexes = [0] * len(shape)
        self._done = False
        self.idx_w = [None] * len(idx_w)
        for i, w_idx in enumerate(idx_w):
            if isinstance(w_idx, W_NDimArray):
                self.idx_w[i] = w_idx.create_iter(shape)

    def done(self):
        return self._done

    @jit.unroll_safe
    def next(self):
        for w_idx in self.idx_w:
            if w_idx is not None:
                w_idx.next()
        for i in range(self.shapelen - 1, -1, -1):
            if self.indexes[i] < self.shape[i] - 1:
                self.indexes[i] += 1
                break
            else:
                self.indexes[i] = 0
        else:
            self._done = True

    @jit.unroll_safe
    def get_index(self, space, shapelen):
        return [space.wrap(self.indexes[i]) for i in range(shapelen)]


class BaseArrayIterator(object):
    def next(self):
        raise NotImplementedError  # purely abstract base class

    def setitem(self, elem):
        raise NotImplementedError

    def set_scalar_object(self, value):
        raise NotImplementedError  # works only on scalars


class ConcreteArrayIterator(BaseArrayIterator):
    _immutable_fields_ = ['array', 'skip', 'size']

    def __init__(self, array):
        self.array = array
        self.offset = 0
        self.skip = array.dtype.elsize
        self.size = array.size

    def setitem(self, elem):
        self.array.setitem(self.offset, elem)

    def getitem(self):
        return self.array.getitem(self.offset)

    def getitem_bool(self):
        return self.array.getitem_bool(self.offset)

    def next(self):
        self.offset += self.skip

    def next_skip_x(self, x):
        self.offset += self.skip * x

    def done(self):
        return self.offset >= self.size

    def reset(self):
        self.offset %= self.size


class OneDimViewIterator(ConcreteArrayIterator):
    def __init__(self, array, start, strides, shape):
        self.array = array
        self.offset = start
        self.index = 0
        assert len(strides) == len(shape)
        if len(shape) == 0:
            self.skip = array.dtype.elsize
            self.size = 1
        else:
            assert len(shape) == 1
            self.skip = strides[0]
            self.size = shape[0]

    def next(self):
        self.offset += self.skip
        self.index += 1

    def next_skip_x(self, x):
        self.offset += self.skip * x
        self.index += x

    def done(self):
        return self.index >= self.size

    def reset(self):
        self.offset %= self.size

    def get_index(self, d):
        return self.index


class MultiDimViewIterator(ConcreteArrayIterator):
    def __init__(self, array, start, strides, backstrides, shape):
        self.indexes = [0] * len(shape)
        self.array = array
        self.shape = shape
        self.offset = start
        self.shapelen = len(shape)
        self._done = self.shapelen == 0 or support.product(shape) == 0
        self.strides = strides
        self.backstrides = backstrides
        self.size = array.size

    @jit.unroll_safe
    def next(self):
        offset = self.offset
        for i in range(self.shapelen - 1, -1, -1):
            if self.indexes[i] < self.shape[i] - 1:
                self.indexes[i] += 1
                offset += self.strides[i]
                break
            else:
                self.indexes[i] = 0
                offset -= self.backstrides[i]
        else:
            self._done = True
        self.offset = offset

    @jit.unroll_safe
    def next_skip_x(self, step):
        for i in range(len(self.shape) - 1, -1, -1):
            if self.indexes[i] < self.shape[i] - step:
                self.indexes[i] += step
                self.offset += self.strides[i] * step
                break
            else:
                remaining_step = (self.indexes[i] + step) // self.shape[i]
                this_i_step = step - remaining_step * self.shape[i]
                self.offset += self.strides[i] * this_i_step
                self.indexes[i] = self.indexes[i] + this_i_step
                step = remaining_step
        else:
            self._done = True

    def done(self):
        return self._done

    def reset(self):
        self.offset %= self.size

    def get_index(self, d):
        return self.indexes[d]


class AxisIterator(BaseArrayIterator):
    def __init__(self, array, shape, dim, cumulative):
        self.shape = shape
        strides = array.get_strides()
        backstrides = array.get_backstrides()
        if cumulative:
            self.strides = strides
            self.backstrides = backstrides
        elif len(shape) == len(strides):
            # keepdims = True
            self.strides = strides[:dim] + [0] + strides[dim + 1:]
            self.backstrides = backstrides[:dim] + [0] + backstrides[dim + 1:]
        else:
            self.strides = strides[:dim] + [0] + strides[dim:]
            self.backstrides = backstrides[:dim] + [0] + backstrides[dim:]
        self.first_line = True
        self.indices = [0] * len(shape)
        self._done = array.get_size() == 0
        self.offset = array.start
        self.dim = dim
        self.array = array

    def setitem(self, elem):
        self.array.setitem(self.offset, elem)

    def getitem(self):
        return self.array.getitem(self.offset)

    @jit.unroll_safe
    def next(self):
        for i in range(len(self.shape) - 1, -1, -1):
            if self.indices[i] < self.shape[i] - 1:
                if i == self.dim:
                    self.first_line = False
                self.indices[i] += 1
                self.offset += self.strides[i]
                break
            else:
                if i == self.dim:
                    self.first_line = True
                self.indices[i] = 0
                self.offset -= self.backstrides[i]
        else:
            self._done = True

    def done(self):
        return self._done
