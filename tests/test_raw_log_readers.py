"""The raw log is not only register writes, and every reader must know it.

`spc_dump` emits `kind:"dir"` directory-snapshot records alongside register
writes -- 436 of them in a single 230-second Evermore track. Three separate
readers were written against the earlier assumption that every record is a
write, and each one raised `KeyError: 'addr'` on the first snapshot it met.

The failure mode is what makes this worth a test. It is not a wrong number;
it is a crash in `make corpus`, and it does not reproduce on the 22-game
baseline because those raw logs were captured before snapshots existed.
Re-extracting ANY game surfaces it. A reader that silently skipped the
records would be worse still, so these tests pin both halves: non-write
records are ignored, and the writes around them are still all processed.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import voices  # noqa: E402

DIR_RECORD = {"t": 65536, "kind": "dir", "page": 2, "bytes": "ff" * 1024}


def _writes_with_a_snapshot_in_the_middle():
    return [
        {"t": 100, "addr": 0x04, "reg": "SRCN", "data": 3},
        {"t": 200, "addr": 0x4C, "reg": "KON", "data": 0x01},
        DIR_RECORD,
        {"t": 900, "addr": 0x5C, "reg": "KOFF", "data": 0x01},
    ]


def test_extract_ignores_a_directory_snapshot_and_keeps_the_writes():
    out = voices.extract(iter(_writes_with_a_snapshot_in_the_middle()))
    assert len(out.notes) == 1, "the key-on/key-off pair must still be found"
    assert out.n_writes == 3, "the snapshot must not be counted as a write"


def test_extract_does_not_raise_on_a_log_of_only_snapshots():
    out = voices.extract(iter([DIR_RECORD, DIR_RECORD]))
    assert out.notes == [] and out.n_writes == 0


def test_extract_still_sees_registers_written_after_a_snapshot():
    """A snapshot must not terminate the replay, only be skipped. An early
    `return`/`break` here would silently truncate every track."""
    writes = [
        DIR_RECORD,
        {"t": 100, "addr": 0x04, "reg": "SRCN", "data": 7},
        DIR_RECORD,
        {"t": 200, "addr": 0x4C, "reg": "KON", "data": 0x01},
        {"t": 900, "addr": 0x5C, "reg": "KOFF", "data": 0x01},
    ]
    out = voices.extract(iter(writes))
    assert len(out.notes) == 1
    assert out.notes[0].srcn == 7, "a write after a snapshot was lost"


def test_the_performance_reader_tolerates_snapshots(tmp_path):
    """`echo_and_modulation` reads the raw log directly rather than through
    `voices`, so it needs its own guard -- it had none, and took the whole
    performance step down with KeyError on re-extraction."""
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "perf_mod", ROOT / "tools" / "performance.py")
    perf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(perf)

    log = tmp_path / "raw.jsonl.gz"
    with gzip.open(log, "wt") as handle:
        for record in (
            {"t": 10, "addr": perf.REG_EON, "data": 0x03},
            DIR_RECORD,
            {"t": 20, "addr": perf.REG_NON, "data": 0x01},
        ):
            handle.write(json.dumps(record) + "\n")

    got = perf.echo_and_modulation(log)
    assert got is not None, "a snapshot must not make the reader give up"
