/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/export.h for the OISC port (OSCC subset).
 *
 * The full kernel header generates a per-symbol ELF section entry; OSCC has
 * no ELF concept and our loader is flat SUBLEQ words, so the annotation
 * expands to nothing.  Keeping the call sites in the source preserves the
 * upstream shape for when a real module loader arrives.
 */
#ifndef _LINUX_EXPORT_H
#define _LINUX_EXPORT_H

#define EXPORT_SYMBOL(x)
#define EXPORT_SYMBOL_GPL(x)
#define EXPORT_SYMBOL_NS(x, ns)
#define EXPORT_SYMBOL_NS_GPL(x, ns)

#endif /* _LINUX_EXPORT_H */