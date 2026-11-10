#!/usr/bin/env python3
"""Preprocessor regression suite for OSCC (tests/preproc_test.py).

Covers: object macros, function-like macros (+ ## paste, # stringize),
conditional compilation (#if/#ifdef/#ifndef/#elif/#else), numeric #if with
defined(), #include resolution, #undef, nested macro expansion, multi-line
macros (backslash continuation), comment stripping, macro args containing
commas inside parens, and #error raising.
"""
import os
import sys
import tempfile

sys.path.insert(0, '/opt/oisk')
from preproc import preprocess, PreprocError


def squash(text):
    """Collapse all whitespace so we can compare token streams loosely."""
    return ' '.join(text.split())


results = []


def case(name, fn):
    try:
        ok = fn()
    except Exception as e:
        print('%-24s EXC %s: %s' % (name, type(e).__name__, e))
        ok = False
    else:
        print('%-24s %s' % (name, 'OK' if ok else 'FAIL'))
    results.append((name, ok))


# 1. object macro -----------------------------------------------------------
def t_object():
    out = preprocess('#define N 42\nint x = N;\n')
    return squash(out) == 'int x = 42 ;'


# 2. object macro with parenthesized body (space before '(' must NOT make it
#    function-like) ---------------------------------------------------------
def t_object_paren():
    out = preprocess('#define A 1\n#define B (A+1)\nint x = B;\n')
    return squash(out) == 'int x = ( 1 + 1 ) ;'


# 3. function-like macro ----------------------------------------------------
def t_function():
    out = preprocess('#define ADD(a,b) ((a)+(b))\nint x = ADD(1,2);\n')
    return squash(out) == 'int x = ( ( 1 ) + ( 2 ) ) ;'


# 4. function macro args containing commas inside nested parens -------------
def t_fn_nested_comma():
    out = preprocess('#define F(a,b) a-b\nint x = F(g(1,2),3);\n')
    return squash(out) == 'int x = g ( 1 , 2 ) - 3 ;'


# 5. token paste ## with parameter ------------------------------------------
def t_paste_param():
    out = preprocess('#define CAT(a,b) a ## b\nint x = CAT(foo,bar);\n')
    return squash(out) == 'int x = foobar ;'


# 6. token paste ## with bare literal ---------------------------------------
def t_paste_literal():
    out = preprocess('#define SUF(x) x ## _t\nint x = SUF(my);\n')
    return squash(out) == 'int x = my_t ;'


# 7. stringize # ------------------------------------------------------------
def t_stringize():
    out = preprocess('#define S(x) #x\nchar *p = S(hello);\n')
    return '"hello"' in out


# 8. #ifdef / #ifndef / #else / #endif --------------------------------------
def t_ifdef():
    src = ('#define ON\n'
           '#ifdef ON\nint a = 1;\n#else\nint a = 2;\n#endif\n'
           '#ifndef OFF\nint b = 3;\n#endif\n')
    out = squash(preprocess(src))
    return out == 'int a = 1 ; int b = 3 ;'


# 9. #if numeric + defined() ------------------------------------------------
def t_if_numeric():
    src = ('#define V 3\n'
           '#if V > 2\nint a = 1;\n#else\nint a = 0;\n#endif\n'
           '#if defined(V) && V == 3\nint b = 1;\n#endif\n'
           '#if defined(NOPE)\nint c = 1;\n#endif\n')
    out = squash(preprocess(src))
    return out == 'int a = 1 ; int b = 1 ;'


# 10. #elif chain -----------------------------------------------------------
def t_elif():
    src = ('#define V 2\n'
           '#if V == 1\nint a = 1;\n'
           '#elif V == 2\nint a = 2;\n'
           '#elif V == 3\nint a = 3;\n'
           '#else\nint a = 9;\n#endif\n')
    return squash(preprocess(src)) == 'int a = 2 ;'


# 11. #undef ---------------------------------------------------------------
def t_undef():
    src = '#define X 1\n#undef X\n#ifdef X\nint a = 1;\n#else\nint a = 0;\n#endif\n'
    return squash(preprocess(src)) == 'int a = 0 ;'


# 12. #include with relative directory + include_paths ---------------------
def t_include():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, 'hdr.h'), 'w') as f:
        f.write('#define FROM_HDR 7\n')
    main = os.path.join(d, 'main.c')
    with open(main, 'w') as f:
        f.write('#include "hdr.h"\nint x = FROM_HDR;\n')
    out = squash(preprocess(open(main).read(), cur_file=main, include_paths=[d]))
    return out == 'int x = 7 ;'


# 13. nested macro expansion ----------------------------------------------
def t_nested():
    src = '#define A B\n#define B C\n#define C 9\nint x = A;\n'
    return squash(preprocess(src)) == 'int x = 9 ;'


# 14. multi-line macro (backslash continuation) ---------------------------
def t_multiline():
    src = '#define M(a,b) \\\n  ((a) + \\\n   (b))\nint x = M(1,2);\n'
    return squash(preprocess(src)) == 'int x = ( ( 1 ) + ( 2 ) ) ;'


# 15. comment stripping --------------------------------------------------
def t_comments():
    src = ('/* block\n   comment */ int a = 1;\n'
           'int b = 2; // line comment\n')
    out = squash(preprocess(src))
    return out == 'int a = 1 ; int b = 2 ;'


# 16. #error raises ------------------------------------------------------
def t_error():
    try:
        preprocess('#if 1\n#error boom\n#endif\n')
    except PreprocError:
        return True
    return False


for nm, fn in [
    ('object_macro', t_object),
    ('object_paren_body', t_object_paren),
    ('function_macro', t_function),
    ('fn_nested_comma', t_fn_nested_comma),
    ('paste_param', t_paste_param),
    ('paste_literal', t_paste_literal),
    ('stringize', t_stringize),
    ('ifdef_ifndef', t_ifdef),
    ('if_numeric_defined', t_if_numeric),
    ('elif_chain', t_elif),
    ('undef', t_undef),
    ('include_relative', t_include),
    ('nested_expansion', t_nested),
    ('multiline_macro', t_multiline),
    ('comment_strip', t_comments),
    ('error_raises', t_error),
]:
    case(nm, fn)

passed = sum(1 for _, ok in results if ok)
total = len(results)
print('TOTAL: %d/%d %s' % (passed, total, 'ALL PASS' if passed == total else 'FAILURES'))
sys.exit(0 if passed == total else 1)
