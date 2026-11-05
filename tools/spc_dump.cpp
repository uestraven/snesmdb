/* spc_dump -- log every DSP register write an SPC performs, with timestamps.
 *
 *   spc_dump <in.spc> <out.jsonl> [seconds] [--wav out.wav] [--aram out.bin]
 *
 * This is deliberately a DUMB tool. It emits the raw write stream and nothing
 * else: no note detection, no pitch conversion, no grid inference. All of that
 * is semantics, it will change many times, and it belongs in Python where it
 * is cheap to iterate and test. What cannot be done in Python is running the
 * SPC700, so that is all this does.
 *
 * Why writes rather than DSP state: the driver's register writes ARE the
 * score. Polling voice state at the output rate would miss a KON that is set
 * and cleared between samples, and would confuse the driver's intent with the
 * DSP's envelope machinery.
 *
 * `--aram` dumps the 64K at the end of the run, which carries the BRR sample
 * directory and the samples themselves -- needed later to recover each
 * sample's fundamental, and free to capture now.
 */

#include "SNES_SPC.h"
#include "hook.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

FILE* g_log = nullptr;
long g_writes = 0;

/* Absolute-time base, in SPC700 clocks.
 *
 * The hook receives `m.spc_time + time`, which is relative to the START OF
 * THE CURRENT play() CALL, not to the beginning of the song. Logging it raw
 * produced timestamps that ran backwards across chunk boundaries -- a KOFF at
 * 37 ms followed by the next write at 25 ms -- which would have silently
 * corrupted every duration and interval derived downstream. The emulator
 * advances 32 clocks per output frame (1.024 MHz / 32 kHz), so the base grows
 * by 32 per frame rendered.
 */
long g_time_base = 0;
const long CLOCKS_PER_FRAME = 32;

/* DSP register names, for a log a human can read without a lookup table. */
const char* reg_name(int addr) {
    const int low = addr & 0x0F;
    if (low <= 0x07) {
        static const char* per_voice[8] = {
            "VOLL", "VOLR", "PITCHL", "PITCHH", "SRCN", "ADSR1", "ADSR2", "GAIN",
        };
        return per_voice[low];
    }
    if (low == 0x08) return "ENVX";
    if (low == 0x09) return "OUTX";
    if (low == 0x0F) return "FIR";
    switch (addr) {
        case 0x0C: return "MVOLL";
        case 0x1C: return "MVOLR";
        case 0x2C: return "EVOLL";
        case 0x3C: return "EVOLR";
        case 0x4C: return "KON";
        case 0x5C: return "KOFF";
        case 0x6C: return "FLG";
        case 0x7C: return "ENDX";
        case 0x0D: return "EFB";
        case 0x2D: return "PMON";
        case 0x3D: return "NON";
        case 0x4D: return "EON";
        case 0x5D: return "DIR";
        case 0x6D: return "ESA";
        case 0x7D: return "EDL";
        default: return "?";
    }
}

}  // namespace

extern "C" void snesmdb_log_dsp_write(long time, int addr, unsigned char data) {
    if (!g_log) return;
    const int low = addr & 0x0F;
    const int voice = (low <= 0x09) ? (addr >> 4) : -1;
    fprintf(g_log,
            "{\"t\":%ld,\"addr\":%d,\"reg\":\"%s\",\"voice\":%d,\"data\":%u}\n",
            g_time_base + time, addr, reg_name(addr), voice, (unsigned)data);
    ++g_writes;
}

static std::vector<unsigned char> read_file(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "spc_dump: cannot open %s\n", path);
        exit(1);
    }
    std::vector<unsigned char> out;
    unsigned char buf[8192];
    size_t got;
    while ((got = fread(buf, 1, sizeof buf, f)) > 0) out.insert(out.end(), buf, buf + got);
    fclose(f);
    return out;
}

