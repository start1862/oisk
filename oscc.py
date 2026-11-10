#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""oscc.py - C subset compiler for OISC (SUBLEQ target).

Supports:
  - int, pointer types, global vars, arrays, functions
  - statements: if/else, while, for, return, block, expr-statement
  - expressions: + - * / % << >> & | ^ ~ ! && || == != < <= > >=
                 unary - & * (cast), function calls, assignments
  - control flow: the SUBLEQ branch is mem[B]<=0 -> jump C.  We compile
    every (int) value into a scratch "register model": a set of global
    slots (acc-style).  We keep it SIMPLE and CORRECT: all temps are
    global slots, all local variables live in a per-call frame array
    (subscripted by a frame pointer slot).  Recursion works because we
    push/pop frames on a global stack.  Function args & return passed
    through a tiny ABI on global slots.

ABI:
  - arg slots: A0..A3 (int) / pointers passed as int (word addresses!)
  - return: R0
  - fp (frame pointer) slot; calling convention: caller writes A0..,
    jump sub program, callee prologue pushes fp, epilogue pops and
    returns via return-address slot RA.

This is an intentionally small but real compiler used to build a
minimal OISC Linux-like kernel and userspace.

NOTE: The generated code uses the `osma` Asm API (labels, slots, consts,
mmio, cells).
"""
import struct
import sys
import re

from osma import Asm, Sym, L, C, S, R, G
from osma import write_words
from preproc import preprocess


# ------------------------------------------------------------------
# Tokenizer
# ------------------------------------------------------------------
class Tok:
    __slots__ = ('kind', 'val', 'line')

    def __init__(self, kind, val, line):
        self.kind = kind
        self.val = val
        self.line = line

    def __repr__(self):
        return 'Tok(%s,%r)' % (self.kind, self.val)


KEYWORDS = {'int', 'void', 'char', 'if', 'else', 'while', 'for', 'do',
            'return', 'break', 'continue', 'unsigned', 'long', 'short',
            'signed', 'static', 'extern', 'struct', 'typedef', 'enum',
            'const', 'volatile', 'inline'}


def tokenize(src):
    toks = []
    i = 0
    n = len(src)
    line = 1
    while i < n:
        c = src[i]
        if c in ' \t\r':
            i += 1
            continue
        if c == '\n':
            line += 1
            i += 1
            continue
        if src.startswith('//', i):
            j = src.find('\n', i)
            if j < 0:
                break
            i = j
            continue
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            if j < 0:
                break
            # count newlines
            line += src.count('\n', i, j)
            i = j + 2
            continue
        # number
        if c.isdigit():
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            raw = src[i:j]
            # strip C integer suffixes (U/UL/ULL/L...).  The tokeniser reads
            # alnum greedily, so "0x10C7UL" lands here as one token; Python's
            # int(tok, 0) would choke on the trailing UL.
            m = re.match(r'(0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)[uUlL]*', raw)
            if m:
                raw = m.group(1)
            toks.append(Tok('num', raw, line))
            i = j
            continue
        # identifier
        if c.isalpha() or c == '_':
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            word = src[i:j]
            kind = 'kw' if word in KEYWORDS else 'id'
            toks.append(Tok(kind, word, line))
            i = j
            continue
        # string literal
        if c == '"':
            j = i + 1
            val = []
            while j < n and src[j] != '"':
                if src[j] == '\\' and j + 1 < n:
                    e = src[j + 1]
                    if e == 'n':
                        val.append(10)
                    elif e == 't':
                        val.append(9)
                    elif e == 'r':
                        val.append(13)
                    elif e == '\\':
                        val.append(92)
                    elif e == '"':
                        val.append(34)
                    elif e == '0':
                        val.append(0)
                    else:
                        val.append(ord(e))
                    j += 2
                else:
                    if src[j] == '\n':
                        line += 1
                    val.append(ord(src[j]))
                    j += 1
            toks.append(Tok('str', bytes(val), line))
            i = j + 1
            continue
        # char literal
        if c == "'":
            j = i + 1
            if j < n and src[j] == '\\':
                e = src[j + 1]
                v = {'n': 10, 't': 9, 'r': 13, '\\': 92, "'": 39,
                     '0': 0}.get(e, ord(e))
                j += 2
            else:
                v = ord(src[j])
                j += 1
            toks.append(Tok('num', str(v), line))
            i = j + 1
            continue
        # operators
        two = {'==': 1, '!=': 1, '<=': 1, '>=': 1, '&&': 1, '||': 1,
               '<<': 1, '>>': 1, '++': 1, '--': 1, '+=': 1, '-=': 1,
               '*=': 1, '/=': 1, '%=': 1, '&=': 1, '|=': 1, '^=': 1,
               '->': 1}
        if i + 1 < n and src[i:i + 2] in two:
            toks.append(Tok('op', src[i:i + 2], line))
            i += 2
            continue
        if c in '+-*(){}[];,<>=!&|^~%?:/.':
            toks.append(Tok('op', c, line))
            i += 1
            continue
        raise SyntaxError('bad char %r at line %d' % (c, line))
    toks.append(Tok('eof', '', line))
    return toks


# ------------------------------------------------------------------
# Parser (C subset)
# ------------------------------------------------------------------
class Type:
    def __init__(self, base='int', ptr=0, arr=None, tag=None, align=1):
        self.base = base        # 'int','void','char','struct','enum'
        self.ptr = ptr          # indirection count
        self.arr = arr          # array length or None
        self.tag = tag          # struct/enum tag name when base is struct/enum
        self.align = align
    def __repr__(self):
        s = self.base + '*' * self.ptr
        if self.tag:
            s += '<%s>' % self.tag
        if self.arr:
            s += '[%d]' % self.arr
        return s
    def size(self):
        if self.arr:
            return self.arr
        return 1
    def clone(self):
        return Type(self.base, self.ptr, self.arr, self.tag, self.align)


class Node:
    pass


class Glob(Node):
    def __init__(self, name, typ, init):
        self.name = name
        self.typ = typ
        self.init = init


class Func(Node):
    def __init__(self, name, ret, params, body, plist):
        self.name = name
        self.ret = ret
        self.params = params
        self.body = body
        self.plist = plist


class FnDecl(Node):
    def __init__(self, name, ret, params, plist):
        self.name = name
        self.ret = ret
        self.params = None
        self.plist = plist


class Block(Node):
    def __init__(self, stmts):
        self.stmts = stmts


class If(Node):
    def __init__(self, cond, then, els):
        self.cond = cond
        self.then = then
        self.els = els


class While(Node):
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body


class DoWhile(Node):
    def __init__(self, body, cond):
        self.body = body
        self.cond = cond


class For(Node):
    def __init__(self, init, cond, post, body):
        self.init = init
        self.cond = cond
        self.post = post
        self.body = body


class Ret(Node):
    def __init__(self, expr):
        self.expr = expr


class Break(Node):
    pass


class Cont(Node):
    pass


class ExprStmt(Node):
    def __init__(self, expr):
        self.expr = expr


class VarDecl(Node):
    def __init__(self, name, typ, init):
        self.name = name
        self.typ = typ
        self.init = init


class Empty(Node):
    pass


# expressions
class Num(Node):
    def __init__(self, v):
        self.v = v


class Str(Node):
    def __init__(self, data):
        self.data = data      # bytes


class Name(Node):
    def __init__(self, name):
        self.name = name


class Unary(Node):
    def __init__(self, op, e):
        self.op = op
        self.e = e


class Binary(Node):
    def __init__(self, op, l, r):
        self.op = op
        self.l = l
        self.r = r


class Assign(Node):
    def __init__(self, op, l, r):
        self.op = op
        self.l = l
        self.r = r


class Call(Node):
    def __init__(self, name, args):
        self.name = name
        self.args = args


class Index(Node):
    def __init__(self, base, idx, step=1):
        self.base = base
        self.idx = idx
        self.step = step       # element size in words (for scaling)


class Member(Node):
    def __init__(self, base, field, offset=0):
        self.base = base
        self.field = field
        self.offset = offset     # word offset of field within struct


class Cond(Node):
    def __init__(self, c, t, e):
        self.c = c
        self.t = t
        self.e = e


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0
        self.typedefs = {}        # typedef name -> Type
        self.enum_consts = {}     # enum tag -> value
        self.struct_layouts = {}  # struct tag -> {field: offset}, size
        self.enum_cursor = 0
        self.struct_cursor = 0
        self.var_types = {}       # variable name -> Type (lightweight symtab)
        self.func_ret_types = {}  # function name -> return Type
    def peek(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        if t.kind != 'eof':
            self.pos += 1
        return t

    def expect(self, val):
        t = self.next()
        if t.val != val:
            raise SyntaxError('expected %r got %r (line %d)'
                              % (val, t.val, t.line))
        return t

    def at(self, val):
        return self.peek().val == val

    def eat(self, val):
        if self.at(val):
            self.next()
            return True
        return False

    # ---- types ----
    def parse_type(self):
        base = 'int'
        ptr = 0
        typ = None
        # skip storage-class / qualifier prefixes
        saw_qualifier = False
        while self.at('static') or self.at('extern') or self.at('const') \
              or self.at('volatile') or self.at('inline') \
              or self.at('unsigned') or self.at('signed') \
              or self.at('long') or self.at('short'):
            saw_qualifier = True
            self.next()
        if self.at('char'):
            self.next()
            base = 'char'
        elif self.at('void'):
            self.next()
            base = 'void'
        elif self.at('int'):
            self.next()
            base = 'int'
        elif self.at('struct'):
            self.next()
            base = 'struct'
            if self.peek().kind == 'id':
                tag = self.next().val
            else:
                tag = None
            typ = Type(base, 0, None, tag)
        elif self.at('enum'):
            self.next()
            base = 'enum'
            if self.peek().kind == 'id':
                tag = self.next().val
            else:
                tag = None
            typ = Type(base, 0, None, tag)
        elif self.peek().kind == 'id' and self.peek().val in self.typedefs:
            # typedef'd type alias
            typ = self.typedefs[self.next().val].clone()
            base = typ.base
        else:
            # `unsigned` / `long` / `short` followed by no type keyword
            # defaults to `int` (C standard: "unsigned" alone == unsigned int).
            if saw_qualifier:
                base = 'int'
                typ = Type(base)
            else:
                return None
        if typ is None:
            typ = Type(base)
        while self.eat('*'):
            ptr += 1
        if ptr:
            typ.ptr += ptr
        return typ
    def parse_declarator(self, typ):
        """Parse identifier, possibly with array suffixes -> (name, Type)."""
        t = self.next()
        if t.kind != 'id':
            raise SyntaxError('expected identifier got %r (line %d)'
                              % (t.val, t.line))
        name = t.val
        while self.at('['):
            self.next()
            if self.at(']'):
                return (name, Type(typ.base, typ.ptr, None, typ.tag, typ.align))
            n = int(self.next().val)
            self.expect(']')
            return (name, Type(typ.base, typ.ptr, n, typ.tag, typ.align))
        return (name, typ)

    # ---- statements ----
    def parse_block(self):
        stmts = []
        self.expect('{')
        while not self.at('}'):
            stmts.append(self.parse_stmt())
        self.expect('}')
        return Block(stmts)

    def parse_stmt(self):
        t = self.peek()
        if t.val == '{':
            return self.parse_block()
        if t.val == 'if':
            self.next()
            self.expect('(')
            c = self.parse_expr()
            self.expect(')')
            th = self.parse_stmt()
            el = None
            if self.at('else'):
                self.next()
                el = self.parse_stmt()
            return If(c, th, el)
        if t.val == 'while':
            self.next()
            self.expect('(')
            c = self.parse_expr()
            self.expect(')')
            b = self.parse_stmt()
            return While(c, b)
        if t.val == 'do':
            self.next()
            b = self.parse_stmt()
            self.expect('while')
            self.expect('(')
            c = self.parse_expr()
            self.expect(')')
            self.expect(';')
            return DoWhile(b, c)
        if t.val == 'for':
            self.next()
            self.expect('(')
            if self.at(';'):
                init = None
            else:
                init = self.parse_expr()
            self.expect(';')
            if self.at(';'):
                cond = None
            else:
                cond = self.parse_expr()
            self.expect(';')
            if self.at(')'):
                post = None
            else:
                post = self.parse_expr()
            self.expect(')')
            b = self.parse_stmt()
            return For(init, cond, post, b)
        if t.val == 'return':
            self.next()
            if self.at(';'):
                e = None
            else:
                e = self.parse_expr()
            self.expect(';')
            return Ret(e)
        if t.val == 'break':
            self.next()
            self.expect(';')
            return Break()
        if t.val == 'continue':
            self.next()
            self.expect(';')
            return Cont()
        if t.val == ';':
            self.next()
            return Empty()
        # declaration or expression
        typ = self.parse_type()
        if typ is not None:
            name, dt = self.parse_declarator(typ)
            init = None
            if self.eat('='):
                init = self.parse_expr()
            self.expect(';')
            return VarDecl(name, dt, init)
        e = self.parse_expr()
        self.expect(';')
        return ExprStmt(e)

    # ---- expressions (precedence climbing) ----
    def parse_expr(self):
        # assignment (right assoc)
        l = self.parse_cond()
        if self.peek().val in ('=', '+=', '-=', '*=', '/=', '%=',
                               '&=', '|=', '^='):
            op = self.next().val
            r = self.parse_expr()
            return Assign(op, l, r)
        return l

    def parse_cond(self):
        c = self.parse_or()
        if self.at('?'):
            self.next()
            t = self.parse_expr()
            self.expect(':')
            e = self.parse_cond()
            return Cond(c, t, e)
        return c

    def parse_or(self):
        l = self.parse_and()
        while self.at('||') or self.at('|'):
            op = self.next().val
            r = self.parse_and()
            l = Binary(op, l, r)
        return l

    def parse_and(self):
        l = self.parse_bitor()
        while self.at('&&') or self.at('&'):
            op = self.next().val
            r = self.parse_bitor()
            l = Binary(op, l, r)
        return l

    def parse_bitor(self):
        l = self.parse_bitxor()
        while self.at('|'):
            op = self.next().val
            r = self.parse_bitxor()
            l = Binary(op, l, r)
        return l

    def parse_bitxor(self):
        l = self.parse_bitand()
        while self.at('^'):
            self.next()
            r = self.parse_bitand()
            l = Binary('^', l, r)
        return l

    def parse_bitand(self):
        l = self.parse_eq()
        while self.at('&'):
            self.next()
            r = self.parse_eq()
            l = Binary('&', l, r)
        return l

    def parse_eq(self):
        l = self.parse_rel()
        while self.at('==') or self.at('!='):
            op = self.next().val
            r = self.parse_rel()
            l = Binary(op, l, r)
        return l

    def parse_rel(self):
        l = self.parse_shift()
        while self.at('<') or self.at('>') or self.at('<=') \
              or self.at('>='):
            op = self.next().val
            r = self.parse_shift()
            l = Binary(op, l, r)
        return l

    def parse_shift(self):
        l = self.parse_add()
        while self.at('<<') or self.at('>>'):
            op = self.next().val
            r = self.parse_add()
            l = Binary(op, l, r)
        return l

    def parse_add(self):
        l = self.parse_mul()
        while self.at('+') or self.at('-'):
            op = self.next().val
            r = self.parse_mul()
            l = Binary(op, l, r)
        return l

    def parse_mul(self):
        l = self.parse_unary()
        while self.at('*') or self.at('/') or self.at('%'):
            op = self.next().val
            r = self.parse_unary()
            l = Binary(op, l, r)
        return l

    def parse_unary(self):
        t = self.peek()
        if t.val in ('-', '!', '~', '*', '&', '++', '--'):
            self.next()
            e = self.parse_unary()
            return Unary(t.val, e)
        if t.val == '(':
            # either cast or paren
            save = self.pos
            self.next()
            if self.parse_type() is not None and self.at(')'):
                self.next()
                e = self.parse_unary()
                return Unary('cast', e)
            self.pos = save
            self.next()
            e = self.parse_expr()
            self.expect(')')
            return e
        if t.kind == 'num':
            self.next()
            v = int(t.val, 0)
            return Num(v)
        if t.kind == 'str':
            self.next()
            return Str(t.val)
        if t.kind == 'id':
            self.next()
            node = Name(t.val)
            cur_type = self.var_types.get(t.val)
            # postfix chain: calls / indexing / member access (. ->)
            while True:
                if self.at('(') and isinstance(node, Name):
                    # function call (only on plain names)
                    self.next()
                    args = []
                    if not self.at(')'):
                        args.append(self.parse_expr())
                        while self.eat(','):
                            args.append(self.parse_expr())
                    self.expect(')')
                    node = Call(node.name, args)
                    continue
                if self.at('['):
                    self.next()
                    idx = self.parse_expr()
                    self.expect(']')
                    # element step: if base is an array of structs, each
                    # element occupies struct_layouts[tag].size words.
                    step = 1
                    if cur_type is not None and cur_type.arr is not None:
                        elem = Type(cur_type.base, cur_type.ptr, None,
                                    cur_type.tag, cur_type.align)
                        if elem.base == 'struct' and elem.tag \
                           and elem.tag in self.struct_layouts:
                            _, esz, _ = self.struct_layouts[elem.tag]
                            step = esz
                    node = Index(node, idx, step)
                    # array of structs -> element type (drop array dim)
                    if cur_type is not None and cur_type.arr is not None:
                        cur_type = Type(cur_type.base, cur_type.ptr, None,
                                        cur_type.tag, cur_type.align)
                    continue
                if self.at('.') or self.at('->'):
                    arrow = self.next().val == '->'
                    if self.peek().kind != 'id':
                        raise SyntaxError('bad member line %d'
                                          % self.peek().line)
                    fname = self.next().val
                    if arrow:
                        # p->f : deref pointer then member
                        stype = cur_type
                        if stype and stype.ptr > 0:
                            stype = stype.clone()
                            stype.ptr -= 1
                        node = Unary('*', node)
                    else:
                        stype = cur_type
                    off = 0
                    if stype is not None and stype.base == 'struct' \
                       and stype.tag \
                       and stype.tag in self.struct_layouts:
                        layout, size, ftypes = self.struct_layouts[stype.tag]
                        if fname in layout:
                            off = layout[fname]
                            cur_type = ftypes.get(fname)
                        else:
                            cur_type = None
                    else:
                        cur_type = None
                    node = Member(node, fname, off)
                    continue
                if self.at('++') and isinstance(node, Name):
                    self.next()
                    return PostInc(node.name)
                if self.at('--') and isinstance(node, Name):
                    self.next()
                    return PostDec(node.name)
                break
            if self.at('(') and not isinstance(node, Name):
                raise SyntaxError('bad call target line %d'
                                  % self.peek().line)
            # enum constant
            if isinstance(node, Name) and node.name in self.enum_consts:
                return Num(self.enum_consts[node.name])
            return node
        raise SyntaxError('unexpected token %r line %d' % (t.val, t.line))

    # ---- top level ----
    def _parse_struct_body(self, tag):
        """Parse `{ type field; ... }` returning (layout, size, field_types).
        layout: field -> word offset; field_types: field -> Type."""
        self.expect('{')
        layout = {}
        ftypes = {}
        off = 0
        size = 0
        while not self.at('}'):
            ftyp = self.parse_type()
            if ftyp is None:
                raise SyntaxError('struct field type at line %d'
                                  % self.peek().line)
            fname, fdt = self.parse_declarator(ftyp)
            if fdt.arr:
                fsize = fdt.arr
            elif fdt.base == 'struct' and fdt.tag \
                 and fdt.tag in self.struct_layouts:
                # nested struct field: occupy its declared size
                _, fsz, _ = self.struct_layouts[fdt.tag]
                fsize = fsz
            else:
                fsize = 1
            layout[fname] = off
            ftypes[fname] = fdt
            off += fsize
            size = off
            self.expect(';')
        self.expect('}')
        if tag:
            self.struct_layouts[tag] = (layout, size, ftypes)
        return layout, size, ftypes

    def _parse_enum_def(self):
        """Parse `enum [tag] { A[=expr], B, ... };` -> values dict."""
        values = {}
        cursor = self.enum_cursor
        start = cursor
        self.next()             # enum
        if self.peek().kind == 'id':
            self.next()         # tag
        if self.at('{'):
            self.next()
            while not self.at('}'):
                if self.peek().kind != 'id':
                    raise SyntaxError('bad enum member line %d'
                                      % self.peek().line)
                name = self.next().val
                if self.eat('='):
                    # constant expression: evaluate simple value
                    v = self._const_eval_expr()
                    cursor = v
                values[name] = cursor
                cursor += 1
                if not self.eat(','):
                    break
            self.expect('}')
        self.enum_cursor = cursor
        return values

    def _const_eval_expr(self):
        """Evaluate a constant integer expression (enum initializer)."""
        toks = []
        depth = 0
        while True:
            t = self.peek()
            if t.val in (',', '}') and depth == 0:
                break
            if t.val == '(':
                depth += 1
            elif t.val == ')':
                depth -= 1
            self.next()
            toks.append(t)
        # build a mini expression evaluator over tokens
        def eval_toks(tl, i):
            # very small recursive descent: expr -> term {+|- term}
            # term -> atom {*|/|%|<<|>> atom} ; atom -> num | id | ( expr )
            def atom(idx):
                t = tl[idx]
                if t.kind == 'num':
                    return int(t.val, 0), idx + 1
                if t.kind == 'id':
                    if t.val in self.enum_consts:
                        v = self.enum_consts[t.val]
                    elif t.val in self.typedefs:
                        v = 0
                    else:
                        v = 0
                    return v, idx + 1
                if t.val == '(':
                    v, idx = eval_toks(tl, idx + 1)
                    if idx < len(tl) and tl[idx].val == ')':
                        idx += 1
                    return v, idx
                if t.val == '-':
                    v, idx = atom(idx + 1)
                    return -v, idx
                raise SyntaxError('bad const expr %r' % t.val)
            def term(idx):
                v, idx = atom(idx)
                while idx < len(tl) and tl[idx].val in ('*', '/', '%'):
                    op = tl[idx].val
                    rv, idx = atom(idx + 1)
                    if op == '*':
                        v = v * rv
                    elif op == '/':
                        v = v // rv if rv else 0
                    elif op == '%':
                        v = v % rv if rv else 0
                return v, idx
            v, idx = term(i)
            while idx < len(tl) and tl[idx].val in ('+', '-', '<<', '>>', '&',
                                                    '|', '^'):
                op = tl[idx].val
                rv, idx = term(idx + 1)
                if op == '+':
                    v = v + rv
                elif op == '-':
                    v = v - rv
                elif op == '<<':
                    v = v << rv
                elif op == '>>':
                    v = v >> rv
                elif op == '&':
                    v = v & rv
                elif op == '|':
                    v = v | rv
                elif op == '^':
                    v = v ^ rv
            return v, idx
        v, idx = eval_toks(toks, 0)
        return v

    def parse(self):
        decls = []
        while self.peek().kind != 'eof':
            # A lone ';' at file scope is legal C (empty declaration) and is
            # what annotation macros leave behind -- e.g. EXPORT_SYMBOL(foo)
            # expands to nothing, leaving "foo() {...} ;".  Kernel sources are
            # full of these, so skip them instead of failing.
            if self.at(';'):
                self.next()
                continue
            if self.at('typedef'):
                self.next()
                t0 = self.peek().val
                if self.at('struct'):
                    self.next()
                    tag = None
                    if self.peek().kind == 'id':
                        tag = self.next().val
                    if self.at('{'):
                        # anonymous struct: give it a synthetic tag so the
                        # layout is registered and member offsets resolve.
                        if tag is None:
                            tag = '__anon_%d' % self.struct_cursor
                            self.struct_cursor += 1
                        layout, size, ftypes = self._parse_struct_body(tag)
                    else:
                        layout, size, ftypes = self.struct_layouts.get(
                            tag, ({}, 1, {}))
                    # declarator (the typedef name)
                    if self.peek().kind != 'id':
                        raise SyntaxError('bad typedef line %d'
                                          % self.peek().line)
                    tname = self.next().val
                    self.expect(';')
                    self.typedefs[tname] = Type('struct', 0, None, tag, size)
                    continue
                if self.at('enum'):
                    self.next()
                    if self.peek().kind == 'id':
                        tag = self.next().val
                    else:
                        tag = None
                    if self.at('{'):
                        # inline enum body (we already consumed 'enum')
                        self.next()
                        while not self.at('}'):
                            if self.peek().kind != 'id':
                                raise SyntaxError(
                                    'bad typedef enum member line %d'
                                    % self.peek().line)
                            ename = self.next().val
                            if self.eat('='):
                                v = self._const_eval_expr()
                                self.enum_cursor = v
                            else:
                                v = self.enum_cursor
                            self.enum_consts[ename] = v
                            self.enum_cursor = v + 1
                            decls.append(Glob('__enum_%s' % ename,
                                              Type('int'), Num(v)))
                            if not self.eat(','):
                                break
                        self.expect('}')
                    # typedef name follows
                    if self.peek().kind != 'id':
                        raise SyntaxError('bad typedef enum')
                    tname = self.next().val
                    self.expect(';')
                    self.typedefs[tname] = Type('int')
                    continue
                # typedef <base-type> <name>;
                typ = self.parse_type()
                if typ is None:
                    raise SyntaxError('bad typedef type line %d'
                                      % self.peek().line)
                name, dt = self.parse_declarator(typ)
                self.expect(';')
                self.typedefs[name] = dt
                continue
            if self.at('enum'):
                vals = self._parse_enum_def()
                self.enum_consts.update(vals)
                for k, v in vals.items():
                    decls.append(Glob('__enum_%s' % k, Type('int'), Num(v)))
                # optional trailing ';' or declarator (rare); handle ';'
                self.eat(';')
                continue
            if self.at('struct'):
                self.next()
                tag = None
                if self.peek().kind == 'id':
                    tag = self.next().val
                if self.at('{'):
                    self._parse_struct_body(tag)
                    self.expect(';')   # standalone struct definition
                    continue
                # struct tag followed by declarator (global var)
                if tag is None:
                    raise SyntaxError('struct without tag/body line %d'
                                      % self.peek().line)
                typ = Type('struct', 0, None, tag)
                name, dt = self.parse_declarator(typ)
                init = None
                if self.eat('='):
                    init = self.parse_expr()
                self.expect(';')
                self.var_types[name] = dt
                decls.append(Glob(name, dt, init))
                continue
            typ = self.parse_type()
            if typ is None:
                raise SyntaxError('expected type, got %r line %d'
                                  % (self.peek().val, self.peek().line))
            name, dt = self.parse_declarator(typ)
            if self.at('('):
                # function
                self.next()
                params = []
                plist = []
                # `f(void)` means NO parameters in C (not one void param).
                if self.at('void') and self.toks[self.pos + 1].val == ')':
                    self.next()
                if not self.at(')'):
                    while True:
                        pt = self.parse_type()
                        if pt is None:
                            raise SyntaxError('bad param')
                        pname, pdt = self.parse_declarator(pt)
                        # strip array to pointer
                        plist.append(pname)
                        params.append(pdt)
                        if not self.eat(','):
                            break
                self.expect(')')
                if self.at(';'):
                    self.next()
                    decls.append(FnDecl(name, dt, None, params))
                else:
                    body = self.parse_block()
                    decls.append(Func(name, dt, params, body, plist))
            else:
                init = None
                if self.eat('='):
                    init = self.parse_expr()
                self.expect(';')
                self.var_types[name] = dt
                decls.append(Glob(name, dt, init))
        return decls


class PostInc(Node):
    def __init__(self, name):
        self.name = name


class PostDec(Node):
    def __init__(self, name):
        self.name = name


# ------------------------------------------------------------------
# Code generator
# ------------------------------------------------------------------
# Compile the C-ish AST (Parser above) to SUBLEQ words via osma.Asm.
#
# Semantics (QEMU OISC, translate.c):
#   subleq A,B,C : mem[B] -= mem[A];  if mem[B] (signed) <= 0 -> PC = C
#                  (C==0 or sign set -> halt)  else PC += 4
# Cells are 4 words [A B C pad]; PC is a word address, +4 per cell.
#
# ABI (all are fixed slots):
#   ACC  - primary accumulator (expression results)
#   TMP  - secondary scratch
#   NB   - negate scratch
#   A0..A3 - function argument slots
#   R0   - return value slot
#   RA   - return address slot
#   SP   - stack pointer (grows DOWN; used to save/restore RA on calls)
#   __stack - global word array used as the call stack
#
# Indirect addressing (arrays/pointers): SUBLEQ A/B/C fields are IMMEDIATE
# addresses, so a runtime target must go through a self-modifying
# trampoline cell (QEMU uses a RUNTIME operand model - A/B/C are re-read
# from RAM every execution, so self-modification works):
#
#   tpl_cell:  [ tplA, tplB, tplC ]      (each is a slot address)
#   at runtime set:  mem[tplA]=src_addr ; mem[tplB]=dst_addr ;
#                    mem[tplC]=resume_addr ; jump tpl_cell
#   effect: mem[dst_addr] -= mem[src_addr] ; if <=0 -> PC=mem[tplC]
#   (plus a jmp trampoline [Z,Z,tplC] for indirect jumps: return)
#
# Every trampoline use re-writes all three fields first, so nested calls
# are safe (each use is self-contained).
# ------------------------------------------------------------------

STACK_WORDS = 64         # call/expr stack (words)


class CodeGen:
    def __init__(self, asm, struct_layouts=None, var_types=None):
        self.a = asm
        # register slots
        self.acc = asm.slot('_acc')
        self.tmp = asm.slot('_tmp')
        self.nb = asm.slot('_nb')
        self.r0 = asm.slot('_r0')
        self.ra = asm.slot('_ra')
        self.sp = asm.slot('_sp')
        self.arg = [asm.slot('_a%d' % i) for i in range(4)]
        # trampoline fields
        self.tplA = asm.slot('_tplA')
        self.tplB = asm.slot('_tplB')
        self.tplC = asm.slot('_tplC')
        # data
        self.stack = asm.glob('__stack', STACK_WORDS)
        # trampoline cells (labels; cells emitted at build() tail).
        # SELF-MODIFYING: at runtime we write the target addresses into
        # the cell's own A/B/C fields (their addresses are compile-time
        # constants via addr_of/add_off), then jump there.  Each use
        # re-writes all fields, so nested calls are safe.
        self.tpl_label = L('_tpl_ind')        # ind-subleq trampoline
        self.tpl_next = L('_tpl_ind_next')    # convergence cell (C=resume)
        self.tpl_jmp = L('_tpl_jmp')          # indirect-jump trampoline
        self.tpl_jmp_next = L('_tpl_jmp_next')# convergence cell for jmp
        # scratch for write_fixed_const
        self.tmp2 = asm.slot('_tmp2')
        # dedicated base-address holder for scaled array indexing.
        # CANNOT be tmp2: add()/sub() primitives use tmp2 as their internal
        # accumulator (cell(tmp2,tmp2) zeroes it first), so a base address
        # parked in tmp2 is destroyed by the very first add/sub in the
        # step>1 scaling loop.  This slot is never touched by any primitive.
        self.baddr = asm.slot('_baddr')
        # dedicated pointer slot for indirect ops (avoids st()'s internal
        # scratch `tmp` clobbering the ptr_reg we're storing)
        self.ptr = asm.slot('_ptr')
        # dedicated index temp for array lvalue/addr computations.  CANNOT be
        # r0: e_Assign parks the RHS value in r0 before _store_lvalue, and an
        # Index target would otherwise clobber the value with the index.
        self.idx = asm.slot('_idx')
        # dedicated push temp.  _push internally does st(temp, slot) before
        # the indirect store; this MUST NOT be r0, because e_Assign parks the
        # RHS in r0 for the whole _store_lvalue call, and _push is invoked
        # while computing array-index lvalue (base/idx get pushed).
        self.vtmp = asm.slot('_vtmp')
        # per-function state
        self.funcs = {}       # name -> {label, locals:{name->slot}}
        self.globals = {}     # name -> {sym, array(bool)}
        self.var_layout = {}  # variable name -> struct field layout dict
        self.struct_layouts = dict(struct_layouts or {})  # struct tag -> (layout,size,ftypes)
        self.var_types = dict(var_types or {})    # variable -> Type
        self.strs = []        # (bytes, globSym)
        self.cur = None       # current function dict
        self.break_stack = []
        self.cont_stack = []
        self.entry = None
        self.label_n = 0
        self.entry_label = L('_entry')

    def new_label(self, hint='l'):
        self.label_n += 1
        return L('%s_%d' % (hint, self.label_n))

    # ---------------- tiny helpers ----------------
    def _z(self):
        return self.a.const(0)

    def _addr(self, x):
        if isinstance(x, Sym):
            return x
        if isinstance(x, int):
            return self.a.const(x & 0xffffffff)
        raise ValueError('bad addr %r' % x)

    def _branch(self, src, dst, target):
        """subleq src,dst,target : dst -= src ; if dst<=0 jump target."""
        self.a.cell(self._addr(src), self._addr(dst), self._addr(target))

    # ============ SUBLEQ primitives ============
    # Every primitive leaves its result in `dst` and ends with an
    # unconditional normalized jump `subleq Z,Z,cont` (Z=0 word) so
    # internal sign-branching never leaks.

    def seti(self, dst, value):
        """dst = value (int immediate)."""
        z = self._z()
        negv = self.a.const(-value & 0xffffffff)
        l1, l2, l3 = self.new_label('s'), self.new_label('s'), self.new_label('s')
        self.a.cell(self._addr(dst), self._addr(dst), l1)  # dst = 0
        self.a.label(l1.name)
        self._branch(negv, dst, l2)    # dst = 0 - (-v) = v
        self.a.label(l2.name)
        self._branch(z, z, l3)
        self.a.label(l3.name)

    def set_addr(self, dst, sym):
        """dst = address-of(sym)  (or addr_off / any addr const)."""
        z = self._z()
        negaddr = self.a.addr_of(sym, negate=True)
        l1, l2, l3 = self.new_label('sa'), self.new_label('sa'), self.new_label('sa')
        self.a.cell(self._addr(dst), self._addr(dst), l1)  # dst = 0
        self.a.label(l1.name)
        self._branch(negaddr, dst, l2)  # dst = 0 - (-addr) = addr
        self.a.label(l2.name)
        self._branch(z, z, l3)
        self.a.label(l3.name)

    def neg(self, dst, src):
        """dst = -src.
        Safe even when dst IS src (e_Unary '-' calls neg(acc, acc)): a naive
        cell(dst,dst); branch(src,dst) would self-zero dst (subleq X,X).
        Copy src to tmp first, then dst = -tmp."""
        z = self._z()
        if dst.name == src.name:
            # copy src into tmp first: st(tmp, src) is safe because st()
            # re-zeroes dst(tmp) at the end and its internal ld(acc,src)
            # merely uses tmp as scratch (overwritten later).
            self.st(self.tmp, src)               # tmp = src
            l1 = self.new_label('n')
            l2 = self.new_label('n')
            l3 = self.new_label('n')
            self.a.cell(self._addr(dst), self._addr(dst), l1)  # dst = 0
            self.a.label(l1.name)
            self._branch(self.tmp, dst, l2)      # dst = 0 - tmp = -src
            self.a.label(l2.name)
            self._branch(z, z, l3)
            self.a.label(l3.name)
        else:
            l1, l2, l3 = self.new_label('n'), self.new_label('n'), self.new_label('n')
            self.a.cell(self._addr(dst), self._addr(dst), l1)  # dst = 0
            self.a.label(l1.name)
            self._branch(self._addr(src), dst, l2)   # dst = 0 - src = -src
            self.a.label(l2.name)
            self._branch(z, z, l3)
            self.a.label(l3.name)

    def ld(self, dst, src):
        """dst = mem[src]  (src is a fixed slot/const address)."""
        z = self._z()
        l1 = self.new_label('ld')
        l2 = self.new_label('ld')
        l3 = self.new_label('ld')
        l4 = self.new_label('ld')
        l5 = self.new_label('ld')
        self.a.cell(self._addr(self.tmp), self._addr(self.tmp), l1)  # tmp=0
        self.a.label(l1.name)
        self._branch(self._addr(src), self.tmp, l2)   # tmp = -src
        self.a.label(l2.name)
        self.a.cell(self._addr(dst), self._addr(dst), l3)  # dst=0
        self.a.label(l3.name)
        self._branch(self.tmp, dst, l4)              # dst = 0 - tmp = src
        self.a.label(l4.name)
        self._branch(z, z, l5)
        self.a.label(l5.name)

    def st(self, dst, src):
        """mem[dst] = mem[src]  (both fixed slot/const addresses).
        Uses NB for negation so dst==src is safe.
        IMPORTANT: first ZEROES dst (subleq dst,dst) because dst may be a
        non-zero trampoline cell field; the naive 'dst = 0 - nb' would
        otherwise yield old_value + src."""
        z = self._z()
        # dst = 0  (subleq dst,dst: mem[dst] -= mem[dst])
        l0a, l0b = self.new_label('st'), self.new_label('st')
        self.a.cell(self._addr(dst), self._addr(dst), l0a)
        self.a.label(l0a.name)
        self._branch(z, z, l0b)
        self.a.label(l0b.name)
        self.ld(self.acc, src)         # acc = src
        # nb = -acc  (nb must be cleared first: nb = nb - acc otherwise)
        l1, l2 = self.new_label('st'), self.new_label('st')
        self.a.cell(self._addr(self.nb), self._addr(self.nb), l1)  # nb=0
        self.a.label(l1.name)
        self._branch(self.acc, self.nb, l2)   # nb = -src
        self.a.label(l2.name)
        # dst = 0 - nb = src
        # NOTE: dst was already zeroed above; but if dst==some shared slot
        # clobbered by ld(acc=src), re-zero it for safety:
        l3, l4 = self.new_label('st'), self.new_label('st')
        self.a.cell(self._addr(dst), self._addr(dst), l3)
        self.a.label(l3.name)
        self._branch(self.nb, dst, l4)
        self.a.label(l4.name)

    def add(self, dst, a, b):
        """dst = a + b.
        Uses self.tmp2 as the internal accumulator (NOT self.tmp) because
        callers (e_Binary) commonly pass b == self.tmp (the right operand is
        popped into _tmp).  If we accumulated into tmp, the step
        'branch(b, tmp)' with b == tmp would become subleq(tmp,tmp) which
        SELF-ZEROES the accumulated -a and the result is always 0."""
        z = self._z()
        l1 = self.new_label('a')
        l2 = self.new_label('a')
        l3 = self.new_label('a')
        l4 = self.new_label('a')
        l5 = self.new_label('a')
        l6 = self.new_label('a')
        self.a.cell(self._addr(self.tmp2), self._addr(self.tmp2), l1)  # tmp2=0
        self.a.label(l1.name)
        self._branch(self._addr(a), self.tmp2, l2)   # tmp2 = -a
        self.a.label(l2.name)
        self._branch(self._addr(b), self.tmp2, l3)   # tmp2 = -a-b
        self.a.label(l3.name)
        self.a.cell(self._addr(dst), self._addr(dst), l4)  # dst=0
        self.a.label(l4.name)
        self._branch(self.tmp2, dst, l5)             # dst = a+b
        self.a.label(l5.name)
        self._branch(z, z, l6)
        self.a.label(l6.name)

    def sub(self, dst, a, b):
        """dst = a - b.
        Uses NB (=-b) and TMP2 (=b-a accumulator).  NEVER uses tmp as the
        accumulator: when dst == tmp (as in _divmod's 'sub(tmp, rem, d)')
        a `cell(tmp,tmp); branch(tmp,dst=tmp)` self-zeroes the result."""
        z = self._z()
        # nb = -b
        l1, l2 = self.new_label('su'), self.new_label('su')
        self.a.cell(self._addr(self.nb), self._addr(self.nb), l1)  # nb=0
        self.a.label(l1.name)
        self._branch(self._addr(b), self.nb, l2)    # nb = -b
        self.a.label(l2.name)
        # tmp2 = -a
        l3, l4 = self.new_label('su'), self.new_label('su')
        self.a.cell(self._addr(self.tmp2), self._addr(self.tmp2), l3)  # tmp2=0
        self.a.label(l3.name)
        self._branch(self._addr(a), self.tmp2, l4)  # tmp2 = -a
        self.a.label(l4.name)
        # tmp2 = -a - nb = -a + b = b - a (negative of a-b)
        l5, l6 = self.new_label('su'), self.new_label('su')
        self._branch(self.nb, self.tmp2, l5)        # tmp2 -= nb
        self.a.label(l5.name)
        # dst = 0 ; then dst -= tmp2 = a - b
        self.a.cell(self._addr(dst), self._addr(dst), l6)  # dst = 0
        self.a.label(l6.name)
        l7 = self.new_label('su')
        self._branch(self.tmp2, dst, l7)            # dst = a-b
        self.a.label(l7.name)
        l8 = self.new_label('su')
        self._branch(z, z, l8)
        self.a.label(l8.name)

    # ---------------- control flow ----------------
    def jmp(self, target):
        self._branch(self._z(), self._z(), target)

    def branch_le0(self, slot, target):
        """branch to target if mem[slot] (signed) <= 0, WITHOUT writing."""
        self._branch(self._z(), slot, target)

    def branch_gt0(self, slot, target):
        """branch to target if mem[slot] (signed) > 0: skip the <=0."""
        skip = self.new_label('gt')
        self.branch_le0(slot, skip)
        self.jmp(target)
        self.a.label(skip.name)

    # ---------------- indirect trampoline --------------
    # SUBLEQ cell fields A/B/C are IMMEDIATE addresses read from the cell
    # words.  Runtime (indirect) operands use SELF-MODIFYING CODE:
    #
    #   tpl_cell  : [ A, B, C1 ]  (A/B patched to runtime addrs, C1 fixed
    #                             to addr(tpl_next))
    #   tpl_next  : [ Z, Z, C2 ]  (C2 patched to resume; convergence)
    #   tpl_jmp   : [ Z, Z, C3 ]  (C3 patched to runtime target; direct jmp)
    #
    # Each use patches the needed cell words via a NORMAL store to the
    # cell-word address (compile-time constant via addr_off(label, 0/4/8)).
    # QEMU re-reads A/B/C on every execution, so this works.  Both branch
    # paths (res<=0 jumps C1, res>0 falls into tpl_next) converge at C2.

    def _load_indirect(self, ptr_reg):
        """acc = *ptr_reg  (ptr value in ptr_reg slot).
        Uses tmp2 as internal zero-base (NOT tmp) so callers that pass
        tmp as ptr_reg are safe."""
        z = self._z()
        self.seti(self.tmp2, 0)                    # tmp2 = 0
        # cell1.A = ptr (runtime addr);  cell1.B = addr(tmp2) (fixed)
        self.st(self.a.field_addr(self.tpl_label, 0), ptr_reg)
        self.st(self.a.field_addr(self.tpl_label, 1), self.a.addr_of(self.tmp2))
        cont = self.new_label('il')
        # cell1.C + cell2.C both = cont (resume)
        self.st(self.a.field_addr(self.tpl_label, 2), self.a.addr_of(cont))
        self.st(self.a.field_addr(self.tpl_next, 2), self.a.addr_of(cont))
        self.jmp(self.tpl_label)
        self.a.label(cont.name)                    # tmp2 = 0 - *ptr = -val
        self.neg(self.acc, self.tmp2)              # acc = *ptr

    def _indirect_store(self, ptr_reg, val_reg):
        """*ptr_reg = val_reg.
        Stores -val in self.tmp2 (NOT self.nb): st() internally zeroes nb
        (cell(nb,nb)) in its own sequence, so a -val computed into nb via
        neg(nb, val) would be destroyed before the trampoline executes.
        tmp2 is never touched by st()/neg internals."""
        # 1) zero target: A=ptr, B=ptr => mem[ptr] -= mem[ptr] = 0
        cont1 = self.new_label('is')
        self.st(self.a.field_addr(self.tpl_label, 0), ptr_reg)
        self.st(self.a.field_addr(self.tpl_label, 1), ptr_reg)
        self.st(self.a.field_addr(self.tpl_label, 2), self.a.addr_of(cont1))
        self.st(self.a.field_addr(self.tpl_next, 2), self.a.addr_of(cont1))
        self.jmp(self.tpl_label)
        self.a.label(cont1.name)                     # mem[ptr] = 0
        # 2) add -val: A=addr(tmp2), B=ptr ; tmp2 = -val
        self.neg(self.tmp2, val_reg)
        cont2 = self.new_label('is')
        self.st(self.a.field_addr(self.tpl_label, 0), self.a.addr_of(self.tmp2))
        self.st(self.a.field_addr(self.tpl_label, 1), ptr_reg)
        self.st(self.a.field_addr(self.tpl_label, 2), self.a.addr_of(cont2))
        self.st(self.a.field_addr(self.tpl_next, 2), self.a.addr_of(cont2))
        self.jmp(self.tpl_label)
        self.a.label(cont2.name)                     # mem[ptr] = -(-val) = val

    def _indirect_jump(self, addr_reg):
        """PC = mem[addr_reg]  (runtime jump target)."""
        # tpl_jmp: [Z, Z, target] => res=0<=0 -> PC=target (no convergence
        # needed: unconditional).
        self.st(self.a.field_addr(self.tpl_jmp, 2), addr_reg)
        self.jmp(self.tpl_jmp)

    # ---------------- expression compilation ----------------
    def expr(self, e):
        """Compile expression; result lands in self.acc."""
        if e is None:
            return
        t = type(e).__name__
        m = getattr(self, 'e_' + t, None)
        if m is None:
            raise NotImplementedError('expr: ' + t)
        m(e)

    def e_Num(self, e):
        self.seti(self.acc, e.v)

    def e_Str(self, e):
        b = e.data if isinstance(e.data, bytes) else e.data.encode('utf8')
        # find or create
        g = None
        for sb, sg in self.strs:
            if sb == b:
                g = sg
                break
        if g is None:
            g = self.a.glob('__str_%d' % len(self.strs), len(b) + 1)
            self.strs.append((b, g))
        # acc = addr_of(g)
        self.set_addr(self.acc, g)

    def e_Name(self, e):
        name = e.name
        if name in self.funcs:
            # function pointer: address of function label
            self.set_addr(self.acc, self.funcs[name]['label'])
            return
        if name in self.globals:
            g = self.globals[name]
            if g['array']:
                self.set_addr(self.acc, g['sym'])   # array -> base addr
            else:
                self.ld(self.acc, g['sym'])
            return
        if self.cur is not None and name in self.cur['locals']:
            self.ld(self.acc, self.cur['locals'][name])
            return
        raise KeyError('unknown var %s' % name)

    # ---- binary ops ----
    def _push(self, slot):
        """SP -= 1; mem[SP] = mem[slot]  (runtime SP address).
        Uses self.ptr (dedicated pointer slot), NOT self.tmp: the indirect
        store patches a trampoline cell via st(field, ptr_reg), and st()
        internally reads src through ld(acc, src) which CLEARS tmp
        (cell(tmp,tmp)).  If ptr_reg were tmp, st(field, tmp) would read 0
        and the trampoline would operate on mem[0] instead of mem[SP].

        CRITICAL: the value is first moved to self.vtmp (a slot never
        touched by store/neg/trampoline internals AND distinct from r0).
        _indirect_store internally runs st(field, ...) which clobbers
        acc/tmp/nb; and this temp must not be r0 because callers (e_Assign)
        may be parking a live value in r0 while this push runs."""
        self.st(self.vtmp, slot)       # vtmp = val (preserve)
        self.st(self.ptr, self.sp)         # ptr = SP (addr copy)
        self._indirect_store(self.ptr, self.vtmp)  # mem[SP] = mem[vtmp]
        self.sub(self.sp, self.sp, self.a.const(1))  # SP -= 1

    def _pop(self, dst):
        """dst = mem[SP+1]; SP += 1.
        Push writes mem[SP]=val then SP-=1, so the element lives at SP+1.
        Same ptr-slot requirement as _push.

        CRITICAL: when dst is acc, SKIP the trailing st(dst, acc) — the
        value is already in acc, and st(acc, acc) would ZERO acc
        (cell(acc,acc) first), destroying the popped value."""
        self.sub(self.sp, self.sp, self.a.const(-1))  # SP += 1
        self.st(self.ptr, self.sp)             # ptr = SP+1 address
        self._load_indirect(self.ptr)          # acc = mem[SP+1]
        if dst.name != self.acc.name:
            self.st(dst, self.acc)             # dst = acc (unless dst==acc)

    def e_Binary(self, e):
        op = e.op
        l, r = e.l, e.r
        if op == '&&':
            end = self.new_label('and')
            self.expr(l)
            self.branch_le0(self.acc, end)     # if !l -> 0
            self.expr(r)
            self.branch_le0(self.acc, end)     # if !r -> 0
            self.seti(self.acc, 1)
            self.a.label(end.name)
            return
        if op == '||':
            end = self.new_label('or')
            lz = self.new_label('orlz')
            self.expr(l)
            self.branch_gt0(self.acc, lz)      # if l>0 -> true
            self.expr(r)
            self.branch_le0(self.acc, end)     # if !r -> 0
            self.seti(self.acc, 1)
            self.jmp(end)
            self.a.label(lz.name)
            self.seti(self.acc, 1)
            self.a.label(end.name)
            return
        if op in ('==', '!=', '<', '<=', '>', '>='):
            self._cmp(op, l, r)
            return
        # arithmetic: eval l, push; eval r, push; pop r->r0, pop l->acc
        # r is kept in _r0 (NOT _tmp): the second _pop (and every
        # push/pop/ld/st/sub) internally clobbers _tmp/_nb/_tmp2/acc,
        # so a right operand parked in _tmp would be destroyed before
        # _arith runs.  r0 is only ever used as _push's temp, and no
        # pop sequence runs between writing r0 here and reading it.
        self.expr(l)
        self._push(self.acc)
        self.expr(r)
        self._push(self.acc)
        self._pop(self.r0)    # r0 = r
        self._pop(self.acc)   # acc = l
        self._arith(op, self.acc, self.r0)

    def _arith(self, op, la, ra):
        if op == '+':
            self.add(self.acc, la, ra)
        elif op == '-':
            self.sub(self.acc, la, ra)
        elif op == '*':
            self._mul(la, ra)
        elif op == '/':
            self._div(la, ra)
        elif op == '%':
            self._mod(la, ra)
        elif op == '<<':
            self._shl(la, ra)
        elif op == '>>':
            self._shr(la, ra)
        elif op == '&':
            self._bitand(la, ra)
        elif op == '|':
            self._bitor(la, ra)
        elif op == '^':
            self._bitxor(la, ra)
        else:
            raise NotImplementedError('arith %s' % op)

    def _mul(self, la, ra):
        """acc = la * ra (SIGNED: abs-product with sign correction).
        SUBLEQ branching is signed (branch_le0 == signed<=0), so plain
        unsigned accumulation breaks when either operand is negative."""
        a = self.new_slot('mul_a'); b = self.new_slot('mul_b')
        an = self.new_slot('mul_an'); bn = self.new_slot('mul_bn')
        sg = self.new_slot('mul_sg')
        self.st(a, la); self.st(b, ra)
        self._sgn(an, a)                   # an = a<0
        self._sgn(bn, b)                   # bn = b<0
        self._abs(a, an)                   # a = |a|
        self._abs(b, bn)                   # b = |b|
        self.seti(self.acc, 0)
        top = self.new_label('mul')
        done = self.new_label('mul_d')
        self.a.label(top.name)              # loop head (must label!)
        self.branch_le0(b, done)        # while b>0
        self.add(self.acc, self.acc, a) # acc += a
        self.sub(b, b, self.a.const(1)) # b -= 1
        self.jmp(top)
        self.a.label(done.name)
        # sign: negate when exactly one of a,b was negative (an XOR bn)
        # sg = an + bn ; if sg==1 -> negate ; sg in {0,2} -> keep
        self.add(sg, an, bn)
        even = self.new_label('mul_e')
        self.branch_le0(sg, even)          # sg<=0 (both 0) -> positive
        flip = self.new_label('mul_f')
        self.sub(self.tmp, sg, self.a.const(1))
        self.branch_le0(self.tmp, flip)    # sg-1<=0 -> sg==1 -> negate
        self.jmp(even)                     # sg==2 (both neg) -> positive
        self.a.label(flip.name)
        self.neg(self.acc, self.acc)       # acc = -acc
        self.a.label(even.name)

    def _sgn(self, flag, slot):
        """flag = (mem[slot] as signed) < 0 ? 1 : 0."""
        self.seti(flag, 0)
        p = self.new_label('sgn')
        self.branch_gt0(slot, p)          # slot>0 -> not neg
        q = self.new_label('sgn')
        self.neg(self.tmp, slot)          # tmp = -slot
        self.branch_le0(self.tmp, q)      # -slot<=0 => slot>=0 => slot==0 -> not neg
        self.seti(flag, 1)
        self.a.label(q.name)
        self.a.label(p.name)

    def _abs(self, slot, negflag):
        """if negflag: slot = -slot."""
        skip = self.new_label('abs')
        self.branch_le0(negflag, skip)
        self.neg(slot, slot)              # neg() is self-safe now
        self.a.label(skip.name)

    def _divmod(self, la, ra, want_mod):
        """acc = la / ra or la % ra (SIGNED, C trunc-toward-zero quotient,
        remainder takes sign of dividend: r = la - q*ra).
        Uses unsigned loop on |la|,|ra| then fixes signs; the remainder is
        derived as la - q*ra so it is correct for any signs."""
        q = self.new_slot('divq'); rem = self.new_slot('divr'); d = self.new_slot('divd')
        lorig = self.new_slot('divl')
        an = self.new_slot('div_an'); bn = self.new_slot('div_bn'); sg = self.new_slot('div_sg')
        self.st(lorig, la)
        self.st(d, ra)
        self.seti(q, 0)
        self._sgn(an, lorig)               # an = la<0
        self._sgn(bn, d)                   # bn = ra<0
        self.st(rem, lorig)
        self._abs(rem, an)                 # rem = |la|
        self._abs(d, bn)                   # d = |ra|
        # unsigned loop: while rem >= d : rem -= d; q++
        # Loop-exit test must be rem < d (STRICTLY less).  branch_le0() jumps
        # when mem <= 0, so testing (rem - d) would ALSO exit when rem == d,
        # skipping the final subtraction and losing 1 from the quotient
        # (256/2 used to come out 127).  Testing (rem - d + 1) <= 0 is
        # equivalent to rem < d and keeps the equality case inside the loop.
        one = self.a.const(1)
        top = self.new_label('div')
        done = self.new_label('div_d')
        self.a.label(top.name)              # loop head (must label!)
        self.sub(self.tmp, rem, d)         # tmp = rem - d
        self.add(self.tmp, self.tmp, one)  # tmp = rem - d + 1
        self.branch_le0(self.tmp, done)    # rem < d -> done
        self.sub(rem, rem, d)
        self.add(q, q, one)
        self.jmp(top)
        self.a.label(done.name)
        # q sign = an XOR bn -> negate if sg==1
        self.add(sg, an, bn)
        even = self.new_label('div_e')
        self.branch_le0(sg, even)
        flip = self.new_label('div_f')
        self.sub(self.tmp, sg, self.a.const(1))
        self.branch_le0(self.tmp, flip)
        self.jmp(even)
        self.a.label(flip.name)
        self.neg(q, q)                     # q = -q (self-safe)
        self.a.label(even.name)
        if want_mod:
            # acc = la - q * ra  (remainder same sign as dividend)
            self._mul(q, d)                # acc = q * ra  (signed)
            self.st(self.tmp, self.acc)
            self.sub(self.acc, lorig, self.tmp)
        else:
            self.st(self.acc, q)

    def _div(self, la, ra):
        self._divmod(la, ra, False)

    def _mod(self, la, ra):
        self._divmod(la, ra, True)

    def _shl(self, la, ra):
        # acc = la << ra : shift count in tmp
        s = self.new_slot('shl'); v = self.new_slot('shl')
        self.st(v, la); self.st(s, ra); self.seti(self.acc, 0)
        self.st(self.tmp, la)
        # simpler: result=v ; loop: if s<=0 done ; v+=v ; s-=1
        top = self.new_label('shl'); done = self.new_label('shl_d')
        self.a.label(top.name)              # loop head (must label!)
        self.branch_le0(s, done)
        self.add(v, v, v)
        self.sub(s, s, self.a.const(1))
        self.jmp(top)
        self.a.label(done.name)
        self.st(self.acc, v)

    def _shr(self, la, ra):
        # acc = la >> ra (logical): halve la ra times
        s = self.new_slot('shr'); v = self.new_slot('shr')
        self.st(v, la); self.st(s, ra)
        top = self.new_label('shr'); done = self.new_label('shr_d')
        self.a.label(top.name)              # loop head (must label!)
        self.branch_le0(s, done)
        # v = v >> 1 : use div by 2 loop
        self._div_const(v, 2)
        self.sub(s, s, self.a.const(1))
        self.jmp(top)
        self.a.label(done.name)
        self.st(self.acc, v)

    def _div_const(self, slot, n):
        """slot = slot / n (n>0, destructive, naive)."""
        q = self.new_slot('dc'); r = self.new_slot('dr')
        self.st(r, slot); self.seti(q, 0)
        # Same strict-inequality concern as _divmod: exit when r < n, i.e.
        # (r - n + 1) <= 0.  A bare (r - n) <= 0 would skip the final
        # subtract when r == n and undercount by one.
        one = self.a.const(1)
        top = self.new_label('dc'); done = self.new_label('dc_d')
        self.a.label(top.name)              # loop head (must label!)
        self.sub(self.tmp, r, self.a.const(n))
        self.add(self.tmp, self.tmp, one)
        self.branch_le0(self.tmp, done)
        self.sub(r, r, self.a.const(n))
        self.add(q, q, one)
        self.jmp(top)
        self.a.label(done.name)
        self.st(slot, q)

    def _bitand(self, la, ra):
        """acc = la & ra (32-bit AND, iterate low to high bit).
        res += ((a&1) * (b&1)) << i over i=0..31."""
        a = self.new_slot('ba'); b = self.new_slot('bb')
        res = self.new_slot('bres'); i = self.new_slot('bi')
        ba = self.new_slot('bita'); bb = self.new_slot('bitb')
        two = self.new_slot('two')
        one = self.a.const(1)
        self.st(a, la); self.st(b, ra)
        self.seti(two, 2)
        self.seti(res, 0); self.seti(i, 0)
        top = self.new_label('ba'); done = self.new_label('bad')
        self.a.label(top.name)
        # while i < 32 : tmp = 32 - i ; i>=32 -> tmp<=0 -> done
        self.sub(self.tmp, self.a.const(32), i)
        self.branch_le0(self.tmp, done)
        # ba = a & 1 ; a >>= 1
        self._mod(a, two)                 # acc = a % 2
        self.st(ba, self.acc)
        self._div_const(a, 2)             # a = a / 2
        # bb = b & 1 ; b >>= 1
        self._mod(b, two)
        self.st(bb, self.acc)
        self._div_const(b, 2)             # b = b / 2
        # res += (ba*bb) << i  (ba,bb each 0/1 so product is AND)
        self._mul(ba, bb)                 # acc = ba * bb
        prod = self.new_slot('prod')
        self.st(prod, self.acc)           # park in DEDICATED slot: never
                                          # pass self.tmp as la to an op
                                          # (ld's first step cell(tmp,tmp)
                                          # zeroes it, reading 0 instead!)
        self._shl(prod, i)                # acc = prod << i
        self.add(res, res, self.acc)
        self.add(i, i, one)
        self.jmp(top)
        self.a.label(done.name)
        self.st(self.acc, res)
    def _bitor(self, la, ra):
        raise NotImplementedError('bitwise |')
    def _bitxor(self, la, ra):
        raise NotImplementedError('bitwise ^')

    def _cmp(self, op, l, r):
        """acc = (l op r) ? 1 : 0  (signed; diff = l - r).
        Right operand is kept in _r0 (NOT _tmp): the second _pop() clobbers
        _tmp via its internal st(ptr,sp)/_load_indirect, so parking r in
        _tmp would corrupt d = l - r (and every loop/cmp built on it)."""
        self.expr(l)
        self._push(self.acc)
        self.expr(r)
        self._push(self.acc)
        self._pop(self.r0)    # r0 = r
        self._pop(self.acc)   # acc = l
        d = self.new_slot('cmpd')
        self.sub(d, self.acc, self.r0)      # d = l - r
        done = self.new_label('cmp')
        if op == '<=':
            le = self.new_label('cle')
            self.branch_le0(d, le)
            self.seti(self.acc, 0)
            self.jmp(done)
            self.a.label(le.name)
            self.seti(self.acc, 1)
        elif op == '>':
            le = self.new_label('cgt')
            self.branch_le0(d, le)
            self.seti(self.acc, 1)
            self.jmp(done)
            self.a.label(le.name)
            self.seti(self.acc, 0)
        elif op == '<':
            # l<r : d<0 : d<=0 and !(d==0)
            n2 = self.new_slot('cmpn')
            self.neg(n2, d)
            le = self.new_label('clt')
            self.branch_le0(d, le)
            self.seti(self.acc, 0)          # d>0 -> false
            self.jmp(done)
            self.a.label(le.name)
            eq = self.new_label('clt_e')
            self.branch_le0(n2, eq)         # -d<=0 => d>=0 => d==0 (d<=0 known)
            self.seti(self.acc, 1)          # d<0 -> true
            self.jmp(done)
            self.a.label(eq.name)
            self.seti(self.acc, 0)          # d==0 -> false
        elif op == '>=':
            lt = self.new_label('cge')
            n2 = self.new_slot('cmpn')
            self.neg(n2, d)
            self.branch_le0(d, lt)          # d<=0 ? maybe true (d<0)
            self.seti(self.acc, 1)          # d>0 -> true
            self.jmp(done)
            self.a.label(lt.name)
            lt2 = self.new_label('cge2')
            self.branch_le0(n2, lt2)        # -d<=0 => d>=0 => d==0 -> true
            self.seti(self.acc, 0)          # d<0 -> false
            self.jmp(done)
            self.a.label(lt2.name)
            self.seti(self.acc, 1)          # d==0 -> true
        elif op == '==':
            n2 = self.new_slot('cmpn')
            self.neg(n2, d)
            le = self.new_label('ceq')
            self.branch_le0(d, le)          # d<=0 (d==0 or d<0)
            self.seti(self.acc, 0)          # d>0 -> false
            self.jmp(done)
            self.a.label(le.name)
            nz = self.new_label('ceq2')
            self.branch_le0(n2, nz)         # -d<=0 => d>=0 => d==0 -> true
            self.seti(self.acc, 0)          # d<0 -> false
            self.jmp(done)
            self.a.label(nz.name)
            self.seti(self.acc, 1)
        elif op == '!=':
            n2 = self.new_slot('cmpn')
            self.neg(n2, d)
            le = self.new_label('cne')
            self.branch_le0(d, le)          # d<=0
            self.seti(self.acc, 1)          # d>0 -> true
            self.jmp(done)
            self.a.label(le.name)
            nz = self.new_label('cne2')
            self.branch_le0(n2, nz)         # -d<=0 => d==0
            self.seti(self.acc, 1)          # d<0 -> true
            self.jmp(done)
            self.a.label(nz.name)
            self.seti(self.acc, 0)          # d==0 -> false
        else:
            raise NotImplementedError('cmp %s' % op)
        self.a.label(done.name)

    def _settrue(self, done):
        """Return a label for 'true' path; sets acc=1, jumps done."""
        t = self.new_label('cmpt')
        self.seti(self.acc, 1)
        self.jmp(done)
        self.a.label(t.name)
        self._last_true = t
        return t

    # ---------------- unary ----------------
    def e_Unary(self, e):
        op = e.op
        if op == '-':
            self.expr(e.e)
            self.neg(self.acc, self.acc)
        elif op == '!':
            self.expr(e.e)
            t = self.new_label('not')
            self.branch_le0(self.acc, t)
            self.seti(self.acc, 0)
            j = self.new_label('notj')
            self.jmp(j)
            self.a.label(t.name)
            self.seti(self.acc, 1)
            self.a.label(j.name)
        elif op == '~':
            self.expr(e.e)
            self._not_bits(self.acc)
        elif op == '*':
            self.expr(e.e)               # acc = pointer
            self._load_indirect(self.acc)
        elif op == '&':
            self._addr_of(e.e)           # acc = address
        elif op == '++':
            self.expr(e.e)
            self.add(self.acc, self.acc, self.a.const(1))
            self._store_lvalue(e.e, self.acc)
        elif op == '--':
            self.expr(e.e)
            self.sub(self.acc, self.acc, self.a.const(1))
            self._store_lvalue(e.e, self.acc)
        elif op == 'cast':
            self.expr(e.e)               # no-op in flat word model
        else:
            raise NotImplementedError('unary %s' % op)

    def _not_bits(self, slot):
        # acc = ~slot = 0xFFFFFFFF - slot
        self.seti(self.tmp, 0xffffffff)
        self.sub(self.acc, self.tmp, slot)

    def e_PostInc(self, e):
        self._postinc(e.name, 1)

    def e_PostDec(self, e):
        self._postinc(e.name, -1)

    def _postinc(self, name, delta):
        # Resolve the variable's storage: globals are compile-time fixed
        # symbols, locals are fixed per-function slots.  Post-increment must
        # leave the ORIGINAL value in acc (for the enclosing expression) and
        # write back the +delta value.
        #
        # IMPORTANT: st(sym, tmp) below internally does ld(acc, tmp), which
        # would clobber acc (the old value).  So we stash old in vtmp (a slot
        # never touched by store internals) before the write-back and reload
        # it afterwards.
        if name in self.globals and not self.globals[name]['array']:
            sym = self.globals[name]['sym']
        elif self.cur is not None and name in self.cur['locals']:
            sym = self.cur['locals'][name]
        else:
            raise KeyError('post-inc %s' % name)
        self.ld(self.acc, sym)
        self.st(self.vtmp, self.acc)      # vtmp = old value
        self.ld(self.tmp, sym)
        if delta == 1:
            self.add(self.tmp, self.tmp, self.a.const(1))
        else:
            self.sub(self.tmp, self.tmp, self.a.const(1))
        self.st(sym, self.tmp)
        self.ld(self.acc, self.vtmp)      # acc = old value (post-inc result)

    # ---------------- lvalue / index / member ----------------
    def _index_addr(self, base, idx, step):
        """acc = address-of(base) + idx*step (step is compile-time word
        count per element).  base may be Name array (address) or pointer
        expression (value); idx is an evaluated expression."""
        if step == 1:
            self.expr(base)
            self._push(self.acc)
            self.expr(idx)
            self._push(self.acc)
            self._pop(self.idx)
            self._pop(self.acc)
            self.add(self.acc, self.acc, self.idx)
            return
        # step > 1: scale idx by step (compile-time constant).
        self.expr(base)
        self._push(self.acc)
        self.expr(idx)
        self._push(self.acc)
        self._pop(self.idx)          # idx = raw index
        self._pop(self.acc)          # acc = base addr
        # park the base address in the DEDICATED baddr slot.  It CANNOT
        # live in tmp2: add()/sub() primitives (called below in the loop)
        # use tmp2 as their internal accumulator and zero it out on entry.
        self.st(self.baddr, self.acc)
        acc = self.acc
        self.seti(acc, 0)
        top = self.new_label('idxm')
        done = self.new_label('idxm')
        self.a.label(top.name)
        self.branch_le0(self.idx, done)
        self.add(acc, acc, self.a.const(step))
        self.sub(self.idx, self.idx, self.a.const(1))
        self.jmp(top)
        self.a.label(done.name)      # acc = idx*step
        self.add(acc, acc, self.baddr)  # acc = base + idx*step
    def _store_lvalue(self, l, valslot):
        t = type(l).__name__
        if t == 'Name':
            self._store_name(l.name, valslot)
        elif t == 'Index':
            # lvalue = base[idx]; compute address then store indirect
            self._index_addr(l.base, l.idx, l.step)
            # park the address in ptr: _indirect_store re-writes the
            # trampoline A/B fields with subsequent st(field, addr_of(...))
            # calls whose internal ld(acc, src) CLOBBERS acc, so the second
            # st(field1, ptr_reg) would write a corrupted pointer if
            # ptr_reg were acc.
            self.st(self.ptr, self.acc)
            self._indirect_store(self.ptr, valslot)
        elif t == 'Member':
            # addr = &base + offset
            self._member_addr(l.base, l.offset)
            self._indirect_store(self.ptr, valslot)
        elif t == 'Unary' and l.op == '*':
            # *p = value : the operand's VALUE is the target address.
            # Evaluate it, park it in ptr, then store indirectly.
            self.expr(l.e)
            self.st(self.ptr, self.acc)
            self._indirect_store(self.ptr, valslot)
        else:
            raise NotImplementedError('lvalue %s' % t)

    def _store_name(self, name, valslot):
        if name in self.globals and not self.globals[name]['array']:
            self.st(self.globals[name]['sym'], valslot)
        elif self.cur is not None and name in self.cur['locals']:
            self.st(self.cur['locals'][name], valslot)
        else:
            raise KeyError('unknown lvalue %s' % name)

    def _addr_of(self, e):
        t = type(e).__name__
        if t == 'Name':
            name = e.name
            if name in self.globals:
                self.set_addr(self.acc, self.globals[name]['sym'])
            elif self.cur is not None and name in self.cur['locals']:
                self.set_addr(self.acc, self.cur['locals'][name])
            else:
                raise KeyError('addr of %s' % name)
        elif t == 'Index':
            self._index_addr(e.base, e.idx, e.step)
        elif t == 'Member':
            self._member_addr(e.base, e.offset)
        elif t == 'Unary' and e.op == '*':
            # &*p == p
            self.expr(e.e)
        else:
            raise NotImplementedError('addr of %s' % t)
    def _member_addr(self, base, offset):
        """acc = address-of(base) + offset, then park in ptr.
        base may be Name / Index / Member / Unary('*') (deref)."""
        bt = type(base).__name__
        if bt == 'Name':
            name = base.name
            if name in self.globals:
                self.set_addr(self.acc, self.globals[name]['sym'])
            elif self.cur is not None and name in self.cur['locals']:
                self.set_addr(self.acc, self.cur['locals'][name])
            else:
                raise KeyError('addr of %s' % name)
        elif bt == 'Index':
            self._index_addr(base.base, base.idx, base.step)
        elif bt == 'Member':
            self._member_addr(base.base, base.offset)
        elif bt == 'Unary' and base.op == '*':
            # *(p) : base is deref of a pointer expression -> value is addr
            self.expr(base.e)
        else:
            # fallback: treat expr() result as a value address (rare)
            self.expr(base)
        if offset:
            self.add(self.acc, self.acc, self.a.const(offset))
        self.st(self.ptr, self.acc)

    def e_Assign(self, e):
        op = e.op
        if op == '=':
            self.expr(e.r)
            self.st(self.r0, self.acc)   # park value in r0: _store_lvalue
                                         # with Index target clobbers acc
                                         # while evaluating base/idx
            self._store_lvalue(e.l, self.r0)
        else:
            base = op[:-1]
            self.expr(e.l)
            self._push(self.acc)
            self.expr(e.r)
            self._push(self.acc)
            self._pop(self.r0)
            self._pop(self.acc)
            self._arith(base, self.acc, self.r0)
            self.st(self.r0, self.acc)   # same: park result before lvalue
            self._store_lvalue(e.l, self.r0)

    def e_Index(self, e):
        self._index_addr(e.base, e.idx, e.step)   # acc = &elem
        # park in ptr: _load_indirect's internal st(field, addr_of(...))
        # clobbers acc via ld(acc, src); ptr is untouched.
        self.st(self.ptr, self.acc)
        self._load_indirect(self.ptr)            # acc = *(&elem)

    def e_Member(self, e):
        # acc = *(base_addr + offset)
        self._member_addr(e.base, e.offset)
        self._load_indirect(self.ptr)   # acc = value at ptr

    # ---------------- call ----------------
    def e_Call(self, e):
        name = e.name
        # ---- MMIO intrinsics (no ghost byte) ----
        # A plain `*(volatile u32*)PORT = c` goes through st(), whose
        # subleq(dst,dst) zero step also hits the UART write port and emits
        # an extra 0x00.  Single-step output: tmp = -c ; subleq tmp, TX
        # (reads 0 back, writes exactly c, falls through).  OSCC compiles
        # these names directly - no runtime call frame, no arg slot.
        if name == '__oisc_putc':
            self.expr(e.args[0])
            # nb = -c  (neg handles dst==src via tmp copy)
            self.neg(self.nb, self.acc)
            # subleq nb, TX : TX -= (-c) => TX = c ; res = c > 0 -> fallthru
            self.a.cell(self._addr(self.nb), self.a.reg('TX'))
            self.ld(self.acc, self.nb)   # acc = -c (unspecified return)
            return
        if name == '__oisc_puts':
            # draw a string from a char* argument, byte by byte
            self.expr(e.args[0])
            self.st(self.ptr, self.acc)      # ptr = s
            top = self.new_label('puts')
            done = self.new_label('puts')
            self.a.label(top.name)
            self._load_indirect(self.ptr)    # acc = *ptr
            self.branch_le0(self.acc, done)  # NUL (or empty) -> done
            self.neg(self.nb, self.acc)
            self.a.cell(self._addr(self.nb), self.a.reg('TX'))
            # ptr++
            self.ld(self.acc, self.ptr)
            self.add(self.acc, self.acc, self.a.const(1))
            self.st(self.ptr, self.acc)
            self.jmp(top)
            self.a.label(done.name)
            return
        if name not in self.funcs:
            raise ValueError('call to undefined %s' % name)
        fn = self.funcs[name]
        for i, arg in enumerate(e.args[:4]):
            self.expr(arg)
            self.st(self.arg[i], self.acc)
        ret = self.new_label('ret')
        # save old RA on stack (callee overwrites RA with its own return path).
        self._push(self.ra)
        # Locals are FIXED per-function slots (__l_<func>_<var>).  Only a
        # call to THIS SAME function can clobber them (same slot names).
        # Calls to OTHER functions must NOT snapshot/restore locals: doing so
        # would save their pre-call values and then clobber any writes the
        # callee made through pointers passed in (e.g. f(&local) -> *p = 7
        # gets wiped when the caller restores its locals to the snapshot).
        recursive = (self.cur is not None and name == self.cur['name'])
        if recursive:
            loc_names = list(self.cur['locals'].keys())
            for ln in loc_names:
                self._push(self.cur['locals'][ln])
        # RA = ret
        self.set_addr(self.ra, ret)
        self.jmp(fn['label'])
        self.a.label(ret.name)
        if recursive:
            for ln in reversed(loc_names):
                self._pop(self.cur['locals'][ln])
        self._pop(self.ra)          # restore caller's RA
        self.ld(self.acc, self.r0)  # acc = return value

    # ---------------- statements ----------------
    def stmt(self, s):
        t = type(s).__name__
        m = getattr(self, 's_' + t, None)
        if m is None:
            raise NotImplementedError('stmt: ' + t)
        m(s)

    def s_Block(self, s):
        for st in s.stmts:
            self.stmt(st)

    def s_ExprStmt(self, s):
        self.expr(s.expr)

    def s_Empty(self, s):
        pass

    def s_VarDecl(self, s):
        slot = self._localslot(s.name)
        if s.init is not None:
            self.expr(s.init)
            self.st(slot, self.acc)

    def s_Ret(self, s):
        if s.expr is not None:
            self.expr(s.expr)
            self.st(self.r0, self.acc)
        self.jmp(self.cur['epilogue'])

    def s_Break(self, s):
        self.jmp(self.break_stack[-1])

    def s_Cont(self, s):
        self.jmp(self.cont_stack[-1])

    def s_If(self, s):
        end = self.new_label('if')
        els = self.new_label('if')
        self.expr(s.cond)
        self.branch_le0(self.acc, els)
        self.stmt(s.then)
        if s.els is not None:
            self.jmp(end)
            self.a.label(els.name)
            self.stmt(s.els)
        else:
            self.a.label(els.name)
        self.a.label(end.name)

    def s_While(self, s):
        top = self.new_label('wh')
        out = self.new_label('wh')
        self.break_stack.append(out)
        self.cont_stack.append(top)
        self.a.label(top.name)
        self.expr(s.cond)
        self.branch_le0(self.acc, out)
        self.stmt(s.body)
        self.jmp(top)
        self.a.label(out.name)
        self.break_stack.pop()
        self.cont_stack.pop()
    def s_DoWhile(self, s):
        top = self.new_label('dw')
        out = self.new_label('dw')
        # For a do-while, `continue` jumps to the CONDITION, not the top.
        cont = self.new_label('dw')
        self.break_stack.append(out)
        self.cont_stack.append(cont)
        self.a.label(top.name)
        self.stmt(s.body)
        self.a.label(cont.name)
        self.expr(s.cond)
        self.branch_gt0(self.acc, top)   # while(cond) -> back to top
        self.a.label(out.name)
        self.break_stack.pop()
        self.cont_stack.pop()

    def s_For(self, s):
        top = self.new_label('fo')
        out = self.new_label('fo')
        cont = self.new_label('fo')
        self.break_stack.append(out)
        self.cont_stack.append(cont)
        if s.init:
            self.expr(s.init)
        self.a.label(top.name)
        if s.cond:
            self.expr(s.cond)
            self.branch_le0(self.acc, out)
        self.stmt(s.body)
        self.a.label(cont.name)
        if s.post:
            self.expr(s.post)
        self.jmp(top)
        self.a.label(out.name)
        self.break_stack.pop()
        self.cont_stack.pop()

    # ---------------- functions / globals ----------------
    def _localslot(self, name):
        if name not in self.cur['locals']:
            self.cur['locals'][name] = self.a.slot('__l_%s_%s'
                                                   % (self.cur['name'], name))
        return self.cur['locals'][name]

    def add_function(self, name, plist):
        self.funcs[name] = {'label': L('f_%s' % name), 'locals': {},
                            'plist': plist, 'name': name}

    def define_func(self, fn):
        name = fn.name
        fnrec = self.funcs[name]
        self.a.label(fnrec['label'].name)
        self.cur = fnrec
        # copy args A0.. into local slots
        for i, pname in enumerate(fn.plist[:4]):
            if not pname:
                continue
            slot = self._localslot(pname)
            self.ld(self.acc, self.arg[i])
            self.st(slot, self.acc)
        epi = self.new_label('fepi')
        fnrec['epilogue'] = epi
        if fn.body is not None:
            self.stmt(fn.body)
        self.a.label(epi.name)
        if name == self.entry:
            # entry function: program ends here -> explicit halt
            self.a.halt()
        else:
            # return: PC = mem[RA]  (indirect jump)
            self._indirect_jump(self.ra)
        self.cur = None

    def declare_global(self, name, typ, init):
        size = typ.size() if typ else 1
        if size is None:
            size = 1
        # struct types carry their size in the layout table.
        if typ is not None:
            # arrays of structs: n_elems * elem_size
            if typ.arr is not None and typ.base == 'struct' and typ.tag \
               and typ.tag in self.struct_layouts:
                _, esz, _ = self.struct_layouts[typ.tag]
                size = typ.arr * esz
            elif typ.base == 'struct' and typ.tag \
                 and typ.tag in self.struct_layouts:
                _, sz, _ = self.struct_layouts[typ.tag]
                size = max(size, sz)
        sym = self.a.glob('__g_%s' % name, max(size, 1))
        isarr = typ is not None and typ.arr is not None
        self.globals[name] = {'sym': sym, 'array': isarr}
        # global scalar init
        if init is not None and (typ is None or typ.arr is None):
            self.expr(init)
            self.st(sym, self.acc)

    # ---------------- driver ----------------
    def compile(self, decls, entry='main'):
        self.entry = entry if entry in [d.name for d in decls if isinstance(d, Func)] else None
        # pass 1: functions, globals
        for d in decls:
            if isinstance(d, Func):
                self.add_function(d.name, d.plist)
            elif isinstance(d, Glob):
                self.declare_global(d.name, d.typ, d.init)
        # ENTRY BLOCK: emit FIRST (before any function bodies) so the
        # simulator starts by initializing SP and jumping to entry.
        if self.entry is None:
            # fallback: first function
            self.entry = next(iter(self.funcs), None)
        if self.entry is None:
            raise ValueError('no functions')
        self.set_addr(self.sp, self.a.addr_off(self.stack, STACK_WORDS - 1))
        self.jmp(self.funcs[self.entry]['label'])
        # pass 2: function bodies
        for d in decls:
            if isinstance(d, Func):
                self.define_func(d)

    # ---------------- finish ----------------
    def build(self):
        """Finalize: attach trampoline cells, then produce flat words."""
        z = self._z()
        # indirect subleq trampoline: [A,B,C1] followed by convergence
        # [Z,Z,C2]; both patched at runtime via self-modification.
        self.a.label(self.tpl_label.name)
        self.a.cell(self.tplA, self.tplB, self.tplC)   # patched cell1
        self.a.label(self.tpl_next.name)
        self.a.cell(z, z, self.tplC)                    # convergence cell
        # indirect jump trampoline
        self.a.label(self.tpl_jmp.name)
        self.a.cell(z, z, self.tplC)
        words = self.a.build()
        # patch string literal contents into their global slots.  e_Str only
        # ALLOCATES the __str_N glob (addr via set_addr); the actual bytes
        # (len+1 words: chars then NUL) must be copied into the image here,
        # since the assembler data section is otherwise zero-filled.
        for b, sg in self.strs:
            addr = self.a.globs[sg.name][1]
            for i, ch in enumerate(b):
                words[addr + i] = ch
            if addr + len(b) < len(words):
                words[addr + len(b)] = 0   # NUL terminator
        return words

    # temp slots creator
    def new_slot(self, hint='s'):
        self.label_n += 1
        return self.a.slot('__%s_%d' % (hint, self.label_n))


# ------------------------------------------------------------------
# Driver
# ------------------------------------------------------------------
def compile_c(src, out_path, cur_file='<input>', include_paths=None,
              pre=True):
    """Compile C source to SUBLEQ words.

    When pre=True (default) the source first goes through preproc.preprocess,
    which resolves #include/#define/#if conditionals; this is required for
    any kernel-style source.  Pass pre=False to hand raw text to the parser
    (all existing regression tests do this, since that path is
    preprocessor-free and faster).
    """
    if pre:
        paths = list(include_paths or [])
        if '.' not in paths:
            paths.append('.')
        src = preprocess(src, cur_file, paths)
    toks = tokenize(src)
    p = Parser(toks)
    decls = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(decls)
    words = cg.build()
    write_words(out_path, words)
    return words


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print('usage: python3 oscc.py [-I<path> ...] file.c [out.bin]')
        sys.exit(1)
    inc = ['.']
    src_args = []
    for a in args:
        if a.startswith('-I'):
            inc.append(a[2:])
        else:
            src_args.append(a)
    if not src_args:
        print('usage: python3 oscc.py [-I<path> ...] file.c [out.bin]')
        sys.exit(1)
    src = open(src_args[0]).read()
    out = src_args[1] if len(src_args) > 1 else '/tmp/out.bin'
    words = compile_c(src, out, cur_file=src_args[0], include_paths=inc)
    print('ok: %d words (%d bytes) -> %s' % (len(words), len(words) * 4, out))