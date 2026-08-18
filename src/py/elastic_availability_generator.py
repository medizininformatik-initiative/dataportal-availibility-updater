import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional

log = logging.getLogger(__name__)

PATIENT_STRAT_TO_TERMCODE: Dict[str, Dict[str, str]] = {
    "patient-gender": {
        "system": "http://snomed.info/sct",
        "code": "263495000",
    },
    "patient-birthdate-exists": {
        "system": "http://snomed.info/sct",
        "code": "424144002",
    },
}


class ElasticAvailabilityGenerator:
    """
    Generates Elasticsearch partial update files that contain availability buckets
    derived from availability reports and ontology trees.
    """

    NAMESPACE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
    FILE_EXTENSION = ".json"
    MAX_FILESIZE_MB = 10

    def __init__(self, availability_input_dir: str, availability_output_dir: str, es_ontology_dir: str) -> None:
        self.input_dir = Path(availability_input_dir)
        self.output_dir = Path(availability_output_dir)
        self.ontology_dir = Path(es_ontology_dir)

        # Node data is split into two flat dicts instead of one dict-of-dicts:
        # the ontology export easily runs into the hundreds of thousands of
        # nodes, and each nested dict plus the unused per-child fields
        # (display text, terminology, ...) added multiple GB of avoidable
        # overhead. Only the child hash is ever read, so that's all we keep,
        # and IDs are interned so a hash shared between a node's key and
        # another node's children list is stored as a single string object.
        self.availability: Dict[str, int] = {}
        self.children: Dict[str, Optional[List[str]]] = {}

        mapping_file = self.input_dir / "stratum-to-context.json"
        self.stratum_to_context = json.loads(mapping_file.read_text(encoding="utf-8"))

    def _contextualized_hash(self, context: Dict[str, str], termcode: Dict[str, str]) -> str:
        """Create stable UUID3 hash for context + termcode combination."""
        raw = (
            f"{context.get('system')}{context.get('code')}{context.get('version', '')}"
            f"{termcode.get('system')}{termcode.get('code')}"
        )
        return str(uuid.uuid3(self.NAMESPACE_UUID, raw))

    def load_ontology_tree(self) -> None:
        """Loads ontology export (newline-delimited JSON)."""
        elastic_dir = self.ontology_dir / "elastic"
        intern = sys.intern

        for file in elastic_dir.glob("*onto_es__ontology*"):
            log.info("Loading ontology file %s", file)

            current_id = None
            for line in file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue

                obj = json.loads(line)

                if "index" in obj:
                    current_id = intern(obj["index"]["_id"])
                else:
                    self.availability[current_id] = 0
                    children = [intern(child["contextualized_termcode_hash"]) for child in obj.get("children", [])]
                    self.children[current_id] = children or None

        log.info("Loaded %d ontology nodes", len(self.availability))

    def _bucketize(self, value: int) -> int:
        buckets = (0, 10, 100, 1_000, 10_000, 100_000, 1_000_000)
        return max(b for b in buckets if value >= b)

    def _accumulate_availability(self, node_id: str, cache: Dict[str, int], in_progress: set = None) -> int:
        if node_id in cache:
            return cache[node_id]

        if in_progress is None:
            in_progress = set()

        total = self.availability[node_id]

        in_progress.add(node_id)
        for child_id in self.children[node_id] or ():
            if child_id not in self.availability:
                log.debug("Missing ontology node for child %s of %s", child_id, node_id)
                continue
            if child_id in in_progress:
                log.debug("Cycle detected: child %s of %s is already on the current path", child_id, node_id)
                continue
            total += self._accumulate_availability(child_id, cache, in_progress)
        in_progress.discard(node_id)

        cache[node_id] = total
        return total

    def _apply_measure(self, context: Dict[str, str], termcode: Dict[str, str], score: int) -> None:
        node_hash = self._contextualized_hash(context, termcode)

        if node_hash not in self.availability:
            log.debug("Missing ontology node for %s %s", context, termcode)
            return

        self.availability[node_hash] += score

    def update_from_reports(self) -> None:
        for file in self.input_dir.glob("*availability_report*"):
            log.info("Processing report %s", file)

            report = json.loads(file.read_text(encoding="utf-8"))

            for group in report.get("group", []):
                for stratifier in group.get("stratifier", []):
                    if "stratum" not in stratifier:
                        continue

                    strat_code = stratifier["code"][0]["coding"][0]["code"]

                    if strat_code not in self.stratum_to_context and strat_code not in PATIENT_STRAT_TO_TERMCODE:
                        log.debug("Skipping unknown stratifier %s", strat_code)
                        continue

                    context = self.stratum_to_context.get(strat_code)

                    if strat_code in PATIENT_STRAT_TO_TERMCODE:
                        termcode = PATIENT_STRAT_TO_TERMCODE[strat_code]
                        score = sum(s["measureScore"]["value"] for s in stratifier["stratum"])
                        self._apply_measure(context, termcode, score)
                        continue

                    for stratum in stratifier["stratum"]:
                        coding = stratum["value"]["coding"][0]

                        if "system" not in coding:
                            continue

                        termcode = {"system": coding["system"], "code": coding["code"]}
                        score = stratum["measureScore"]["value"]

                        self._apply_measure(context, termcode, score)

    def _write_chunked(self, records: Iterable[List[Dict[str, Any]]], prefix: str) -> None:

        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_index = 1
        current_size = 0
        max_bytes = self.MAX_FILESIZE_MB * 1024 * 1024

        fh = (self.output_dir / f"{prefix}_{file_index}{self.FILE_EXTENSION}").open("w", encoding="utf-8")

        for record in records:
            lines = [json.dumps(doc, ensure_ascii=False) + "\n" for doc in record]
            encoded = [line.encode("utf-8") for line in lines]
            record_size = sum(len(chunk) for chunk in encoded)

            if current_size > 0 and current_size + record_size > max_bytes:
                fh.close()
                file_index += 1
                fh = (self.output_dir / f"{prefix}_{file_index}{self.FILE_EXTENSION}").open("w", encoding="utf-8")
                current_size = 0

            for line in lines:
                fh.write(line)
            current_size += record_size

        fh.close()

    def _build_updates(self, cache: Dict[str, int]) -> Iterable[List[Dict[str, Any]]]:
        for node_id in self.availability:
            total = self._accumulate_availability(node_id, cache)
            bucket = self._bucketize(total)

            if total > 0:
                log.debug("Node %s → %d (bucket %d)", node_id, total, bucket)

            yield [{"update": {"_id": node_id}}, {"doc": {"availability": bucket}}]

    def generate(self) -> None:
        """Main pipeline."""
        self.load_ontology_tree()
        self.update_from_reports()

        # Records are streamed straight into _write_chunked rather than collected
        # into a list first: materializing all ~700k update/doc pairs up front
        # roughly doubled peak memory on top of the ontology tree itself.
        cache: Dict[str, int] = {}
        self._write_chunked(self._build_updates(cache), "es_availability_update")
