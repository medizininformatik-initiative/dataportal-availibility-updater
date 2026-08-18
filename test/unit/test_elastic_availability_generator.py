import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "py"))

from elastic_availability_generator import ElasticAvailabilityGenerator


def make_generator(output_dir: Path, max_filesize_mb: float) -> ElasticAvailabilityGenerator:
    gen = object.__new__(ElasticAvailabilityGenerator)
    gen.output_dir = output_dir
    gen.MAX_FILESIZE_MB = max_filesize_mb
    return gen


def read_ndjson(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_write_chunked_writes_all_records_in_one_file_when_under_limit(tmp_path):
    gen = make_generator(tmp_path, max_filesize_mb=10)

    records = [
        [{"update": {"_id": "a"}}, {"doc": {"availability": 1}}],
        [{"update": {"_id": "b"}}, {"doc": {"availability": 2}}],
    ]

    gen._write_chunked(records, "es_availability_update")

    files = sorted(tmp_path.glob("es_availability_update_*.json"))
    assert len(files) == 1
    assert read_ndjson(files[0]) == [
        {"update": {"_id": "a"}}, {"doc": {"availability": 1}},
        {"update": {"_id": "b"}}, {"doc": {"availability": 2}},
    ]


def test_write_chunked_never_splits_an_update_doc_pair_across_files(tmp_path):
    # A tiny size limit forces a chunk boundary between almost every record,
    # which used to split the "update" line from its "doc" line into
    # separate files and produce invalid Elasticsearch bulk requests.
    gen = make_generator(tmp_path, max_filesize_mb=0.0002)

    records = [
        [{"update": {"_id": f"id-{i}"}}, {"doc": {"availability": i}}]
        for i in range(50)
    ]

    gen._write_chunked(records, "es_availability_update")

    files = sorted(tmp_path.glob("es_availability_update_*.json"))
    assert len(files) > 1

    all_lines = []
    for file in files:
        lines = read_ndjson(file)
        assert len(lines) % 2 == 0, f"{file.name} ends mid-record"
        for i in range(0, len(lines), 2):
            assert "update" in lines[i], f"{file.name} line {i} is not an 'update' entry"
            assert "doc" in lines[i + 1], f"{file.name} line {i + 1} is not the matching 'doc' entry"
        all_lines.extend(lines)

    assert len(all_lines) == 100
