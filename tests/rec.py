import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

def run_c(name, src, checks, maxst=200000):
    try:
        toks = tokenize(src)
        p = Parser(toks)
        d = p.parse()
        cg = CodeGen(Asm())
        cg.compile(d)
        words = cg.build()
        s = Sim(); s.load_words(words)
        n = s.run(max_steps=maxst)
        parts = []
        ok = True
        for gl, want in checks:
            gaddr = cg.a.globs['__g_' + gl][1]
            got = s.mem[gaddr]
            good = (got & 0xffffffff) == (want & 0xffffffff)
            ok = ok and good
            parts.append('%s=%d(want %d)%s' % (gl, got, want, 'OK' if good else 'FAIL'))
        print('%-48s steps=%-6d %s -> %s' % (name, n, ' '.join(parts), 'OK' if ok else 'FAIL'))
        return ok
    except Exception as e:
        print('%-48s EXC %r -> FAIL' % (name, e))
        return False

results = []
# single recursion works (fact).  Test fib(1), fib(2), fib(3) small
results.append(run_c('fib(1)', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(1); return 0; }', [('g', 1)]))
results.append(run_c('fib(2)=1', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(2); return 0; }', [('g', 1)]))
results.append(run_c('fib(3)=2', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(3); return 0; }', [('g', 2)]))
results.append(run_c('fib(4)=3', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(4); return 0; }', [('g', 3)]))
results.append(run_c('fib(5)=5', 'int g; int fib(int n){ if(n<2) return n; return fib(n-1)+fib(n-2); } int main(){ g=fib(5); return 0; }', [('g', 5)]))
# plus simple a-b-c chain: g = (10-3)-2  vs  g = 10-3-2
results.append(run_c('g=10-3-2', 'int g; int main(){ g=10-3-2; return 0; }', [('g', 5)]))
results.append(run_c('g=100-50-30', 'int g; int main(){ g=100-50-30; return 0; }', [('g', 20)]))
print('TOTAL: %d/%d' % (sum(results), len(results)))