"""This module provides the astbuilder class which is to be used
by GrammarElements to directly build the AST during parsing
without going trhough the nested tuples step
"""

from grammar import BaseGrammarBuilder, AbstractContext
from pypy.interpreter.astcompiler import ast, consts
import pypy.interpreter.pyparser.pysymbol as sym
import pypy.interpreter.pyparser.pytoken as tok

DEBUG_MODE = 0


### Parsing utilites #################################################
def parse_except_clause(tokens):
    """parses 'except' [test [',' test]] ':' suite
    and returns a 4-tuple : (tokens_read, expr1, expr2, except_body)
    """
    clause_length = 1
    # Read until end of except clause (bound by following 'else',
    # or 'except' or end of tokens)
    while clause_length < len(tokens):
        token = tokens[clause_length]
        if isinstance(token, TokenObject) and \
           (token.value == 'except' or token.value == 'else'):
            break
        clause_length += 1
    # if clause_length >= len(tokens):
    #     raise Exception
    if clause_length == 3:
        # case 'except: body'
        return (3, None, None, tokens[2])
    elif clause_length == 4:
        # case 'except Exception: body':
        return (4, tokens[1], None, tokens[3])
    else:
        # case 'except Exception, exc: body'
        return (6, tokens[1], to_lvalue(tokens[3], consts.OP_ASSIGN), tokens[5])


def parse_dotted_names(tokens):
    """parses NAME('.' NAME)* and returns full dotted name

    this function doesn't assume that the <tokens> list ends after the
    last 'NAME' element
    """
    name = tokens[0].value
    l = len(tokens)
    index = 1
    for index in range(1, l, 2):
        token = tokens[index]
        assert isinstance(token, TokenObject)
        if token.name != tok.DOT:
            break
        name = name + '.' + tokens[index+1].value
    return (index, name)

def parse_argument(tokens):
    """parses function call arguments"""
    l = len(tokens)
    index = 0
    arguments = []
    last_token = None
    building_kw = False
    kw_built = False
    stararg_token = None
    dstararg_token = None
    while index < l:
        cur_token = tokens[index]
        index += 1
        if not isinstance(cur_token, TokenObject):
            if not building_kw:
                arguments.append(cur_token)
            # elif kw_built:
            #     raise SyntaxError("non-keyword arg after keyword arg (%s)" % (cur_token))
            else:
                last_token = arguments.pop()
                assert isinstance(last_token, ast.Name) # used by rtyper
                arguments.append(ast.Keyword(last_token.name, cur_token))
                building_kw = False
                kw_built = True
        elif cur_token.name == tok.COMMA:
            continue
        elif cur_token.name == tok.EQUAL:
            building_kw = True
            continue
        elif cur_token.name == tok.STAR or cur_token.name == tok.DOUBLESTAR:
            if cur_token.name == tok.STAR:
                stararg_token = tokens[index]
                index += 1
                if index >= l:
                    break
                index += 2 # Skip COMMA and DOUBLESTAR
            dstararg_token = tokens[index]
            break
    return arguments, stararg_token, dstararg_token


def parse_fpdef(tokens):
    """fpdef: fpdef: NAME | '(' fplist ')'
    fplist: fpdef (',' fpdef)* [',']
    """
    # FIXME: will we need to implement a Stack class to be RPYTHON compliant ?
    stack = [[],] # list of lists
    tokens_read = 0
    to_be_closed = 1 # number of parenthesis to be closed
    result = None
    while to_be_closed > 0:
        token = tokens[tokens_read]
        tokens_read += 1
        if isinstance(token, TokenObject) and token.name == tok.COMMA:
            continue
        elif isinstance(token, TokenObject) and token.name == tok.LPAR:
            stack.append([])
            to_be_closed += 1
        elif isinstance(token, TokenObject) and token.name == tok.RPAR:
            to_be_closed -= 1
            elt = stack.pop()
            if to_be_closed > 0:
                stack[-1].append(tuple(elt))
            else:
                stack.append(tuple(elt))
        else:
            assert isinstance(token, TokenObject)
            stack[-1].append(token.value)
    assert len(stack) == 1, "At the end of parse_fpdef, len(stack) should be 1, got %s" % stack
    return tokens_read, tuple(stack[0])

def parse_arglist(tokens):
    """returns names, defaults, flags"""
    l = len(tokens)
    index = 0
    defaults = []
    names = []
    flags = 0
    while index < l:
        cur_token = tokens[index]
        index += 1
##         if isinstance(cur_token, FPListObject):
##             names.append(cur_token.value)
        if not isinstance(cur_token, TokenObject):
            # XXX: think of another way to write this test
            defaults.append(cur_token)
        elif cur_token.name == tok.COMMA:
            # We could skip test COMMA by incrementing index cleverly
            # but we might do some experiment on the grammar at some point
            continue
        elif cur_token.name == tok.LPAR:
            tokens_read, name = parse_fpdef(tokens[index:])
            index += tokens_read
            names.append(name)
        elif cur_token.name == tok.STAR or cur_token.name == tok.DOUBLESTAR:
            if cur_token.name == tok.STAR:
                cur_token = tokens[index]
                index += 1
                if cur_token.name == tok.NAME:
                    names.append(cur_token.value)
                    flags |= consts.CO_VARARGS
                    index += 1
                    if index >= l:
                        break
                    else:
                        # still more tokens to read
                        cur_token = tokens[index]
                        index += 1
                else:
                    raise ValueError("FIXME: SyntaxError (incomplete varags) ?")
            if cur_token.name != tok.DOUBLESTAR:
                raise ValueError("Unexpected token: %s" % cur_token)
            cur_token = tokens[index]
            index += 1
            if cur_token.name == tok.NAME:
                names.append(cur_token.value)
                flags |= consts.CO_VARKEYWORDS
                index +=  1
            else:
                raise ValueError("FIXME: SyntaxError (incomplete varags) ?")
            if index < l:
                raise ValueError("unexpected token: %s" % tokens[index])
        elif cur_token.name == tok.NAME:
            names.append(cur_token.value)
    return names, defaults, flags


