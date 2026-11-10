/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/init.h for the OISC port (OSCC subset).
 *
 * __init/__initdata etc. are section annotations in upstream Linux.  OSCC
 * emits a flat SUBLEQ image with no section concept, so all annotations
 * expand to nothing here; the call sites keep the upstream shape for
 * readability and to ease a later switch to real sections.
 */
#ifndef _LINUX_INIT_H
#define _LINUX_INIT_H

#define __init
#define __initdata
#define __initconst
#define __ref
#define __read_mostly
#define __ro_after_init
#define __cold
#define __exit

#endif /* _LINUX_INIT_H */