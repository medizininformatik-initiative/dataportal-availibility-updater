import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Any, Iterable

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

        self.es_tree: Dict[str, Dict[str, Any]] = {}

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

        for file in elastic_dir.glob("*onto_es__ontology*"):
            log.info("Loading ontology file %s", file)

            current_id = None
            for line in file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue

                obj = json.loads(line)

                if "index" in obj:
                    current_id = obj["index"]["_id"]
                else:
                    self.es_tree[current_id] = {
                        "availability": 0,
                        "children": obj.get("children", []),
                    }

        log.info("Loaded %d ontology nodes", len(self.es_tree))

    def _bucketize(self, value: int) -> int:
        buckets = (0, 10, 100, 1_000, 10_000, 100_000, 1_000_000)
        return max(b for b in buckets if value >= b)

    def _accumulate_availability(self, node_id: str, cache: Dict[str, int]) -> int:
        if node_id in cache:
            return cache[node_id]

        node = self.es_tree[node_id]
        total = node["availability"]

        for child in node["children"]:
            total += self._accumulate_availability(child["contextualized_termcode_hash"], cache)

        cache[node_id] = total
        return total

    def _apply_measure(self, context: Dict[str, str], termcode: Dict[str, str], score: int) -> None:
        node_hash = self._contextualized_hash(context, termcode)

        if node_hash not in self.es_tree:
            log.debug("Missing ontology node for %s %s", context, termcode)
            return

        self.es_tree[node_hash]["availability"] += score

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

    def _write_chunked(self, docs: Iterable[Dict[str, Any]], prefix: str) -> None:

        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_index = 1
        current_size = 0
        max_bytes = self.MAX_FILESIZE_MB * 1024 * 1024

        fh = (self.output_dir / f"{prefix}_{file_index}{self.FILE_EXTENSION}").open("w", encoding="utf-8")

        for doc in docs:
            line = json.dumps(doc, ensure_ascii=False) + "\n"
            encoded = line.encode("utf-8")

            if current_size + len(encoded) > max_bytes:
                fh.close()
                file_index += 1
                fh = (self.output_dir / f"{prefix}_{file_index}{self.FILE_EXTENSION}").open("w", encoding="utf-8")
                current_size = 0

            fh.write(line)
            current_size += len(encoded)

        fh.close()

    def generate(self) -> None:
        """Main pipeline."""
        self.load_ontology_tree()
        self.update_from_reports()

        cache: Dict[str, int] = {}
        updates = []

        for node_id in self.es_tree:
            total = self._accumulate_availability(node_id, cache)
            bucket = self._bucketize(total)

            if total > 0:
                log.debug("Node %s → %d (bucket %d)", node_id, total, bucket)

            updates.append({"update": {"_id": node_id}})
            updates.append({"doc": {"availability": bucket}})

        self._write_chunked(updates, "es_availability_update")