def parse_listcomp(tokens):
    """parses 'for j in k for i in j if i %2 == 0' and returns
    a GenExprFor instance
    XXX: refactor with listmaker ?
    """
    list_fors = []
    ifs = []
    index = 0
    while index < len(tokens):
        if tokens[index].value == 'for':
            index += 1 # skip 'for'
            ass_node = to_lvalue(tokens[index], consts.OP_ASSIGN)
            index += 2 # skip 'in'
            iterable = tokens[index]
            index += 1
            while index < len(tokens) and tokens[index].value == 'if':
                ifs.append(ast.ListCompIf(tokens[index+1]))
                index += 2
            list_fors.append(ast.ListCompFor(ass_node, iterable, ifs))
            ifs = []
        else:
            raise ValueError('Unexpected token: %s' % tokens[index])
    return list_fors


def parse_genexpr_for(tokens):
    """parses 'for j in k for i in j if i %2 == 0' and returns
    a GenExprFor instance
    XXX: if RPYTHON supports to pass a class object to a function,
         we could refactor parse_listcomp and parse_genexpr_for,
         and call :
           - parse_listcomp(tokens, forclass=ast.GenExprFor, ifclass=...)
         or:
           - parse_listcomp(tokens, forclass=ast.ListCompFor, ifclass=...)
    """
    genexpr_fors = []
    ifs = []
    index = 0
    while index < len(tokens):
        if tokens[index].value == 'for':
            index += 1 # skip 'for'
            ass_node = to_lvalue(tokens[index], consts.OP_ASSIGN)
            index += 2 # skip 'in'
            iterable = tokens[index]
            index += 1
            while index < len(tokens) and tokens[index].value == 'if':
                ifs.append(ast.GenExprIf(tokens[index+1]))
                index += 2
            genexpr_fors.append(ast.GenExprFor(ass_node, iterable, ifs))
            ifs = []
        else:
            raise ValueError('Unexpected token: %s' % tokens[index])
    return genexpr_fors


def get_docstring(stmt):
    """parses a Stmt node.
    
    If a docstring if found, the Discard node is **removed**
    from <stmt> and the docstring is returned.

    If no docstring is found, <stmt> is left unchanged
    and None is returned
    """
    if not isinstance(stmt, ast.Stmt):
        return None
    doc = None
    if len(stmt.nodes):
        first_child = stmt.nodes[0]
        if isinstance(first_child, ast.Discard):
            expr = first_child.expr
            if isinstance(expr, ast.Const):
                # This *is* a docstring, remove it from stmt list
                del stmt.nodes[0]
                doc = expr.value
    return doc


def to_lvalue(ast_node, flags):
    if isinstance( ast_node, ast.Name ):
        return ast.AssName( ast_node.name, flags )
    elif isinstance(ast_node, ast.Tuple):
        nodes = []
        for node in ast_node.getChildren():
            nodes.append(to_lvalue(node, flags))
            # nodes.append(ast.AssName(node.name, consts.OP_ASSIGN))
        return ast.AssTuple(nodes)
    elif isinstance(ast_node, ast.List):
        nodes = []
        for node in ast_node.getChildren():
            nodes.append(to_lvalue(node, flags))
            # nodes.append(ast.AssName(node.name, consts.OP_ASSIGN))
        return ast.AssList(nodes)
    elif isinstance(ast_node, ast.Getattr):
        expr = ast_node.expr
        attrname = ast_node.attrname
        return ast.AssAttr(expr, attrname, flags)
    elif isinstance(ast_node, ast.Subscript):
        ast_node.flags = flags
        return ast_node
    elif isinstance(ast_node, ast.Slice):
        ast_node.flags = flags
        return ast_node
    else:
        assert False, "TODO"

def is_augassign( ast_node ):
    if ( isinstance( ast_node, ast.Name ) or
         isinstance( ast_node, ast.Slice ) or
         isinstance( ast_node, ast.Subscript ) or
         isinstance( ast_node, ast.Getattr ) ):
        return True
    return False

def get_atoms( builder, nb ):
    atoms = []
    i = nb
    while i>0:
        obj = builder.pop()
        if isinstance(obj, RuleObject):
            i += obj.count
        else:
            atoms.append( obj )
        i -= 1
    atoms.reverse()
    return atoms
    
def eval_number(value):
    """temporary implementation"""
    return eval(value)

def eval_string(value):
    """temporary implementation"""
    return eval(value)


## misc utilities, especially for power: rule
def reduce_callfunc(obj, arglist):
    """generic factory for CallFunc nodes"""
    assert isinstance(arglist, ArglistObject)
    arguments, stararg, dstararg = arglist.value
    return ast.CallFunc(obj, arguments, stararg, dstararg)        

def reduce_subscript(obj, subscript):
    """generic factory for Subscript nodes"""
    assert isinstance(subscript, SubscriptObject)
    return ast.Subscript(obj, consts.OP_APPLY, subscript.value)

def reduce_slice(obj, sliceobj):
    """generic factory for Slice nodes"""
    assert isinstance(sliceobj, SlicelistObject)
    if sliceobj.name == 'slice':
        start = sliceobj.value[0]
        end = sliceobj.value[1]
        return ast.Slice(obj, consts.OP_APPLY, start, end)
    else:
        return ast.Subscript(obj, consts.OP_APPLY, [ast.Sliceobj(sliceobj.value)])

