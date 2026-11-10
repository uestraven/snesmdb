# Modifications to snes_spc

This directory is **Shay Green's (blargg's) snes_spc 0.9.0**, obtained from
<http://www.slack.net/~ant/libs/>. It is **not** SNES-MDB code and is **not**
covered by SNES-MDB's MIT license.

| | |
|---|---|
| Upstream author | Shay Green (blargg) |
| Upstream version | snes_spc 0.9.0 |
| License | **LGPL-2.1** (GNU Lesser General Public License, version 2.1) |
| License text | [`license.txt`](license.txt), also [`LICENSE`](LICENSE) |
| Upstream notices | [`readme.txt`](readme.txt), [`changes.txt`](changes.txt), [`snes_spc.txt`](snes_spc.txt) — all preserved unedited |
| Modified by | the SNES-MDB project, <https://github.com/uestraven/snesmdb> |
| Modified on | 2026-11-08 |
| Files changed | **one**: `snes_spc/SPC_DSP.cpp` |
| Change size | **42 lines added, 0 removed, 0 altered** |

LGPL-2.1 §2(a) requires a modified file to carry prominent notice that it
changed and when. `snes_spc/SPC_DSP.cpp` carries that notice in its header,
directly below the upstream copyright block, which is preserved intact.

## Why anything was changed at all

The production extractor needs no patch: snes_spc already provides an
extension point for DSP register writes (`SPC_DSP_WRITE_HOOK`, called from
`SNES_SPC::dsp_write`), which SNES-MDB enables from the compiler command
line. That is the mechanism upstream intended and it is used unmodified.

The research build needs three things upstream offers no extension point
for, because they are *internal pipeline instants* rather than register
writes. A register write says what the CPU asked for; these say what the DSP
actually did with it. The two differ, and the difference is the measurement:
a music driver can rewrite the sample directory between a key-on write and
the DSP's read of it, so resolving sample identity from the CPU write
resolves it against a table the hardware never used.

## The three modifications

All three are single macro invocations. Each expands to **nothing** unless
its macro is defined by the build, so the default build of this file is
functionally identical to upstream — verified by `make
verify-instrumentation`, which requires the instrumented and production
builds to produce bit-identical audio.

### 1. `SPC_DSP_SAMPLE_HOOK` — the sample start the DSP committed

**Site:** `SPC_DSP::voice_V3c`, at `if ( v->kon_delay == 5 )`, before
`v->brr_addr` is assigned.

Fires at the instant the DSP commits a voice's BRR start address, carrying
the directory address it read and both words of the entry. This is the only
point at which the entry the hardware *used* is observable; by the next
externally visible boundary the driver may have overwritten it.

### 2. `SPC_DSP_KON_HOOK` — key-on acceptance

**Site:** `SPC_DSP::run`, inside `if ( m.kon & v->vbit )`, before
`v->kon_delay = 5`.

A write to `$4C` only assigns `m.new_kon`; the DSP latches it here, later.
Observing the latch makes "the write was accepted before the commit" a
measurement rather than an inference from timestamps.

### 3. `SPC_DSP_LOOP_HOOK` — the loop destination actually taken

**Site:** `SPC_DSP::voice_V4` (BRR end block), before
`v->brr_addr = m.t_brr_next_addr`.

Reports the loop destination at the moment the DSP jumps to it, which is not
necessarily the directory's second word read at sample start — a driver can
rewrite the entry while the voice sustains. An *unobserved* loop means the
runtime destination was never established, and is published as unknown
rather than as a zero loop offset.

## The no-op defaults live outside this directory

The `#ifndef`/`#define` no-op fallbacks for all three macros are in
SNES-MDB's `src/hook.h`, force-included via `-include`, so that this
directory contains no SNES-MDB-authored code. A consequence worth stating
plainly: compiling `snes_spc/SPC_DSP.cpp` on its own, without those macros
defined, will not build. Either define them, or take
[`upstream/SPC_DSP.cpp`](upstream/SPC_DSP.cpp) instead.

## Verifying the change yourself

[`upstream/SPC_DSP.cpp`](upstream/SPC_DSP.cpp) is the **unmodified** snes_spc
0.9.0 file, kept in the repository so the modification is auditable offline
with no network access:

```
sha256  42a48152675eaa772f3bd534122fa71c3d6adec9566d9f5f63e53a556849ac22
```

```sh
make verify-vendor           # the full diff, upstream -> modified
make verify-instrumentation  # instrumented and production audio are identical
```

## Redistribution requirements

If you redistribute snes_spc, or a binary built from it, LGPL-2.1 applies to
that part of the work. Distributing this repository or a SNES-MDB release
satisfies it as follows:

| LGPL-2.1 requirement | How it is met |
|---|---|
| §1 — ship the license text with the source | `license.txt` and `LICENSE`, both unedited |
| §1 — keep copyright notices intact | The upstream block at the top of every vendored file is unchanged; the SNES-MDB notice is *added below* it, not in place of it |
| §2(a) — mark changed files and date them | Header notice in `snes_spc/SPC_DSP.cpp`; this document |
| §2 — the modified work stays LGPL-2.1 | It does. MIT is not asserted over this directory |
| §4/§5 — source availability for a distributed binary | Complete source is in this directory, including the unmodified original |
| §6 — relinking permitted for a combined work | Satisfied by shipping source; SNES-MDB builds snes_spc from source and distributes no prebuilt binary |

SNES-MDB uses snes_spc as a source-level component and never ships a compiled
artifact, so the §6 object-code provisions are not reached in practice.

LGPL-2.1 and MIT are compatible for this combination, and SNES-MDB's MIT
license does not extend to this directory. See [`../../RIGHTS.md`](../../RIGHTS.md).
