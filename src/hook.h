/* Declaration for the DSP-write hook, force-included into the vendored
 * snes_spc sources so no vendored file is patched.
 *
 * snes_spc already provides the extension point: SNES_SPC::dsp_write calls
 * SPC_DSP_WRITE_HOOK( time, address, data ) when that macro is defined
 * (snes_spc/SNES_SPC.cpp, inside `dsp_write`). We define the macro on the
 * compiler command line to call the function below, and pass this header with
 * `-include` so the declaration is visible wherever the macro expands.
 *
 * Keeping the vendored tree byte-identical to upstream mattered here, and it
 * is no longer true: SPC_DSP.cpp carries THREE documented additions, for the
 * three macros defined below. It is LGPL-2.1, each change is marked in
 * place, the file carries a modified-file notice, and the full account is in
 * vendor/snes_spc/MODIFICATIONS.md. `make verify-vendor` shows the diff
 * against the unmodified upstream file kept at
 * vendor/snes_spc/upstream/SPC_DSP.cpp.
 *
 * The no-op fallbacks live HERE rather than in the vendored tree so that
 * directory contains no snesmdb-authored code.
 */
/* SECOND HOOK: the sample-directory entry the DSP actually consumed.
 *
 * Unlike the write hook, snes_spc provides no extension point here, so
 * SPC_DSP.cpp carries an addition inside voice_V3c -- a no-op unless the
 * macro is defined. It is needed because hooking the CPU's KON write
 * captures the
 * wrong instant: the DSP reads the directory during voice processing after a
 * key-on delay, and a driver can rewrite the table in between. Super
 * Turrican does exactly that, producing 2,952 directory states in one track
 * and leaving 30% of its notes with an entry that was valid at key-on and
 * invalid at the next observable boundary.
 */
#ifndef SPC_DSP_SAMPLE_HOOK
#define SPC_DSP_SAMPLE_HOOK( voice, dir_addr, start, loop )
#endif

/* The loop destination the DSP actually jumps to at a BRR end block, and the
 * instant it latches a key-on. Both no-ops unless defined. An unobserved
 * loop means the runtime destination was NOT established -- it must never be
 * read as a zero loop offset, which would fabricate an identity property. */
#ifndef SPC_DSP_LOOP_HOOK
#define SPC_DSP_LOOP_HOOK( voice, dest )
#endif
#ifndef SPC_DSP_KON_HOOK
#define SPC_DSP_KON_HOOK( voice )
#endif

#ifndef SNESMDB_HOOK_H
#define SNESMDB_HOOK_H

#ifdef __cplusplus
extern "C" {
#endif

/* time is in SPC700 clocks (1.024 MHz); addr is a DSP register 0x00-0x7F. */
void snesmdb_log_dsp_write(long time, int addr, unsigned char data);

/* Called when the DSP commits a voice's BRR start address. `dir_addr` is the
 * directory entry the DSP read, so the SRCN it used is recoverable as
 * (dir_addr - DIR*0x100) / 4 without trusting a pipelined register copy. */
void snesmdb_log_sample_start(int voice, int dir_addr, int start, int loop);
void snesmdb_log_loop_taken(int voice, int dest);
void snesmdb_log_kon_accepted(int voice);

#ifdef __cplusplus
}
#endif

#endif