def parse_attraccess(tokens):
    """parses token list like ['a', '.', 'b', '.', 'c', ...]
    
    and returns an ast node : ast.Getattr(Getattr(Name('a'), 'b'), 'c' ...)
    """
    token = tokens[0]
    # XXX HACK for when parse_attraccess is called from build_decorator
    if isinstance(token, TokenObject):
        result = ast.Name(token.value)
    else:
        result = token
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if isinstance(token, TokenObject) and token.name == tok.DOT:
            index += 1
            token = tokens[index]
            assert isinstance(token, TokenObject)
            result = ast.Getattr(result, token.value)
        elif isinstance(token, ArglistObject):
            result = reduce_callfunc(result, token)
        elif isinstance(token, SubscriptObject):
            result = reduce_subscript(result, token)
        elif isinstance(token, SlicelistObject):
            result = reduce_slice(result, token)
        else:
            assert False, "Don't know how to handle index %s of %s" % (index, tokens)
        index += 1
    return result


## building functions helpers
## --------------------------
##
## Builder functions used to reduce the builder stack into appropriate
## AST nodes. All the builder functions have the same interface
##
## Naming convention:
## to provide a function handler for a grammar rule name yyy
## you should provide a build_yyy( builder, nb ) function
## where builder is the AstBuilder instance used to build the
## ast tree and nb is the number of items this rule is reducing
##
## Example:
## for example if the rule
##    term <- var ( '+' expr )*
## matches
##    x + (2*y) + z
## build_term will be called with nb == 2
## and get_atoms( builder, nb ) should return a list
## of 5 objects : Var TokenObject('+') Expr('2*y') TokenObject('+') Expr('z')
## where Var and Expr are AST subtrees and Token is a not yet
## reduced token
##
## AST_RULES is kept as a dictionnary to be rpython compliant this is the
## main reason why build_* functions are not methods of the AstBuilder class
##

def build_atom(builder, nb):
    atoms = get_atoms( builder, nb )
    top = atoms[0]
    if isinstance(top, TokenObject):
        if top.name == tok.LPAR:
            if len(atoms) == 2:
                builder.push(ast.Tuple([], top.line))
            else:
                builder.push( atoms[1] )
        elif top.name == tok.LSQB:
            if len(atoms) == 2:
                builder.push(ast.List([], top.line))
            else:
                list_node = atoms[1]
                # XXX lineno is not on *every* child class of ast.Node
                #     (will probably crash the annotator, but should be
                #      easily fixed)
                list_node.lineno = top.line
                builder.push(list_node)
        elif top.name == tok.LBRACE:
            items = []
            for index in range(1, len(atoms)-1, 4):
                # a   :   b   ,   c : d
                # ^  +1  +2  +3  +4
                items.append((atoms[index], atoms[index+2]))
            builder.push(ast.Dict(items, top.line))
        elif top.name == tok.NAME:
            builder.push( ast.Name(top.value) )
        elif top.name == tok.NUMBER:
            builder.push( ast.Const(eval_number(top.value)) )
        elif top.name == tok.STRING:
            # need to concatenate strings in atoms
            s = ''
            for token in atoms:
                s += eval_string(token.value)
            builder.push( ast.Const(s) )
            # assert False, "TODO (String)"
        elif top.name == tok.BACKQUOTE:
            builder.push(ast.Backquote(atoms[1]))
        else:
            raise ValueError, "unexpected tokens (%d): %s" % (nb, [str(i) for i in atoms])


def build_power(builder, nb):
    """power: atom trailer* ['**' factor]"""
    atoms = get_atoms(builder, nb)
    if len(atoms) == 1:
        builder.push(atoms[0])
    else:
        if isinstance(atoms[-2], TokenObject) and atoms[-2].name == tok.DOUBLESTAR:
            obj = parse_attraccess(atoms[:-2])
            builder.push(ast.Power([obj, atoms[-1]]))
        else:
            obj = parse_attraccess(atoms)
            builder.push(obj)

def build_factor( builder, nb ):
    atoms = get_atoms( builder, nb )
    if len(atoms) == 1:
        builder.push( atoms[0] )
    elif len(atoms) == 2 and isinstance(atoms[0],TokenObject):
        if atoms[0].name == tok.PLUS:
            builder.push( ast.UnaryAdd( atoms[1] ) )
        if atoms[0].name == tok.MINUS:
            builder.push( ast.UnarySub( atoms[1] ) )
        if atoms[0].name == tok.TILDE:
            builder.push( ast.Invert( atoms[1] ) )

