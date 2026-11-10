#!/usr/bin/env python3
# struct / enum / typedef regression for OSCC.
import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

def run_c(src, checks, maxst=200000):
    toks = tokenize(src)
    p = Parser(toks)
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    words = cg.build()
    s = Sim(); s.load_words(words)
    n = s.run(max_steps=maxst)
    ok = True
    for nm, want in checks:
        ga = cg.a.globs['__g_' + nm][1]
        got = s.mem[ga]
        good = (got == want)
        ok = ok and good
        print('%-16s g=%-8d want %-8d %s' % (nm, got, want, 'OK' if good else 'FAIL'))
    print('  steps=%d halted=%s -> %s' % (n, s.halted, 'OK' if ok else 'FAIL'))
    return ok

results = []
# 1. basic typedef struct + enum
src1 = '''\
typedef struct { int x; int y; } Point;
typedef enum { RED=0, GREEN=1, BLUE=2 } Color;
Point p; int g; int main(){ p.x=42; p.y=7; g=p.x+p.y+GREEN; return 0; }
'''
results.append(('typedef_struct_enum', run_c(src1, [('g', 50)])))
# 2. zero-init + more fields
src2 = '''\
typedef struct { int a; int b; int c; } T;
T t; int g; int main(){ t.a=1; t.b=2; t.c=3; g=t.a*100+t.b*10+t.c; return 0; }
'''
results.append(('multi_field', run_c(src2, [('g', 123)])))
# 3. array of structs
src3 = '''\
typedef struct { int a; int b; } P;
P arr[3]; int g; int main(){ arr[0].a=10; arr[0].b=20; arr[1].a=30; arr[1].b=40; g=arr[0].a+arr[1].b; return 0; }
'''
results.append(('struct_array', run_c(src3, [('g', 50)])))
# 4. pointer to struct (->)
src4 = '''\
typedef struct { int a; int b; } P;
P arr[3]; P *pp; int g; int h; int main(){ pp=&arr[2]; pp->a=5; pp->b=6; h=pp->a+pp->b; g=pp->a; return 0; }
'''
results.append(('struct_ptr_arrow', run_c(src4, [('g', 5), ('h', 11)])))
# 5. nested struct
src5 = '''\
typedef struct { int a; int b; } Pair;
typedef struct { Pair inner; int c; } Outer;
Outer o; int g; int main(){ o.inner.a=3; o.inner.b=4; o.c=5; g=o.inner.a+o.inner.b+o.c; return 0; }
'''
results.append(('nested_struct', run_c(src5, [('g', 12)])))
# 6. enum auto-seq + expression init
src6 = '''\
enum { A, B, C=5, D, E };
int g; int main(){ g=D*10+E; return 0; }
'''
results.append(('enum_seq', run_c(src6, [('g', 67)])))

fails = [n for n, ok in results if not ok]
print('\nTOTAL: %d/%d  %s' % (len(results)-len(fails), len(results),
      'ALL PASS' if not fails else 'FAIL: %s' % fails))
sys.exit(1 if fails else 0)
