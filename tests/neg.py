import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

# signed-aware compare: both are 32-bit words; compare bit patterns AND
# interpret as signed for the user-visible check.
def run_c(name, src, checks, maxst=300000):
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
            got_w = s.mem[gaddr]
            want_w = want & 0xffffffff
            same = got_w == want_w
            ok = ok and same
            got_s = got_w if got_w < 0x80000000 else got_w - 0x100000000
            parts.append('%s=%d(0x%x want 0x%x int%d)%s' % (
                gl, got_s, got_w, want_w, want, 'OK' if same else 'FAIL'))
        print('%-56s g[%s] %s' % (name, parts[0] if parts else '', 'OK' if ok else 'FAIL'))
        return ok
    except Exception as e:
        print('%-56s EXC %r -> FAIL' % (name, e))
        return False

results = []
# neg constants of all kinds
results.append(run_c('g=-7', 'int g; int main(){ g=-7; return 0; }', [('g', -7)]))
results.append(run_c('g=-1', 'int g; int main(){ g=-1; return 0; }', [('g', -1)]))
results.append(run_c('g=0-7', 'int g; int main(){ g=0-7; return 0; }', [('g', -7)]))
results.append(run_c('g=-(-7)', 'int g; int main(){ g=-(-7); return 0; }', [('g', 7)]))
# signed arithmetic
results.append(run_c('g=-3+10', 'int g; int main(){ g=-3+10; return 0; }', [('g', 7)]))
results.append(run_c('g=-7*0', 'int g; int main(){ g=-7*0; return 0; }', [('g', 0)]))
results.append(run_c('g=-10/3', 'int g; int main(){ g=-10/3; return 0; }', [('g', -3)]))
results.append(run_c('g=-10%3', 'int g; int main(){ g=-10%3; return 0; }', [('g', -1)]))
# nested
results.append(run_c('g=-(5+7)', 'int g; int main(){ g=-(5+7); return 0; }', [('g', -12)]))
results.append(run_c('g=10--3', 'int g; int main(){ g=10--3; return 0; }', [('g', 13)]))
print('TOTAL: %d/%d' % (sum(results), len(results)))