def build_term( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    left = atoms[0]
    for i in range(2,l,2):
        right = atoms[i]
        op = atoms[i-1].name
        if op == tok.STAR:
            left = ast.Mul( [ left, right ] )
        elif op == tok.SLASH:
            left = ast.Div( [ left, right ] )
        elif op == tok.PERCENT:
            left = ast.Mod( [ left, right ] )
        elif op == tok.DOUBLESLASH:
            left = ast.FloorDiv( [ left, right ] )
        else:
            raise ValueError, "unexpected token: %s" % atoms[i-1]
    builder.push( left )

def build_arith_expr( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    left = atoms[0]
    for i in range(2,l,2):
        right = atoms[i]
        op = atoms[i-1].name
        if op == tok.PLUS:
            left = ast.Add( [ left, right ] )
        elif op == tok.MINUS:
            left = ast.Sub( [ left, right ] )
        else:
            raise ValueError, "unexpected token: %s : %s" % atoms[i-1]
    builder.push( left )

def build_shift_expr( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    left = atoms[0]
    for i in range(2,l,2):
        right = atoms[i]
        op = atoms[i-1].name
        if op == tok.LEFTSHIFT:
            left = ast.LeftShift( [ left, right ] )
        elif op == tok.RIGHTSHIFT:
            left = ast.RightShift( [ left, right ] )
        else:
            raise ValueError, "unexpected token: %s : %s" % atoms[i-1]
    builder.push( left )


def build_binary_expr(builder, nb, OP):
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    if l==1:
        builder.push( atoms[0] )
        return
    items = []
    for i in range(0,l,2): # this is atoms not 1
        items.append( atoms[i] )
    builder.push( OP( items ) )
    return

def build_and_expr( builder, nb ):
    return build_binary_expr( builder, nb, ast.Bitand )

def build_xor_expr( builder, nb ):
    return build_binary_expr( builder, nb, ast.Bitxor )

def build_expr( builder, nb ):
    return build_binary_expr( builder, nb, ast.Bitor )

def build_comparison( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    if l == 1:
        builder.push( atoms[0] )
        return
    else:
        # a < b < c is transalted into:
        # Compare(Name('a'), [('<', Name(b)), ('<', Name(c))])
        left_token = atoms[0]
        ops = []
        for i in range(1, l, 2):
            # if tok.name isn't in rpunct, then it should be
            # 'is', 'is not', 'not' or 'not in' => tok.value
            op_name = tok.tok_rpunct.get(atoms[i].name, atoms[i].value)
            ops.append((op_name, atoms[i+1]))
        builder.push(ast.Compare(atoms[0], ops))

def build_comp_op(builder, nb):
    """comp_op reducing has 2 different cases:
     1. There's only one token to reduce => nothing to
        do, just re-push it on the stack
     2. Two tokens to reduce => it's either 'not in' or 'is not',
        so we need to find out which one it is, and re-push a
        single token

    Note: reducing comp_op is needed because reducing comparison
          rules is much easier when we can assume the comparison
          operator is one and only one token on the stack (which
          is not the case, by default, with 'not in' and 'is not')
    """
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    # l==1 means '<', '>', '<=', etc.
    if l == 1:
        builder.push(atoms[0])
    # l==2 means 'not in' or 'is not'
    elif l == 2:
        if atoms[0].value == 'not':
            builder.push(TokenObject(tok.NAME, 'not in', None))
        else:
            builder.push(TokenObject(tok.NAME, 'is not', None))
    else:
        assert False, "TODO" # uh ?
        
def build_and_test( builder, nb ):
    return build_binary_expr( builder, nb, ast.And )

def build_not_test(builder, nb):
    atoms = get_atoms(builder, nb)
    if len(atoms) == 1:
        builder.push(atoms[0])
    elif len(atoms) == 2:
        builder.push(ast.Not(atoms[1]))
    else:
        assert False, "not_test implementation incomplete (%s)" % atoms

def build_test( builder, nb ):
    return build_binary_expr(builder, nb, ast.Or)
    
def build_testlist( builder, nb ):
    return build_binary_expr( builder, nb, ast.Tuple )

def build_expr_stmt( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    if l==1:
        builder.push( ast.Discard( atoms[0] ) )
        return
    op = atoms[1]
    if op.name == tok.EQUAL:
        nodes = []
        for i in range(0,l-2,2):
            lvalue = to_lvalue( atoms[i], consts.OP_ASSIGN )
            nodes.append( lvalue )
        rvalue = atoms[-1]
        builder.push( ast.Assign( nodes, rvalue ) )
        pass
    else:
        assert l==3
        lvalue = atoms[0]
        assert is_augassign( lvalue )
        builder.push( ast.AugAssign( lvalue, op.get_name(), atoms[2] ) )

def return_one( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    assert l == 1, "missing one node in stack"
    builder.push( atoms[0] )
    return

def build_simple_stmt( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    nodes = []
    for n in range(0,l,2):
        node = atoms[n]
        if isinstance(node, TokenObject) and node.name == tok.NEWLINE:
            nodes.append(ast.Discard(ast.Const(None)))
        else:
            nodes.append(node)
    builder.push(ast.Stmt(nodes))

def build_return_stmt(builder, nb):
    atoms = get_atoms(builder, nb)
    if len(atoms) > 2:
        assert False, "return several stmts not implemented"
    elif len(atoms) == 1:
        builder.push(ast.Return(ast.Const(None), None)) # XXX lineno
    else:
        builder.push(ast.Return(atoms[1], None)) # XXX lineno

def build_file_input(builder, nb):
    # FIXME: need to handle docstring !
    doc = None
    stmts = []
    atoms = get_atoms(builder, nb)
    for node in atoms:
        if isinstance(node, ast.Stmt):
            stmts.extend(node.nodes)
        elif isinstance(node, TokenObject) and node.name == tok.ENDMARKER:
            # XXX Can't we just remove the last element of the list ?
            break    
        elif isinstance(node, TokenObject) and node.name == tok.NEWLINE:
            continue
        else:
            stmts.append(node)
    main_stmt = ast.Stmt(stmts)
    doc = get_docstring(main_stmt)
    return builder.push(ast.Module(doc, main_stmt))

def build_single_input( builder, nb ):
    atoms = get_atoms( builder, nb )
    l = len(atoms)
    if l >= 1:
        builder.push(ast.Module(None, atoms[0]))
    else:
        assert False, "Forbidden path"

def build_testlist_gexp(builder, nb):
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    if l == 1:
        builder.push(atoms[0])
        return
    items = []
    if atoms[1].name == tok.COMMA:
        for i in range(0, l, 2): # this is atoms not 1
            items.append(atoms[i])
    else:
        # genfor: 'i for i in j'
        # GenExpr(GenExprInner(Name('i'), [GenExprFor(AssName('i', 'OP_ASSIGN'), Name('j'), [])])))]))
        expr = atoms[0]
        genexpr_for = parse_genexpr_for(atoms[1:])
        builder.push(ast.GenExpr(ast.GenExprInner(expr, genexpr_for)))
        return
    builder.push(ast.Tuple(items))
    return

def build_varargslist(builder, nb):
    pass

def build_lambdef(builder, nb):
    atoms = get_atoms(builder, nb)
    code = atoms[-1]
    names, defaults, flags = parse_arglist(atoms[1:-2])
    builder.push(ast.Lambda(names, defaults, flags, code))


def build_trailer(builder, nb):
    """trailer: '(' ')' | '(' arglist ')' | '[' subscriptlist ']' | '.' NAME
    """
    atoms = get_atoms(builder, nb)
    # Case 1 : '(' ...
    if atoms[0].name == tok.LPAR:
        if len(atoms) == 2: # and atoms[1].token == tok.RPAR:
            builder.push(ArglistObject('arglist', ([], None, None), None))
        elif len(atoms) == 3: # '(' Arglist ')'
            # push arglist on the stack
            builder.push(atoms[1])
    elif atoms[0].name == tok.LSQB:
        if isinstance(atoms[1], SlicelistObject):
            builder.push(atoms[1])
        else:
            subs = []
            for index in range(1, len(atoms), 2):
                subs.append(atoms[index])
            builder.push(SubscriptObject('subscript', subs, None))
    elif len(atoms) == 2:
        # Attribute access: '.' NAME
        # XXX Warning: fails if trailer is used in lvalue
        builder.push(atoms[0])
        builder.push(atoms[1])
        builder.push(TempRuleObject('pending-attr-access', 2, None))
    else:
        assert False, "Trailer reducing implementation incomplete !"

def build_arglist(builder, nb):
    atoms = get_atoms(builder, nb)
    builder.push(ArglistObject('arglist', parse_argument(atoms), None))

def build_subscript(builder, nb):
    """'.' '.' '.' | [test] ':' [test] [':' [test]] | test"""
    atoms = get_atoms(builder, nb)
    if isinstance(atoms[0], TokenObject) and atoms[0].name == tok.DOT:
        # Ellipsis:
        builder.push(ast.Ellipsis())
    elif len(atoms) == 1:
        token = atoms[0]
        if isinstance(token, TokenObject) and token.name == tok.COLON:
            sliceinfos = [None, None, None]
            builder.push(SlicelistObject('slice', sliceinfos, None))
        else:
            # test
            builder.push(atoms[0])
    else: # elif len(atoms) > 1:
        items = []
        sliceinfos = [None, None, None]
        infosindex = 0
        subscript_type = 'subscript'
        for token in atoms:
            if isinstance(token, TokenObject):
                if token.name == tok.COLON:
                    infosindex += 1
                    subscript_type = 'slice'
                # elif token.name == tok.COMMA:
                #     subscript_type = 'subscript'
                else:
                    items.append(token)
                    sliceinfos[infosindex] = token
            else:
                items.append(token)
                sliceinfos[infosindex] = token
        if subscript_type == 'slice':
            if infosindex == 2:
                sliceobj_infos = []
                for value in sliceinfos:
                    if value is None:
                        sliceobj_infos.append(ast.Const(None))
                    else:
                        sliceobj_infos.append(value)
                builder.push(SlicelistObject('sliceobj', sliceobj_infos, None))
            else:
                builder.push(SlicelistObject('slice', sliceinfos, None))
        else:
            builder.push(SubscriptObject('subscript', items, None))

        
def build_listmaker(builder, nb):
    """listmaker: test ( list_for | (',' test)* [','] )"""
    atoms = get_atoms(builder, nb)
    if len(atoms) >= 2 and isinstance(atoms[1], TokenObject) and atoms[1].value == 'for':
        # list comp
        expr = atoms[0]
        list_for = parse_listcomp(atoms[1:])
        builder.push(ast.ListComp(expr, list_for))
    else:
        # regular list building (like in [1, 2, 3,])
        index = 0
        nodes = []
        while index < len(atoms):
            nodes.append(atoms[index])
            index += 2 # skip comas
        builder.push(ast.List(nodes))
    

def build_decorator(builder, nb):
    """decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE"""
    atoms = get_atoms(builder, nb)
    print "***** decorator", atoms
    nodes = []
    # remove '@', '(' and ')' from atoms and use parse_attraccess
    for token in atoms[1:]:
        if isinstance(token, TokenObject) and \
               token.name in (tok.LPAR, tok.RPAR, tok.NEWLINE):
            # skip those ones
            continue
        else:
            nodes.append(token)
    obj = parse_attraccess(nodes)
    builder.push(obj)

def build_funcdef(builder, nb):
    """funcdef: [decorators] 'def' NAME parameters ':' suite
    """
    atoms = get_atoms(builder, nb)
    index = 0
    decorators = []
    decorator_node = None
    while not (isinstance(atoms[index], TokenObject) and atoms[index].value == 'def'):
        decorators.append(atoms[index])
        index += 1
    if decorators:
        decorator_node = ast.Decorators(decorators)
    atoms = atoms[index:]
    funcname = atoms[1]
    arglist = []
    index = 3
    arglist = atoms[3:-3]
    # while not (isinstance(atoms[index], TokenObject) and atoms[index].name == tok.COLON):
    #     arglist.append(atoms[index])
    #     index += 1
    # arglist.pop() # remove ':'
    names, default, flags = parse_arglist(arglist)
    funcname = atoms[1].value
    arglist = atoms[2]
    code = atoms[-1]
    doc = get_docstring(code)
    # FIXME: decorators and docstring !
    builder.push(ast.Function(decorator_node, funcname, names, default, flags, doc, code))


def build_classdef(builder, nb):
    """classdef: 'class' NAME ['(' testlist ')'] ':' suite"""
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    # FIXME: docstring
    classname = atoms[1].value
    if l == 4:
        basenames = []
        body = atoms[3]
    elif l == 7:
        basenames = []
        body = atoms[6]
        base = atoms[3]
        if isinstance(base, ast.Tuple):
            for node in base.nodes:
                basenames.append(node)
        else:
            basenames.append(base)
    doc = get_docstring(body)
    builder.push(ast.Class(classname, basenames, doc, body))

def build_suite(builder, nb):
    """suite: simple_stmt | NEWLINE INDENT stmt+ DEDENT"""
    atoms = get_atoms(builder, nb)
    if len(atoms) == 1:
        builder.push(atoms[0])
    elif len(atoms) == 4:
        # Only one statement for (stmt+)
        stmt = atoms[2]
        if not isinstance(stmt, ast.Stmt):
            stmt = ast.Stmt([stmt])
        builder.push(stmt)
    else:
        # several statements
        stmts = []
        nodes = atoms[2:-1]
        for node in nodes:
            if isinstance(node, ast.Stmt):
                stmts.extend(node.nodes)
            else:
                stmts.append(node)
        builder.push(ast.Stmt(stmts))


def build_if_stmt(builder, nb):
    atoms = get_atoms(builder, nb)
    tests = []
    tests.append((atoms[1], atoms[3]))
    index = 4
    else_ = None
    while index < len(atoms):
        cur_token = atoms[index]
        assert isinstance(cur_token, TokenObject) # rtyper
        if cur_token.value == 'elif':
            tests.append((atoms[index+1], atoms[index+3]))
            index += 4
        else: # cur_token.value == 'else'
            else_ = atoms[index+2]
            break # break is not necessary
    builder.push(ast.If(tests, else_))

def build_pass_stmt(builder, nb):
    """past_stmt: 'pass'"""
    atoms = get_atoms(builder, nb)
    assert len(atoms) == 1
    builder.push(ast.Pass())


def build_break_stmt(builder, nb):
    """past_stmt: 'pass'"""
    atoms = get_atoms(builder, nb)
    assert len(atoms) == 1
    builder.push(ast.Break())


def build_for_stmt(builder, nb):
    """for_stmt: 'for' exprlist 'in' testlist ':' suite ['else' ':' suite]"""
    atoms = get_atoms(builder, nb)
    else_ = None
    # skip 'for'
    assign = to_lvalue(atoms[1], consts.OP_ASSIGN)
    # skip 'in'
    iterable = atoms[3]
    # skip ':'
    body = atoms[5]
    # if there is a "else" statement
    if len(atoms) > 6:
        # skip 'else' and ':'
        else_ = atoms[8]
    builder.push(ast.For(assign, iterable, body, else_))

def build_exprlist(builder, nb):
    atoms = get_atoms(builder, nb)
    if len(atoms) <= 2:
        builder.push(atoms[0])
    else:
        names = []
        for index in range(0, len(atoms), 2):
            names.append(atoms[index])
        builder.push(ast.Tuple(names))

def build_fplist(builder, nb):
    """fplist: fpdef (',' fpdef)* [',']"""
    atoms = get_atoms(builder, nb)
    names = []
    for index in range(0, len(atoms), 2):
        names.append(atoms[index].value)
    builder.push(FPListObject('fplist', tuple(names), None))


def build_while_stmt(builder, nb):
    """while_stmt: 'while' test ':' suite ['else' ':' suite]"""
    atoms = get_atoms(builder, nb)
    else_ = None
    # skip 'while'
    test =  atoms[1]
    # skip ':'
    body = atoms[3]
    # if there is a "else" statement
    if len(atoms) > 4:
        # skip 'else' and ':'
        else_ = atoms[6]
    builder.push(ast.While(test, body, else_))


def build_import_name(builder, nb):
    """import_name: 'import' dotted_as_names

    dotted_as_names: dotted_as_name (',' dotted_as_name)*
    dotted_as_name: dotted_name [NAME NAME]
    dotted_name: NAME ('.' NAME)*

    written in an unfolded way:
    'import' NAME(.NAME)* [NAME NAME], (NAME(.NAME)* [NAME NAME],)*

    XXX: refactor build_import_name and build_import_from
    """
    atoms = get_atoms(builder, nb)
    index = 1 # skip 'import'
    l = len(atoms)
    names = []
    while index < l:
        as_name = None
        # dotted name (a.b.c)
        incr, name = parse_dotted_names(atoms[index:])
        index += incr
        # 'as' value
        if index < l and atoms[index].value == 'as':
            as_name = atoms[index+1].value
            index += 2
        names.append((name, as_name))
        # move forward until next ','
        while index < l and atoms[index].name != tok.COMMA:
            index += 1
        index += 1
    builder.push(ast.Import(names))


def build_import_from(builder, nb):
    """
    import_from: 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)

    import_as_names: import_as_name (',' import_as_name)* [',']
    import_as_name: NAME [NAME NAME]
    """
    atoms = get_atoms(builder, nb)
    index = 1
    incr, from_name = parse_dotted_names(atoms[index:])
    index += (incr + 1) # skip 'import'
    if atoms[index].name == tok.STAR:
        names = [('*', None)]
    else:
        if atoms[index].name == tok.LPAR:
            # mutli-line imports
            tokens = atoms[index+1:-1]
        else:
            tokens = atoms[index:]
        index = 0
        l = len(tokens)
        names = []
        while index < l:
            name = tokens[index].value
            as_name = None
            index += 1
            if index < l:
                if tokens[index].value == 'as':
                    as_name = tokens[index+1].value
                    index += 2
            names.append((name, as_name))
            if index < l: # case ','
                index += 1
    builder.push(ast.From(from_name, names))


def build_yield_stmt(builder, nb):
    atoms = get_atoms(builder, nb)
    builder.push(ast.Yield(atoms[1]))

def build_continue_stmt(builder, nb):
    atoms = get_atoms(builder, nb)
    builder.push(ast.Continue())

def build_del_stmt(builder, nb):
    atoms = get_atoms(builder, nb)
    builder.push(to_lvalue(atoms[1], consts.OP_DELETE))
        

def build_assert_stmt(builder, nb):
    """assert_stmt: 'assert' test [',' test]"""
    atoms = get_atoms(builder, nb)
    test = atoms[1]
    if len(atoms) == 4:
        fail = atoms[3]
    else:
        fail = None
    builder.push(ast.Assert(test, fail))

def build_exec_stmt(builder, nb):
    """exec_stmt: 'exec' expr ['in' test [',' test]]"""
    atoms = get_atoms(builder, nb)
    expr = atoms[1]
    loc = None
    glob = None
    if len(atoms) > 2:
        loc = atoms[3]
        if len(atoms) > 4:
            glob = atoms[5]
    builder.push(ast.Exec(expr, loc, glob))

def build_print_stmt(builder, nb):
    """
    print_stmt: 'print' ( '>>' test [ (',' test)+ [','] ] | [ test (',' test)* [','] ] )
    """
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    items = []
    dest = None
    start = 1
    if l > 1:
        if isinstance(atoms[1], TokenObject) and atoms[1].name == tok.RIGHTSHIFT:
            dest = atoms[2]
            # skip following comma
            start = 4
    for index in range(start, l, 2):
        items.append(atoms[index])
    if isinstance(atoms[-1], TokenObject) and atoms[-1].name == tok.COMMA:
        builder.push(ast.Print(items, dest))
    else:
        builder.push(ast.Printnl(items, dest))

def build_global_stmt(builder, nb):
    """global_stmt: 'global' NAME (',' NAME)*"""
    atoms = get_atoms(builder, nb)
    names = []
    for index in range(1, len(atoms), 2):
        token = atoms[index]
        assert isinstance(token, TokenObject)
        names.append(token.value)
    builder.push(ast.Global(names))


def build_raise_stmt(builder, nb):
    """raise_stmt: 'raise' [test [',' test [',' test]]]"""
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    expr1 = None
    expr2 = None
    expr3 = None
    if l >= 2:
        expr1 = atoms[1]
        if l >= 4:
            expr2 = atoms[3]
            if l == 6:
                expr3 = atoms[5]
    builder.push(ast.Raise(expr1, expr2, expr3))

def build_try_stmt(builder, nb):
    """
    try_stmt: ('try' ':' suite (except_clause ':' suite)+ #diagram:break
               ['else' ':' suite] | 'try' ':' suite 'finally' ':' suite)
    # NB compile.c makes sure that the default except clause is last
    except_clause: 'except' [test [',' test]]
   
    """
    atoms = get_atoms(builder, nb)
    l = len(atoms)
    handlers = []
    else_ = None
    body = atoms[2]
    token = atoms[3]
    assert isinstance(token, TokenObject)
    if token.value == 'finally':
        builder.push(ast.TryFinally(body, atoms[5]))
    else: # token.value == 'except'
        index = 3
        while index < l and atoms[index].value == 'except':
            tokens_read, expr1, expr2, except_body = parse_except_clause(atoms[index:])
            handlers.append((expr1, expr2, except_body))
            index += tokens_read
        if index < l:
            token = atoms[index]
            assert isinstance(token, TokenObject)
            assert token.value == 'else'
            else_ = atoms[index+2] # skip ':'
        builder.push(ast.TryExcept(body, handlers, else_))


ASTRULES = {
#    "single_input" : build_single_input,
    sym.atom : build_atom,
    sym.power : build_power,
    sym.factor : build_factor,
    sym.term : build_term,
    sym.arith_expr : build_arith_expr,
    sym.shift_expr : build_shift_expr,
    sym.and_expr : build_and_expr,
    sym.xor_expr : build_xor_expr,
    sym.expr : build_expr,
    sym.comparison : build_comparison,
    sym.comp_op : build_comp_op,
    sym.and_test : build_and_test,
    sym.not_test : build_not_test,
    sym.test : build_test,
    sym.testlist : build_testlist,
    sym.expr_stmt : build_expr_stmt,
    sym.small_stmt : return_one,
    sym.simple_stmt : build_simple_stmt,
    sym.single_input : build_single_input,
    sym.file_input : build_file_input,
    sym.testlist_gexp : build_testlist_gexp,
    sym.lambdef : build_lambdef,
    sym.varargslist : build_varargslist,
    sym.trailer : build_trailer,
    sym.arglist : build_arglist,
    sym.subscript : build_subscript,
    sym.listmaker : build_listmaker,
    sym.funcdef : build_funcdef,
    sym.classdef : build_classdef,
    sym.return_stmt : build_return_stmt,
    sym.suite : build_suite,
    sym.if_stmt : build_if_stmt,
    sym.pass_stmt : build_pass_stmt,
    sym.break_stmt : build_break_stmt,
    sym.for_stmt : build_for_stmt,
    sym.while_stmt : build_while_stmt,
    sym.import_name : build_import_name,
    sym.import_from : build_import_from,
    sym.yield_stmt : build_yield_stmt,
    sym.continue_stmt : build_continue_stmt,
    sym.del_stmt : build_del_stmt,
    sym.assert_stmt : build_assert_stmt,
    sym.exec_stmt : build_exec_stmt,
    sym.print_stmt : build_print_stmt,
    sym.global_stmt : build_global_stmt,
    sym.raise_stmt : build_raise_stmt,
    sym.try_stmt : build_try_stmt,
    sym.exprlist : build_exprlist,
    sym.decorator : build_decorator,
    # sym.fplist : build_fplist,
    }

## Stack elements definitions ###################################
class RuleObject(ast.Node):
    """A simple object used to wrap a rule or token"""
    def __init__(self, name, count, src ):
        self.name = name
        self.count = count
        self.line = 0 # src.getline()
        self.col = 0  # src.getcol()

    def __str__(self):
        return "<Rule: %s/%d>" % (sym.sym_name[self.name], self.count)

    def __repr__(self):
        return "<Rule: %s/%d>" % (sym.sym_name[self.name], self.count)


class TempRuleObject(RuleObject):
    """used to keep track of how many items get_atom() should pop"""
    def __str__(self):
        return "<Rule: %s/%d>" % (self.name, self.count)

    def __repr__(self):
        return "<Rule: %s/%d>" % (self.name, self.count)

    
class TokenObject(ast.Node):
    """A simple object used to wrap a rule or token"""
    def __init__(self, name, value, src ):
        self.name = name
        self.value = value
        self.count = 0
        self.line = 0 # src.getline()
        self.col = 0  # src.getcol()

    def get_name(self):
        return tok.tok_rpunct.get(self.name,
                                  tok.tok_name.get(self.name, str(self.name)))
        
    def __str__(self):
        return "<Token: (%s,%s)>" % (self.get_name(), self.value)
    
    def __repr__(self):
        return "<Token: (%r,%s)>" % (self.get_name(), self.value)


class FPListObject(ast.Node):
    """store temp informations for fplist"""
    def __init__(self, name, value, src):
        self.name = name
        self.value = value
        self.count = 0
        self.line = 0 # src.getline()
        self.col = 0  # src.getcol()

    def __str__(self):
        return "<FPList: (%s)>" % (self.value,)
    
    def __repr__(self):
        return "<FPList: (%s)>" % (self.value,)
        
# FIXME: The ObjectAccessor family is probably not RPYTHON since
# some attributes have a different type depending on the subclass
class ObjectAccessor(ast.Node):
    """base class for ArglistObject, SubscriptObject and SlicelistObject

    FIXME: think about a more appropriate name
    """
    def __init__(self, name, value, src):
        self.name = name
        self.value = value
        self.count = 0
        self.line = 0 # src.getline()
        self.col = 0  # src.getcol()

class ArglistObject(ObjectAccessor):
    """helper class to build function's arg list

    self.value is the 3-tuple (names, defaults, flags)
    """
    def __str__(self):
        return "<ArgList: (%s, %s, %s)>" % self.value
    
    def __repr__(self):
        return "<ArgList: (%s, %s, %s)>" % self.value
    
class SubscriptObject(ObjectAccessor):
    """helper class to build subscript list
    
    self.value represents the __getitem__ argument
    """
    def __str__(self):
        return "<SubscriptList: (%s)>" % self.value
    
    def __repr__(self):
        return "<SubscriptList: (%s)>" % self.value

class SlicelistObject(ObjectAccessor):
    """helper class to build slice objects

    self.value is a 3-tuple (start, end, step)
    self.name can either be 'slice' or 'sliceobj' depending
    on if a step is specfied or not (see Python's AST
    for more information on that)
    """
    def __str__(self):
        return "<SliceList: (%s)>" % self.value
    
    def __repr__(self):
        return "<SliceList: (%s)>" % self.value
    

class AstBuilderContext(AbstractContext):
    """specific context management for AstBuidler"""
    def __init__(self, rule_stack):
        self.rule_stack = list(rule_stack)

class AstBuilder(BaseGrammarBuilder):
    """A builder that directly produce the AST"""

    def __init__( self, rules=None, debug=0 ):
        BaseGrammarBuilder.__init__(self, rules, debug )
        self.rule_stack = []

    def context(self):
        return AstBuilderContext(self.rule_stack)

    def restore(self, ctx):
        if DEBUG_MODE:
            print "Restoring context (%s)" % (len(ctx.rule_stack))
        assert isinstance(ctx, AstBuilderContext)
        self.rule_stack = ctx.rule_stack

    def pop(self):
        return self.rule_stack.pop(-1)

    def push(self, obj):
        self.rule_stack.append( obj )
        if not isinstance(obj, RuleObject) and not isinstance(obj, TokenObject):
            if DEBUG_MODE:
                print "Pushed:", str(obj), len(self.rule_stack)
        elif isinstance(obj, TempRuleObject):
            if DEBUG_MODE:
                print "Pushed:", str(obj), len(self.rule_stack)            
        # print "\t", self.rule_stack

    def push_tok(self, name, value, src ):
        self.push( TokenObject( name, value, src ) )

    def push_rule(self, name, count, src ):
        self.push( RuleObject( name, count, src ) )

    def alternative( self, rule, source ):
        # Do nothing, keep rule on top of the stack
        rule_stack = self.rule_stack[:]
        if rule.is_root():
            if DEBUG_MODE:
                print "ALT:", sym.sym_name[rule.codename], self.rule_stack
            builder_func = ASTRULES.get(rule.codename, None)
            if builder_func:
                builder_func(self, 1)
            else:
                if DEBUG_MODE:
                    print "No reducing implementation for %s, just push it on stack" % (
                        sym.sym_name[rule.codename])
                self.push_rule(rule.codename, 1, source)
        else:
            self.push_rule(rule.codename, 1, source)
        if DEBUG_MODE > 1:
            show_stack(rule_stack, self.rule_stack)
            x = raw_input("Continue ?")
        return True

    def sequence(self, rule, source, elts_number):
        """ """
        rule_stack = self.rule_stack[:]
        if rule.is_root():
            if DEBUG_MODE:
                print "SEQ:", sym.sym_name[rule.codename]
            builder_func = ASTRULES.get(rule.codename)
            if builder_func:
                # print "REDUCING SEQUENCE %s" % sym.sym_name[rule.codename]
                builder_func(self, elts_number)
            else:
                if DEBUG_MODE:
                    print "No reducing implementation for %s, just push it on stack" % (
                        sym.sym_name[rule.codename])
                self.push_rule(rule.codename, elts_number, source)
        else:
            self.push_rule(rule.codename, elts_number, source)
        if DEBUG_MODE > 1:
            show_stack(rule_stack, self.rule_stack)
            raw_input("Continue ?")
        return True

    def token(self, name, value, source):
        if DEBUG_MODE:
            print "TOK:", tok.tok_name[name], name, value
        self.push_tok(name, value, source)
        return True

def show_stack(before, after):
    """debuggin helper function"""
    size1 = len(before)
    size2 = len(after)
    for i in range(max(size1, size2)):
        if i< size1:
            obj1 = str(before[i])
        else:
            obj1 = "-"
        if i< size2:
            obj2 = str(after[i])
        else:
            obj2 = "-"
        print "% 3d | %30s | %30s" % (i, obj1, obj2)
    
