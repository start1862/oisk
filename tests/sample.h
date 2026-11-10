/* sample kernel-style header */
#ifndef _SAMPLE_H
#define _SAMPLE_H

#define BASE 100
#define WRAP(n) ((n) * (n))

typedef struct { int x; int y; } Pt;
typedef enum { MODE_A = 0, MODE_B = 1 } Mode;

#endif /* _SAMPLE_H */