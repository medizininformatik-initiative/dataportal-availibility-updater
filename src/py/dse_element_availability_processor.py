#!/usr/bin/env python3
"""Process DSE element availability reports and annotate feature files with element counts."""

import argparse
import json
import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


def load_snapshots(snapshots_dir: Path) -> Tuple[Dict[str, dict], Dict[str, List[dict]]]:
    """Load StructureDefinition snapshots, indexed by name and by FHIR type."""
    by_name: Dict[str, dict] = {}
    by_type: Dict[str, List[dict]] = defaultdict(list)

    for f in snapshots_dir.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        name = data.get("name")
        typ = data.get("type")
        if name:
            by_name[name] = data
        if typ:
            by_type[typ].append(data)

    log.info("Loaded %d snapshots (%d unique types)", len(by_name), len(by_type))
    return by_name, by_type


def load_features(features_dir: Path) -> Dict[str, Tuple[dict, Path]]:
    """Load feature files, indexed by their URL."""
    features: Dict[str, Tuple[dict, Path]] = {}
    for f in features_dir.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        url = data.get("url")
        if url:
            features[url] = (data, f)

    log.info("Loaded %d features", len(features))
    return features


def _initial_population_count(stratum: dict) -> Optional[int]:
    for pop in stratum.get("population", []):
        code = pop.get("code", {}).get("coding", [{}])[0].get("code")
        if code == "initial-population":
            return pop.get("count")
    return None


BUCKETS = (0, 10, 100, 1_000, 10_000, 100_000, 1_000_000)


def _bucketize(value: int) -> int:
    return max(b for b in BUCKETS if value >= b)


def extract_element_counts(report: dict) -> Dict[Tuple[str, str], int]:
    """
    Walk the MeasureReport and return summed initial-population counts for every
    (profile_prefix, element_suffix) pair whose stratum value is 'true'.
    """
    counts: Dict[Tuple[str, str], int] = defaultdict(int)

    for group in report.get("group", []):
        for stratifier in group.get("stratifier", []):
            code_list = stratifier.get("code", [])
            if not code_list:
                continue
            strat_code = code_list[0]["coding"][0]["code"]
            dot_idx = strat_code.find(".")
            if dot_idx == -1:
                continue
            profile_prefix = strat_code[:dot_idx]
            element_suffix = strat_code[dot_idx + 1:]

            for stratum in stratifier.get("stratum", []):
                val_code = stratum.get("value", {}).get("coding", [{}])[0].get("code")
                if val_code != "true":
                    continue
                count = _initial_population_count(stratum)
                if count is not None:
                    counts[(profile_prefix, element_suffix)] += count

    return dict(counts)


def resolve_snapshot(
    profile_prefix: str,
    by_name: Dict[str, dict],
    by_type: Dict[str, List[dict]],
) -> Optional[dict]:
    """
    Return the snapshot that matches profile_prefix.
    Name match takes priority; falls back to FHIR type match when unambiguous.
    """
    if profile_prefix in by_name:
        return by_name[profile_prefix]

    type_matches = by_type.get(profile_prefix, [])
    if len(type_matches) == 1:
        return type_matches[0]
    if len(type_matches) > 1:
        log.warning("Ambiguous type match for '%s' (%d snapshots) — skipping", profile_prefix, len(type_matches))
    return None


def _annotate_fields(fields: list, element_id_to_count: Dict[str, int]) -> None:
    """Recursively add a bucketed 'count' key to every field whose id appears in the map."""
    for field in fields:
        field_id = field.get("id")
        if field_id and field_id in element_id_to_count:
            field["count"] = _bucketize(element_id_to_count[field_id])
        _annotate_fields(field.get("children", []), element_id_to_count)


def process(
    reports_dir: Path,
    snapshots_dir: Path,
    features_dir: Path,
    output_dir: Path,
) -> None:
    report_files = sorted(reports_dir.glob("*.json"))
    log.info("Found %d report file(s) in %s", len(report_files), reports_dir)

    by_name, by_type = load_snapshots(snapshots_dir)
    features = load_features(features_dir)

    # Accumulate counts across all reports before resolving snapshots
    combined_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for report_path in report_files:
        log.info("Processing report %s", report_path.name)
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        for key, count in extract_element_counts(report).items():
            combined_counts[key] += count

    raw_counts = dict(combined_counts)
    log.info("Extracted %d (profile_prefix, element_suffix) count entries across all reports", len(raw_counts))

    # Group counts by snapshot URL: snapshot_url -> {full_element_id: count}
    per_snapshot: Dict[str, Dict[str, int]] = defaultdict(dict)

    for (profile_prefix, element_suffix), count in raw_counts.items():
        snapshot = resolve_snapshot(profile_prefix, by_name, by_type)
        if snapshot is None:
            log.debug("No snapshot for prefix '%s' — skipping", profile_prefix)
            continue

        snapshot_url = snapshot.get("url")
        resource_type = snapshot.get("type")
        full_id = f"{resource_type}.{element_suffix}"

        existing = per_snapshot[snapshot_url].get(full_id)
        if existing is not None and existing != count:
            log.warning(
                "Count conflict for element '%s' in snapshot '%s': %d vs %d — using max",
                full_id, snapshot_url, existing, count,
            )
            count = max(existing, count)
        per_snapshot[snapshot_url][full_id] = count

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for snapshot_url, element_id_counts in per_snapshot.items():
        if snapshot_url not in features:
            log.debug("No feature for snapshot URL '%s' — skipping", snapshot_url)
            continue

        feature_data, feature_file = features[snapshot_url]
        output_feature = deepcopy(feature_data)
        _annotate_fields(output_feature.get("fields", []), element_id_counts)

        out_file = output_dir / feature_file.name
        out_file.write_text(json.dumps(output_feature, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Written %s", out_file)
        written += 1

    log.info("Done — %d feature file(s) annotated", written)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Annotate feature files with element-level availability counts from a DSE MeasureReport."
    )
    parser.add_argument("--reports-dir", required=True, type=Path, help="Directory containing DSE availability MeasureReport JSON files")
    parser.add_argument("--snapshots-dir", required=True, type=Path, help="Directory containing StructureDefinition snapshot JSONs")
    parser.add_argument("--features-dir", required=True, type=Path, help="Directory containing feature JSON files")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory to write annotated feature files")
    parser.add_argument(
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.loglevel), format="%(asctime)s - %(levelname)s - %(message)s")
    process(args.reports_dir, args.snapshots_dir, args.features_dir, args.output_dir)


if __name__ == "__main__":
    main()
