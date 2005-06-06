import types
from pypy.annotation.pairtype import pairtype
from pypy.annotation import model as annmodel
from pypy.annotation.classdef import isclassdef
from pypy.rpython.lltype import *
from pypy.rpython.rmodel import Repr, TyperError, inputconst

#
#  There is one "vtable" per user class, with the following structure:
#  A root class "object" has:
#
#      struct object_vtable {
#          struct object_vtable* parenttypeptr;
#      }
#
#  Every other class X, with parent Y, has the structure:
#
#      struct vtable_X {
#          struct vtable_Y super;   // inlined
#          ...                      // extra class attributes
#      }

# The type of the instances is:
#
#     struct object {       // for the root class
#         struct object_vtable* typeptr;
#     }
#
#     struct X {
#         struct Y super;   // inlined
#         ...               // extra instance attributes
#     }
#

OBJECT_VTABLE = ForwardReference()
TYPEPTR = NonGcPtr(OBJECT_VTABLE)
OBJECT_VTABLE.become(Struct('object_vtable', ('parenttypeptr', TYPEPTR)))

OBJECT = GcStruct('object', ('typeptr', TYPEPTR))


def getclassrepr(rtyper, classdef):
    try:
        result = rtyper.class_reprs[classdef]
    except KeyError:
        result = rtyper.class_reprs[classdef] = ClassRepr(rtyper, classdef)
    return result

def getinstancerepr(rtyper, classdef):
    try:
        result = rtyper.instance_reprs[classdef]
    except KeyError:
        result = rtyper.instance_reprs[classdef] = InstanceRepr(rtyper,classdef)
    return result

class MissingRTypeAttribute(TyperError):
    pass


def cast_vtable_to_typeptr(vtable):
    while typeOf(vtable).TO != OBJECT_VTABLE:
        vtable = vtable.super
    if typeOf(vtable) != TYPEPTR:
        vtable = cast_flags(TYPEPTR, vtable)
    return vtable


