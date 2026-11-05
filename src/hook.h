/* Declaration for the DSP-write hook, force-included into the vendored
 * snes_spc sources so no vendored file is patched.
 *
 * snes_spc already provides the extension point: SNES_SPC::dsp_write calls
 * SPC_DSP_WRITE_HOOK( time, address, data ) when that macro is defined
 * (snes_spc/SNES_SPC.cpp, inside `dsp_write`). We define the macro on the
 * compiler command line to call the function below, and pass this header with
 * `-include` so the declaration is visible wherever the macro expands.
 *
 * Keeping the vendored tree byte-identical to upstream matters here: it is
 * LGPL-2.1, and an unmodified copy used through a documented hook is far
 * easier to reason about than a patched one.
 */
#ifndef SNESMDB_HOOK_H
#define SNESMDB_HOOK_H

#ifdef __cplusplus
extern "C" {
#endif

/* time is in SPC700 clocks (1.024 MHz); addr is a DSP register 0x00-0x7F. */
void snesmdb_log_dsp_write(long time, int addr, unsigned char data);

#ifdef __cplusplus
}
#endif

#endif
