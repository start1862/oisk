import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

def run_c(name, src, checks):
    try:
        toks = tokenize(src)
        p = Parser(toks)
        d = p.parse()
        cg = CodeGen(Asm())
        cg.compile(d)
        words = cg.build()
        s = Sim(); s.load_words(words)
        n = s.run(max_steps=50000)
        parts = []
        ok = True
        for gl, want in checks:
            gaddr = cg.a.globs['__g_' + gl][1]
            got = s.mem[gaddr]
            good = got == want
            ok = ok and good
            parts.append('%s=%d(want %d)%s' % (gl, got, want, 'OK' if good else 'FAIL'))
        print('%-46s steps=%-5d %s -> %s' % (name, n, ' '.join(parts), 'OK' if ok else 'FAIL'))
        return ok
    except Exception as e:
        print('%-46s EXC %r -> FAIL' % (name, e))
        return False

results = []
results.append(run_c('a[0]=42; g=a[0]', 'int g; int a[2]; int main(){ a[0]=42; g=a[0]; return 0; }', [('g', 42)]))
results.append(run_c('a[1]=42; g=a[1]', 'int g; int a[2]; int main(){ a[1]=42; g=a[1]; return 0; }', [('g', 42)]))
results.append(run_c('a[0]=40;a[1]=2;g=a[0]+a[1]', 'int g; int a[2]; int main(){ a[0]=40; a[1]=2; g=a[0]+a[1]; return 0; }', [('g', 42)]))
results.append(run_c('index var', 'int g; int a[2]; int i; int main(){ i=1; a[i]=42; g=a[i]; return 0; }', [('g', 42)]))
print('TOTAL: %d/%d' % (sum(results), len(results)))