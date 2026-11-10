#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""preproc.py - minimal C preprocessor for OSCC.

Supports the subset of the C preprocessor needed by kernel-style C:
  - #include "file" / <file>  (relative to CWD + include paths, guard via
    #pragma once and include-once convention)
  - #define NAME body          (object macro)
  - #define NAME(a,b) body     (function-like macro)
  - # for stringize, ## for token paste
  - #undef NAME
  - #if / #ifdef / #ifndef / #elif / #else / #endif
  - #error / #warning / #pragma (ignored/raised)
  - `` comments stripped by tokenizer anyway.

Macro expansion is token-level (identifier tokens only), with a recursion
guard per expansion so self/mutual references stay inert (C semantics).

Output is pure C text with all directives consumed.
"""
import os
import re


class PreprocError(Exception):
    pass


class Preproc:
    def __init__(self, include_paths=None):
        self.macros = {}          # name -> (params|None, body_tokens)
        self.include_paths = include_paths or ['.']
        self.included = set()     # absolute paths already included
        self._cur_file = '<input>'

    # ------------------------------------------------------------- tokenizer
    _RE_TOK = re.compile(r'''
        \s+
      | (?P<str>"(?:\\.|[^"\\])*")
      | (?P<chr>'(?:\\.|[^'\\])*')
      | (?P<num>[0-9a-zA-Z_.]+)
      | (?P<punct>\#\#|<<=|>>=|\+\+|--|->|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%<>=!&|^~,()\[\]{};:?])
      | (?P<other>.)
    ''', re.VERBOSE)

    @staticmethod
    def tokenize_line(line):
        toks = []
        for m in Preproc._RE_TOK.finditer(line):
            s = m.group(0)
            if s.startswith((' ', '\t')):
                continue
            toks.append(s)
        return toks

    # ------------------------------------------------------- macro handling
    def define(self, name, params, body_toks):
        self.macros[name] = (params, list(body_toks))

    def is_macro(self, name):
        return name in self.macros

    # ------------------------------------------- token-level macro expansion
    def expand_tokens(self, toks, depth=0, active_sets=None):
        """Expand macro calls in a token list (well-formed, no unbalanced
        parens across lines -- function-macro calls are single-line per C
        practice in kernel code)."""
        if active_sets is None:
            active_sets = []
        out = []
        i = 0
        n = len(toks)
        while i < n:
            t = toks[i]
            # object-like identifier?
            if t.isidentifier() and t in self.macros and t not in active_sets:
                params, body = self.macros[t]
                if params is None:
                    # object macro: expand body with guard
                    out.extend(self.expand_tokens(
                        body, depth + 1, active_sets + [t]))
                    i += 1
                    continue
                # function-like: need '(' next (skip whitespace--already gone)
                if i + 1 < n and toks[i + 1] == '(':
                    # gather args
                    depth_p = 0
                    j = i + 1
                    # For a zero-parameter macro call `F()`, the arg list is
                    # EMPTY -- not one empty argument.  Start with no args and
                    # only create the first slot when we see a real token.
                    args = []
                    cur = []
                    while j < n:
                        c = toks[j]
                        if c == '(':
                            depth_p += 1
                            if depth_p > 1:
                                cur.append(c)
                        elif c == ')':
                            depth_p -= 1
                            if depth_p == 0:
                                break
                            cur.append(c)
                        elif c == ',' and depth_p == 1:
                            args.append(cur)
                            cur = []
                        else:
                            cur.append(c)
                        j += 1
                    if j >= n:
                        raise PreprocError('unterminated macro call %s(' % t)
                    # flush the trailing argument only if it is non-empty;
                    # `F()` therefore yields args == [] as C requires.
                    if cur or args:
                        args.append(cur)
                    expect_n = len(params)
                    if len(args) != expect_n:
                        raise PreprocError(
                            'macro %s expects %d args got %d'
                            % (t, expect_n, len(args)))
                    # expand args first
                    arg_map = {}
                    for k, pname in enumerate(params):
                        arg_map[pname] = self.expand_tokens(
                            args[k], depth + 1, active_sets)
                    # substitute, handling # (stringize) and ## (paste)
                    newtoks = []
                    bl = 0
                    while bl < len(body):
                        bt = body[bl]
                        if bt == '#' and bl + 1 < len(body) \
                           and body[bl + 1] in arg_map:
                            # stringize
                            av = arg_map[body[bl + 1]]
                            newtoks.append('"' + ' '.join(av) + '"')
                            bl += 2
                            continue
                        if bt == '##' and bl + 1 < len(body):
                            # token paste: concatenate previous emitted
                            # token with next (param or literal)
                            if newtoks:
                                nxt = body[bl + 1]
                                if nxt in arg_map:
                                    nxtval = ''.join(arg_map[nxt])
                                else:
                                    nxtval = nxt
                                newtoks[-1] = newtoks[-1] + nxtval
                                bl += 2
                                continue
                        if bt in arg_map:
                            newtoks.extend(
                                self.expand_tokens(arg_map[bt], depth + 1,
                                                   active_sets))
                            bl += 1
                            continue
                        # nested macro inside body
                        if bt in self.macros and bt not in active_sets:
                            sub = self.expand_tokens(
                                [bt], depth + 1, active_sets + [t])
                            newtoks.extend(sub)
                            bl += 1
                            continue
                        newtoks.append(bt)
                        bl += 1
                    out.extend(self.expand_tokens(
                        newtoks, depth + 1, active_sets + [t]))
                    i = j + 1
                    continue
                # function macro without '(' -> leave as-is
                out.append(t)
                i += 1
            else:
                out.append(t)
                i += 1
        return out

    # ------------------------------------------------- #if expression evaluator
    def _eval_if(self, expr_text):
        # resolve defined() first
        def repl_defined(m):
            name = m.group(1)
            return '1' if name in self.macros else '0'
        expr_text = re.sub(r'defined\s*\(\s*([A-Za-z_]\w*)\s*\)',
                           repl_defined, expr_text)
        expr_text = re.sub(r'\bdefined\s+([A-Za-z_]\w*)',
                           lambda m: '1' if m.group(1) in self.macros else '0',
                           expr_text)
        # replace macro identifiers with their expansion (object macros only)
        toks = self.tokenize_line(expr_text)
        ev = self.expand_tokens(toks)
        expr_text = ' '.join(ev)
        # replace remaining identifiers with 0
        expr_text = re.sub(r'\b[A-Za-z_]\w*', '0', expr_text)
        expr_text = expr_text.replace('&&', ' and ').replace('||', ' or ')
        expr_text = expr_text.replace('!', ' not ')
        # mask to 32-bit arithmetic
        try:
            code = expr_text
            # arithmetic ops keep Python semantics; fine for kernel ifs
            v = eval(code, {'__builtins__': {}}, {})
            return int(v) != 0
        except Exception as e:
            raise PreprocError('#if expression error: %r (%s)' % (expr_text, e))

    # ------------------------------------------------------------ main loop
    def process(self, src, cur_file='<input>'):
        self._cur_file = cur_file
        self._cond_stack = []       # list of (parent_active, this_branch_taken, else_seen, was_active)
        out = []
        # strip BLOCK comments globally first: they may span lines and a
        # per-line regex would never close across the newline boundary.
        src = re.sub(r'/\*.*?\*/', ' ', src, flags=re.DOTALL)
        lines = src.split('\n')
        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            # merge continuation lines
            while raw.rstrip().endswith('\\') and i + 1 < n:
                i += 1
                raw = raw[:-1] + lines[i]
            line = raw
            # strip line comments (after continuation merge, so a trailing
            # backslash-continued line with // on the second part is handled)
            line = re.sub(r'//.*$', ' ', line)
            stripped = line.strip()
            # active-ness: a directive/line is processed only if all enclosing
            # #if branches are active
            active = True
            for st in self._cond_stack:
                if not st['active']:
                    active = False
                    break
            if stripped.startswith('#'):
                pl = self.tokenize_line(stripped[1:].lstrip())
                if not pl:
                    i += 1
                    continue
                cmd = pl[0]
                argline = stripped[len(cmd) + 1:].strip()
                if cmd == 'include':
                    if not active:
                        i += 1
                        continue
                    # parse "..." or <...>
                    m = re.match(r'[<"]([^>"]+)[>"]', argline)
                    if not m:
                        raise PreprocError('bad #include: %s' % argline)
                    fname = m.group(1)
                    path = self._find_include(fname)
                    if path is None:
                        raise PreprocError(
                            '%s: cannot find include <%s>'
                            % (self._cur_file, fname))
                    apath = os.path.abspath(path)
                    if apath not in self.included:
                        self.included.add(apath)
                        try:
                            with open(path, 'r', errors='replace') as f:
                                sub = f.read()
                        except OSError as e:
                            raise PreprocError('include %s: %s' % (path, e))
                        # process() starts by resetting the SHARED cond stack
                        # (self._cond_stack = []), which would destroy the
                        # enclosing file's #if state.  Save/restore it around
                        # the recursive call so each file keeps its own stack
                        # while macro/define state stays shared.
                        saved_stack = self._cond_stack
                        saved_file = self._cur_file
                        sub_out = self.process(sub, path)
                        self._cond_stack = saved_stack
                        self._cur_file = saved_file
                        out.extend(sub_out)
                    i += 1
                    continue
                if cmd == 'define':
                    if not active:
                        i += 1
                        continue
                    i = self._handle_define(lines, i, argline)
                    continue
                if cmd == 'undef':
                    if active and len(pl) >= 2:
                        self.macros.pop(pl[1], None)
                    i += 1
                    continue
                if cmd in ('if', 'ifdef', 'ifndef'):
                    parent_active = active
                    if cmd == 'ifdef':
                        cond = len(pl) >= 2 and pl[1] in self.macros
                    elif cmd == 'ifndef':
                        cond = not (len(pl) >= 2 and pl[1] in self.macros)
                    else:
                        cond = self._eval_if(argline)
                    # taken_here: this group has already selected a branch,
                    # so every later #elif/#else in the group stays inert.
                    # NOTE: parent_active must gate it -- when the enclosing
                    # block is inactive this whole group is dead anyway.
                    self._cond_stack.append({
                        'active': parent_active and cond,
                        'parent': parent_active,
                        'else_seen': False,
                        'taken_here': parent_active and cond,
                    })
                    i += 1
                    continue
                if cmd == 'elif':
                    if not self._cond_stack:
                        raise PreprocError('#elif without #if')
                    st = self._cond_stack[-1]
                    if st['else_seen']:
                        raise PreprocError('#elif after #else')
                    # Only the FIRST true branch of a group may be active.
                    # If a previous branch already won (taken_here) or the
                    # enclosing context is inactive, this branch is dead --
                    # otherwise its body would leak into the output.
                    if st['parent'] and not st['taken_here']:
                        c = self._eval_if(argline)
                        st['active'] = c
                        if c:
                            st['taken_here'] = True
                    else:
                        st['active'] = False
                    i += 1
                    continue
                if cmd == 'else':
                    if not self._cond_stack:
                        raise PreprocError('#else without #if')
                    st = self._cond_stack[-1]
                    if st['else_seen']:
                        raise PreprocError('duplicate #else')
                    st['else_seen'] = True
                    if st['parent'] and not st['taken_here']:
                        st['active'] = True
                        st['taken_here'] = True
                    else:
                        st['active'] = False
                    i += 1
                    continue
                if cmd == 'endif':
                    if not self._cond_stack:
                        raise PreprocError('#endif without #if')
                    self._cond_stack.pop()
                    i += 1
                    continue
                if cmd == 'error':
                    if active:
                        raise PreprocError('#error %s' % argline)
                    i += 1
                    continue
                if cmd in ('warning', 'pragma', 'line'):
                    i += 1
                    continue
                # unknown directive: ignore
                i += 1
                continue
            # ordinary line
            if active:
                toks = self.tokenize_line(line)
                if toks:
                    ex = self.expand_tokens(toks)
                    out.append(' '.join(ex))
                else:
                    out.append('')   # blank line (keeps line count)
            i += 1
        if self._cond_stack:
            raise PreprocError('unterminated #if')
        return out

    def _handle_define(self, lines, i, argline):
        pl = self.tokenize_line(argline)
        if not pl:
            raise PreprocError('bad #define')
        name = pl[0]
        # A function-like macro requires '(' IMMEDIATELY after the name
        # (no whitespace).  Match only the name (no trailing ws) so a
        # parenthesized body like `(A + 1)` stays an object macro.
        m = re.match(r'\s*([A-Za-z_]\w*)', argline)
        rest = argline[m.end():] if m else ''
        is_fn = rest.startswith('(')
        if is_fn:
            params = []
            j = 2          # skip name and '('
            while j < len(pl) and pl[j] != ')':
                params.append(pl[j])
                j += 1
                if j < len(pl) and pl[j] == ',':
                    j += 1
            body = pl[j + 1:] if j + 1 < len(pl) else []
            self.define(name, params, body)
            return i + 1
        body = pl[1:]
        self.define(name, None, body)
        return i + 1

    def _find_include(self, fname):
        # quoted: relative to current file dir first, then include paths
        cands = []
        d = os.path.dirname(os.path.abspath(self._cur_file))
        cands.append(os.path.join(d, fname))
        for p in self.include_paths:
            cands.append(os.path.join(p, fname))
        for c in cands:
            if os.path.isfile(c):
                return c
        return None


def preprocess(src, cur_file='<input>', include_paths=None):
    pp = Preproc(include_paths)
    lines = pp.process(src, cur_file)
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: python3 preproc.py file.c [out.i]')
        sys.exit(1)
    src = open(sys.argv[1]).read()
    out = preprocess(src, sys.argv[1], ['/opt/oisk'])
    if len(sys.argv) >= 3:
        open(sys.argv[2], 'w').write(out + '\n')
    else:
        sys.stdout.write(out + '\n')