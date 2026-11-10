#!/bin/sh
# OSCC full regression runner.  Usage: ./tests/run_all.sh
cd "$(dirname "$0")/.." || exit 1

fail=0
for t in mic arr rec suite neg struct_test preproc_test e2e_test kernel_test boot_test mm_test; do
    printf '%-14s ' "$t"
    if timeout 600 python3 "tests/$t.py" >"/tmp/reg_$t.log" 2>&1; then
        echo "PASS"
    else
        echo "FAIL"
        tail -5 "/tmp/reg_$t.log"
        fail=1
    fi
done

if [ "$fail" -eq 0 ]; then
    echo "=== ALL SUITES PASS ==="
else
    echo "=== FAILURES PRESENT ==="
fi
exit "$fail"