static void write_wav(const char* path, const std::vector<short>& pcm, int rate) {
    FILE* f = fopen(path, "wb");
    if (!f) return;
    const unsigned data_bytes = (unsigned)(pcm.size() * 2);
    const unsigned chunk = 36 + data_bytes;
    const unsigned byte_rate = (unsigned)rate * 2 * 2;
    fwrite("RIFF", 1, 4, f);
    fwrite(&chunk, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f);
    const unsigned fmt_size = 16;
    const unsigned short pcm_tag = 1, channels = 2, bits = 16, align = 4;
    const unsigned srate = (unsigned)rate;
    fwrite(&fmt_size, 4, 1, f);
    fwrite(&pcm_tag, 2, 1, f);
    fwrite(&channels, 2, 1, f);
    fwrite(&srate, 4, 1, f);
    fwrite(&byte_rate, 4, 1, f);
    fwrite(&align, 2, 1, f);
    fwrite(&bits, 2, 1, f);
    fwrite("data", 1, 4, f);
    fwrite(&data_bytes, 4, 1, f);
    fwrite(pcm.data(), 2, pcm.size(), f);
    fclose(f);
}

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr,
                "usage: %s <in.spc> <out.jsonl> [seconds] "
                "[--wav out.wav] [--aram out.bin]\n",
                argv[0]);
        return 2;
    }
    const char* spc_path = argv[1];
    const char* log_path = argv[2];
    double seconds = (argc > 3 && argv[3][0] != '-') ? atof(argv[3]) : 10.0;
    const char* wav_path = nullptr;
    const char* aram_path = nullptr;
    for (int i = 3; i < argc; ++i) {
        if (!strcmp(argv[i], "--wav") && i + 1 < argc) wav_path = argv[++i];
        else if (!strcmp(argv[i], "--aram") && i + 1 < argc) aram_path = argv[++i];
    }

    std::vector<unsigned char> spc = read_file(spc_path);

    SNES_SPC* apu = new SNES_SPC;
    if (const char* err = apu->init()) {
        fprintf(stderr, "spc_dump: init failed: %s\n", err);
        return 1;
    }
    if (const char* err = apu->load_spc(spc.data(), (long)spc.size())) {
        fprintf(stderr, "spc_dump: load_spc failed: %s\n", err);
        return 1;
    }
    apu->clear_echo();

    g_log = fopen(log_path, "wb");
    if (!g_log) {
        fprintf(stderr, "spc_dump: cannot write %s\n", log_path);
        return 1;
    }

    const int rate = 32000;
    const long frames = (long)(seconds * rate);
    std::vector<short> pcm;
    pcm.reserve((size_t)frames * 2);

    // Play in chunks so the write hook fires interleaved with audio, exactly
    // as it would during real playback.
    const int chunk_frames = 2048;
    std::vector<short> buf((size_t)chunk_frames * 2);
    for (long done = 0; done < frames; done += chunk_frames) {
        const int want = (int)((frames - done < chunk_frames) ? (frames - done) : chunk_frames);
        if (const char* err = apu->play(want * 2, buf.data())) {
            fprintf(stderr, "spc_dump: play failed: %s\n", err);
            break;
        }
        if (wav_path) pcm.insert(pcm.end(), buf.begin(), buf.begin() + (size_t)want * 2);
        g_time_base += (long)want * CLOCKS_PER_FRAME;
    }

    fclose(g_log);
    g_log = nullptr;

    if (wav_path) write_wav(wav_path, pcm, rate);

    if (aram_path) {
        // `save_spc` is the supported way to reach ARAM without touching the
        // vendored internals: it writes a complete SPC image, in which the 64K
        // of ARAM sits at offset 0x100 by the file format's definition.
        std::vector<unsigned char> image(SNES_SPC::spc_file_size);
        apu->save_spc(image.data());
        FILE* a = fopen(aram_path, "wb");
        if (a) {
            fwrite(image.data() + 0x100, 1, 0x10000, a);
            fclose(a);
        }
    }

    fprintf(stderr, "spc_dump: %ld writes over %.2fs from %s\n",
            g_writes, seconds, spc_path);
    delete apu;
    return 0;
}