class ClassRepr(Repr):
    initialized = False

    def __init__(self, rtyper, classdef):
        self.rtyper = rtyper
        self.classdef = classdef
        self.vtable_type = ForwardReference()
        self.lowleveltype = NonGcPtr(self.vtable_type)

    def __repr__(self):
        if self.classdef is None:
            cls = object
        else:
            cls = self.classdef.cls
        return '<ClassRepr for %s.%s>' % (cls.__module__, cls.__name__)

    def setup(self):
        if self.initialized:
            assert self.initialized == True
            return
        self.initialized = "in progress"
        # NOTE: don't store mutable objects like the dicts below on 'self'
        #       before they are fully built, to avoid strange bugs in case
        #       of recursion where other code would uses these
        #       partially-initialized dicts.
        clsfields = {}
        allmethods = {}
        if self.classdef is None:
            # 'object' root type
            self.vtable_type.become(OBJECT_VTABLE)
        else:
            # class attributes
            llfields = []
            attrs = self.classdef.attrs.items()
            attrs.sort()
            for name, attrdef in attrs:
                if attrdef.readonly:
                    s_value = attrdef.s_value
                    s_value = self.prepare_method(name, s_value, allmethods)
                    r = self.rtyper.getrepr(s_value)
                    mangled_name = 'cls_' + name
                    clsfields[name] = mangled_name, r
                    llfields.append((mangled_name, r.lowleveltype))
            #
            self.rbase = getclassrepr(self.rtyper, self.classdef.basedef)
            self.rbase.setup()
            vtable_type = Struct('%s_vtable' % self.classdef.cls.__name__,
                                 ('super', self.rbase.vtable_type),
                                 *llfields)
            self.vtable_type.become(vtable_type)
            allmethods.update(self.rbase.allmethods)
        self.clsfields = clsfields
        self.allmethods = allmethods
        self.vtable = None
        self.initialized = True

    def prepare_method(self, name, s_value, allmethods):
        # special-casing for methods
        if isinstance(s_value, annmodel.SomePBC):
            debound = {}
            count = 0
            for x, classdef in s_value.prebuiltinstances.items():
                if isclassdef(classdef):
                    if classdef.commonbase(self.classdef) != self.classdef:
                        raise TyperError("methods from PBC set %r don't belong "
                                         "in %r" % (s_value.prebuiltinstances,
                                                    self.classdef.cls))
                    count += 1
                    classdef = True
                debound[x] = classdef
            if count > 0:
                if count != len(s_value.prebuiltinstances):
                    raise TyperError("mixing functions and methods "
                                     "in PBC set %r" % (
                        s_value.prebuiltinstances,))
                s_value = annmodel.SomePBC(debound)
                allmethods[name] = True
        return s_value

    def convert_const(self, value):
        if not isinstance(value, (type, types.ClassType)):
            raise TyperError("not a class: %r" % (value,))
        try:
            subclassdef = self.rtyper.annotator.getuserclasses()[value]
        except KeyError:
            raise TyperError("no classdef: %r" % (value,))
        if self.classdef is not None:
            if self.classdef.commonbase(subclassdef) != self.classdef:
                raise TyperError("not a subclass of %r: %r" % (
                    self.classdef.cls, value))
        #
        return getclassrepr(self.rtyper, subclassdef).getvtable()

    def getvtable(self, cast_to_typeptr=True):
        """Return a ptr to the vtable of this type."""
        if self.vtable is None:
            self.vtable = malloc(self.vtable_type, immortal=True)
            if self.classdef is not None:
                self.setup_vtable(self.vtable, self)
        #
        vtable = self.vtable
        if cast_to_typeptr:
            vtable = cast_vtable_to_typeptr(vtable)
        return vtable

    def setup_vtable(self, vtable, rsubcls):
        """Initialize the 'self' portion of the 'vtable' belonging to the
        given subclass."""
        if self.classdef is None:
            # initialize the 'parenttypeptr' field
            vtable.parenttypeptr = rsubcls.rbase.getvtable()
        else:
            # XXX setup class attributes
            # then initialize the 'super' portion of the vtable
            self.rbase.setup_vtable(vtable.super, rsubcls)

    def fromparentpart(self, v_vtableptr, llops):
        """Return the vtable pointer cast from the parent vtable's type
        to self's vtable type."""
        ctype = inputconst(Void, self.lowleveltype)
        return llops.genop('cast_parent', [ctype, v_vtableptr],
                           resulttype=self.lowleveltype)

    def fromtypeptr(self, vcls, llops):
        """Return the type pointer cast to self's vtable type."""
        if self.classdef is None:
            return vcls
        else:
            v_vtableptr = self.rbase.fromtypeptr(vcls, llops)
            return self.fromparentpart(v_vtableptr, llops)

    def getclsfieldrepr(self, attr):
        """Return the repr used for the given attribute."""
        if attr in self.clsfields:
            mangled_name, r = self.clsfields[attr]
            return r
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            return self.rbase.getfieldrepr(attr)

    def getclsfield(self, vcls, attr, llops):
        """Read the given attribute of 'vcls'."""
        if attr in self.clsfields:
            mangled_name, r = self.clsfields[attr]
            v_vtable = self.fromtypeptr(vcls, llops)
            cname = inputconst(Void, mangled_name)
            return llops.genop('getfield', [v_vtable, cname], resulttype=r)
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            return self.rbase.getclsfield(vcls, attr, llops)

    def setclsfield(self, vcls, attr, vvalue, llops):
        """Write the given attribute of 'vcls'."""
        if attr in self.clsfields:
            mangled_name, r = self.clsfields[attr]
            v_vtable = self.fromtypeptr(vcls, llops)
            cname = inputconst(Void, mangled_name)
            llops.genop('setfield', [v_vtable, cname, vvalue])
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            self.rbase.setclsfield(vcls, attr, vvalue, llops)


def get_type_repr(rtyper):
    return getclassrepr(rtyper, None)

# ____________________________________________________________


class __extend__(annmodel.SomeInstance):
    def rtyper_makerepr(self, rtyper):
        return getinstancerepr(rtyper, self.classdef)


