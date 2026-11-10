# oisk

OISC（SUBLEQ）单指令集架构的内核骨架与自研 C 工具链。

## 项目组成

- `oscc.py` — OISC 的 C 子集编译器（预处理/struct/数组/指针/宏）
- `osma.py` — SUBLEQ 汇编器/符号表
- `preproc.py` — C 预处理器
- `sim.py` — OISC 模拟器（含 MMIO UART/时钟/中断）
- `oishw.py` — 硬件视图定义
- `kernel/arch/oisc/*` — OISC 内核骨架
  - `kernel/setup.c` / `start_kernel.c` — 启动路径
  - `lib/memcpy.c` / `delay.c` — 基础库
  - `mm/alloc.c` — free-list 物理页分配器
  - `include/asm/` — 体系结构头文件
- `kernel_port/` — Linux 内核文件移植骨架（头文件桥接）
- `tests/` — 回归测试套件（`tests/run_all.sh` 一键全跑）

## 快速开始

```sh
# 编译启动镜像
python3 oscc.py -Ikernel/arch/oisc/include kernel/t_boot.c /tmp/kernel.bin

# 模拟运行
python3 sim.py /tmp/kernel.bin

# 回归测试
./tests/run_all.sh
```

## 特性

- SUBLEQ 是唯一原生指令：`mem[b] -= mem[a]; if (mem[b] <= 0) goto c`
- OSCC 编译 OISC 的 C 子集到 SUBLEQ 自修改代码
- 内核可启动：打印内存/横幅后进入 idle 循环
- free-list 物理页分配器（避免位图，因 OSCC 无位或指令）

## License

GPL-2.0-only

本项目包含从 Linux 内核移植/改编的头文件与代码
（`kernel_port/include/linux/*`、`kernel_port/include/asm/*`、`kernel_port/lib/delay.c` 等），
这些文件保持 Linux 内核的 GPL-2.0-only 许可。其余自研代码（工具链 oscc/osma/sim、
内核 arch/oisc 等）同样以 GPL-2.0-only 授权，与 Linux 内核许可证保持一致。

参见 [LICENSE](LICENSE)。