import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

def run_c(name, src, glob, want, maxst=200000):
    try:
        toks = tokenize(src)
        p = Parser(toks)
        d = p.parse()
        cg = CodeGen(Asm())
        cg.compile(d)
        words = cg.build()
        s = Sim(); s.load_words(words)
        gaddr = cg.a.globs['__g_' + glob][1]
        n = s.run(max_steps=maxst)
        got = s.mem[gaddr]
        # signed-aware compare: SUNDEQ stores 32-bit words; compare against
        # the want value's bit pattern so negative expectations work.
        want_w = want & 0xffffffff
        got_s = got if got < 0x80000000 else got - 0x100000000
        ok = (got & 0xffffffff) == want_w
        print('%-42s g=%d(0x%x) want %d(0x%x) steps=%d halted=%s -> %s' % (
            name, got_s, got & 0xffffffff, want, want_w, n, s.halted,
            'OK' if ok else 'FAIL'))
        return ok
    except Exception as e:
        print('%-42s EXC %r -> FAIL' % (name, e))
        return False

results = []

# --- control flow ---
results.append(run_c('if true', 'int g; int main(){ int a; a=1; if(a) g=7; else g=9; return 0; }', 'g', 7))
results.append(run_c('if false', 'int g; int main(){ int a; a=0; if(a) g=7; else g=9; return 0; }', 'g', 9))
results.append(run_c('while loop', 'int g; int i; int main(){ i=3; g=0; while(i>0){ g=g+2; i=i-1; } return 0; }', 'g', 6))
results.append(run_c('for loop', 'int g; int i; int main(){ g=0; for(i=0;i<5;i=i+1) g=g+i; return 0; }', 'g', 10))
results.append(run_c('nested if/else chain', 'int g; int a; int main(){ a=2; if(a==0) g=10; else if(a==1) g=20; else if(a==2) g=30; else g=40; return 0; }', 'g', 30))
results.append(run_c('do while', 'int g; int i; int main(){ g=0; i=0; do { g=g+1; i=i+1; } while(i<5); return 0; }', 'g', 5))
results.append(run_c('do while runs once', 'int g; int i; int main(){ g=0; i=9; do { g=g+1; i=i+1; } while(i<5); return 0; }', 'g', 1))
# --- bitwise ops ---
results.append(run_c('bitwise and', 'int g; int main(){ g=0xF0 & 0x3C; return 0; }', 'g', 48))
results.append(run_c('bitwise and ones', 'int g; int a; int b; int main(){ a=5; b=3; g=a & b; return 0; }', 'g', 1))

# --- function calls ---
results.append(run_c('2-arg sum', 'int g; int add2(int a,int b){ return a+b; } int main(){ g=add2(30,12); return 0; }', 'g', 42))
results.append(run_c('nested calls', 'int g; int f1(int a){ return a*2; } int f2(int a){ return a+10; } int main(){ g=f2(f1(16)); return 0; }', 'g', 42))
results.append(run_c('factorial rec', 'int g; int fact(int n){ if(n<=1) return 1; return n*fact(n-1); } int main(){ g=fact(5); return 0; }', 'g', 120))
results.append(run_c('fib recursive', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(8); return 0; }', 'g', 21))

# --- arrays / pointers ---
results.append(run_c('array store/load', 'int g; int a[4]; int main(){ a[0]=40; a[1]=2; g=a[0]+a[1]; return 0; }', 'g', 42))
results.append(run_c('array index var', 'int g; int a[4]; int i; int main(){ a[0]=1; a[1]=41; i=1; g=a[i]; return 0; }', 'g', 41))
results.append(run_c('pointer deref', 'int g; int x; int *p; int main(){ x=42; p=&x; g=*p; return 0; }', 'g', 42))

# --- comparisons / logic ---
results.append(run_c('logical and', 'int g; int a; int b; int main(){ a=1; b=1; g=(a && b); return 0; }', 'g', 1))
results.append(run_c('logical or', 'int g; int a; int b; int main(){ a=0; b=1; g=(a || b); return 0; }', 'g', 1))
results.append(run_c('modulo', 'int g; int main(){ g=17 % 5; return 0; }', 'g', 2))
results.append(run_c('neg const', 'int g; int main(){ g=-7; return 0; }', 'g', -7))
results.append(run_c('shl', 'int g; int main(){ g=1 << 5; return 0; }', 'g', 32))

print()
print('TOTAL: %d/%d PASS' % (sum(results), len(results)))