class InstanceRepr(Repr):
    initialized = False

    def __init__(self, rtyper, classdef):
        self.rtyper = rtyper
        self.classdef = classdef
        self.object_type = GcForwardReference()
        self.lowleveltype = GcPtr(self.object_type)

    def __repr__(self):
        if self.classdef is None:
            cls = object
        else:
            cls = self.classdef.cls
        return '<InstanceRepr for %s.%s>' % (cls.__module__, cls.__name__)

    def setup(self):
        if self.initialized:
            assert self.initialized == True
            return
        self.initialized = "in progress"
        # NOTE: don't store mutable objects like the dicts below on 'self'
        #       before they are fully built, to avoid strange bugs in case
        #       of recursion where other code would uses these
        #       partially-initialized dicts.
        self.rclass = getclassrepr(self.rtyper, self.classdef)
        fields = {}
        allinstancefields = {}
        if self.classdef is None:
            fields['__class__'] = 'typeptr', TYPEPTR
            self.object_type.become(OBJECT)
        else:
            # instance attributes
            llfields = []
            attrs = self.classdef.attrs.items()
            attrs.sort()
            for name, attrdef in attrs:
                if not attrdef.readonly:
                    r = self.rtyper.getrepr(attrdef.s_value)
                    mangled_name = 'inst_' + name
                    fields[name] = mangled_name, r
                    llfields.append((mangled_name, r.lowleveltype))
            #
            self.rbase = getinstancerepr(self.rtyper, self.classdef.basedef)
            self.rbase.setup()
            object_type = GcStruct(self.classdef.cls.__name__,
                                   ('super', self.rbase.object_type),
                                   *llfields)
            self.object_type.become(object_type)
            allinstancefields.update(self.rbase.allinstancefields)
        allinstancefields.update(fields)
        self.fields = fields
        self.allinstancefields = allinstancefields
        self.initialized = True

    def convert_const(self, value, targetptr=None, vtable=None):
        if value is None:
            return nullgcptr(self.object_type)
        # we will need the vtable pointer, so ask it first, to let
        # ClassRepr.convert_const() perform all the necessary checks on 'value'
        if vtable is None:
            vtable = self.rclass.convert_const(value.__class__)
        if targetptr is None:
            targetptr = malloc(self.object_type)
        #
        if self.classdef is None:
            # instantiate 'object': should be disallowed, but it's convenient
            # to write convert_const() this way and use itself recursively
            targetptr.typeptr = cast_vtable_to_typeptr(vtable)
        else:
            # build the parent part of the instance
            self.rbase.convert_const(value,
                                     targetptr = targetptr.super,
                                     vtable = vtable)
            # XXX add instance attributes from this level
        return targetptr

    def parentpart(self, vinst, llops):
        """Return the pointer 'vinst' cast to the parent type."""
        cname = inputconst(Void, 'super')
        return llops.genop('getsubstruct', [vinst, cname],
                           resulttype=self.rbase.lowleveltype)

    def getfieldrepr(self, attr):
        """Return the repr used for the given attribute."""
        if attr in self.fields:
            mangled_name, r = self.fields[attr]
            return r
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            return self.rbase.getfieldrepr(attr)

    def getfield(self, vinst, attr, llops):
        """Read the given attribute (or __class__ for the type) of 'vinst'."""
        if attr in self.fields:
            mangled_name, r = self.fields[attr]
            cname = inputconst(Void, mangled_name)
            return llops.genop('getfield', [vinst, cname], resulttype=r)
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            vsuper = self.parentpart(vinst, llops)
            return self.rbase.getfield(vsuper, attr, llops)

    def setfield(self, vinst, attr, vvalue, llops):
        """Write the given attribute (or __class__ for the type) of 'vinst'."""
        if attr in self.fields:
            mangled_name, r = self.fields[attr]
            cname = inputconst(Void, mangled_name)
            llops.genop('setfield', [vinst, cname, vvalue])
        else:
            if self.classdef is None:
                raise MissingRTypeAttribute(attr)
            vsuper = self.parentpart(vinst, llops)
            self.rbase.setfield(vsuper, attr, vvalue, llops)

    def new_instance(self, llops):
        """Build a new instance, without calling __init__."""
        ctype = inputconst(Void, self.object_type)
        vptr = llops.genop('malloc', [ctype],
                           resulttype = GcPtr(self.object_type))
        ctypeptr = inputconst(TYPEPTR, self.rclass.getvtable())
        self.setfield(vptr, '__class__', ctypeptr, llops)
        # initialize instance attributes from their defaults from the class
        flds = self.allinstancefields.keys()
        flds.sort()
        mro = list(self.classdef.getmro())
        mro.reverse()
        for clsdef in mro:
            for fldname in flds:
                if fldname in clsdef.cls.__dict__:
                    mangled_name, r = self.allinstancefields[fldname]
                    value = clsdef.cls.__dict__[fldname]
                    cvalue = inputconst(r, value)
                    self.setfield(vptr, fldname, cvalue, llops)
        return vptr

    def rtype_type(self, hop):
        vinst, = hop.inputargs(self)
        return self.getfield(vinst, '__class__', hop.llops)

    def rtype_getattr(self, hop):
        attr = hop.args_s[1].const
        vinst, vattr = hop.inputargs(self, Void)
        if attr in self.allinstancefields:
            return self.getfield(vinst, attr, hop.llops)
        elif attr in self.rclass.allmethods:
            # special case for methods: represented as their 'self' only
            # (see MethodsPBCRepr)
            return vinst
        else:
            vcls = self.getfield(vinst, '__class__', hop.llops)
            return self.rclass.getclsfield(vcls, attr, hop.llops)

    def rtype_setattr(self, hop):
        attr = hop.args_s[1].const
        r_value = self.getfieldrepr(attr)
        vinst, vattr, vvalue = hop.inputargs(self, Void, r_value)
        self.setfield(vinst, attr, vvalue, hop.llops)


# ____________________________________________________________

def rtype_new_instance(cls, hop):
    classdef = hop.rtyper.annotator.getuserclasses()[cls]
    rinstance = getinstancerepr(hop.rtyper, classdef)
    return rinstance.new_instance(hop.llops)
