import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim

def run_c(src, glob, want, maxst=20000):
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
    print('%-40s g=%d want %d steps=%d halted=%s -> %s' % (
        glob, got, want, n, s.halted, 'OK' if got == want else 'FAIL'))
    return got == want

# g = 41 - 1  (uses sub)
run_c('int g; int main(){ g = 41 - 1; return 0; }', 'g', 40)
# g = 41 + 1  (uses add)
run_c('int g; int main(){ g = 41 + 1; return 0; }', 'g', 42)
# g = 41 + 1 + 1  (nested binary)
run_c('int g; int main(){ g = 41 + 1 + 1; return 0; }', 'g', 43)
# g = x - 1 where x global
run_c('int g; int x; int main(){ x = 41; g = x - 1; return 0; }', 'g', 40)
# g = x + 1 where x global
run_c('int g; int x; int main(){ x = 41; g = x + 1; return 0; }', 'g', 42)