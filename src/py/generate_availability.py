import argparse
import json
import logging
import zipfile
from pathlib import Path
from typing import List, Optional
import io
from requests.auth import HTTPBasicAuth
import tempfile
import certifi

import requests

from elastic_availability_generator import ElasticAvailabilityGenerator

log = logging.getLogger(__name__)

PROJECT_IDENTIFIER_SYSTEM = "http://medizininformatik-initiative.de/sid/project-identifier"


def get_combined_ca_bundle(custom_ca_path: Optional[str] = None) -> Optional[str]:
    """
    Return a CA bundle path that includes both system CAs and optional custom CA.
    """
    if not custom_ca_path:
        return True

    custom_path = Path(custom_ca_path)
    if not custom_path.is_file():
        raise ValueError(f"Custom CA file not found: {custom_ca_path}")

    system_cas = Path(certifi.where()).read_text()
    custom_cas = custom_path.read_text()

    tmp_bundle = tempfile.NamedTemporaryFile(mode="w+", delete=False)
    tmp_bundle.write(system_cas)
    tmp_bundle.write("\n")
    tmp_bundle.write(custom_cas)
    tmp_bundle.flush()
    tmp_bundle.close()

    return tmp_bundle.name


def get_oauth2_token(token_url: str, client_id: str, client_secret: str, scope: Optional[str] = None, ca_cert_path: Optional[str] = None) -> str:
    """
    Fetch an OAuth2 token using client credentials flow.
    """
    data = {"grant_type": "client_credentials"}
    if scope:
        data["scope"] = scope

    response = requests.post(token_url, data=data, auth=HTTPBasicAuth(client_id, client_secret), verify=ca_cert_path or True)
    response.raise_for_status()
    token_info = response.json()
    return token_info.get("access_token")


def configure_session(
    session: requests.Session,
    use_oauth2: bool = False,
    token_url: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    scope: Optional[str] = None,
    use_basic_auth: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None,
    ca_cert_path: Optional[str] = None
):

    ca_bundle = get_combined_ca_bundle(ca_cert_path)

    session.verify = ca_bundle

    if use_oauth2:
        if not all([token_url, client_id, client_secret]):
            raise ValueError("token_url, client_id, client_secret required for OAuth2")
        token = get_oauth2_token(token_url, client_id, client_secret, scope, ca_cert_path=ca_cert_path)
        session.headers.update({"Authorization": f"Bearer {token}"})

    if use_basic_auth:
        if not username or not password:
            raise ValueError("Username and password required for basic auth")
        session.auth = HTTPBasicAuth(username, password)


def download_and_unzip(session, url: str, extract_to: Path) -> None:
    log.info("Downloading %s", url)

    extract_to.mkdir(parents=True, exist_ok=True)

    resp = session.get(url, timeout=120)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "zip" not in content_type and "octet-stream" not in content_type:
        raise RuntimeError(
            f"Expected ZIP but got Content-Type '{content_type}'. "
            f"First 200 bytes:\n{resp.text[:200]}"
        )

    data = io.BytesIO(resp.content)

    with zipfile.ZipFile(data) as zf:
        zf.extractall(extract_to)

    log.info("Extracted to %s", extract_to)


def _filter_availability_docrefs(entries: List[dict], master_ident: str) -> List[dict]:

    matches = []

    for entry in entries:
        resource = entry.get("resource", {})
        master = resource.get("masterIdentifier", {})

        if master.get("system") == PROJECT_IDENTIFIER_SYSTEM and master.get("value") == master_ident:
            matches.append(resource)

    return matches


def download_availability_reports(
    session: requests.Session,
    input_dir: Path,
    fhir_base_url: str,
    availability_master_ident: str,
) -> int:

    url = f"{fhir_base_url}/DocumentReference?_count=1000&_format=json"
    log.info("Querying %s", url)

    response = session.get(url, timeout=60)
    response.raise_for_status()

    bundle = response.json()
    docrefs = _filter_availability_docrefs(bundle.get("entry", []), availability_master_ident)

    log.info("Found %d matching DocumentReferences", len(docrefs))

    for docref in docrefs:
        author = docref["author"][0]["identifier"]["value"]

        contents = docref.get("content", [])
        if len(contents) != 1:
            log.warning("Skipping docref with unexpected content length")
            continue

        measure_url = contents[0].get("attachment", {}).get("url")
        if not measure_url:
            log.warning("Skipping docref without MeasureReport URL")
            continue

        full_url = f"{fhir_base_url}/{measure_url}?_format=json"
        log.debug("Downloading report %s", full_url)

        report = session.get(full_url, timeout=60)
        report.raise_for_status()

        outfile = input_dir / f"availability_report_{author}.json"
        outfile.write_text(json.dumps(report.json()), encoding="utf-8")

    return len(docrefs)


def update_availability_in_es(
    session: requests.Session,
    es_base_url: str,
    es_index: str,
    availability_dir: Path,
) -> None:

    bulk_url = f"{es_base_url}/{es_index}/_bulk"

    for file in sorted(availability_dir.glob("*.json")):
        log.info("Uploading %s", file.name)

        with file.open("rb") as fh:
            resp = session.post(
                bulk_url,
                headers={"Content-Type": "application/json"},
                data=fh,
                timeout=120,
            )

        resp.raise_for_status()          

    log.info("Elasticsearch update complete")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--onto-repo", required=True)
    parser.add_argument("--onto-git-tag", required=True)
    parser.add_argument("--update-ontology", action="store_true")

    parser.add_argument("--ontology-dir", required=True, type=Path)
    parser.add_argument("--availability-input-dir", required=True, type=Path)
    parser.add_argument("--availability-output-dir", required=True, type=Path)

    parser.add_argument("--availability-report-server-base-url", required=True)
    parser.add_argument("--availability-master-ident", required=True)

    parser.add_argument("--es-base-url", required=True)
    parser.add_argument("--es-index", required=True)
    parser.add_argument("--min-n-reports", default=3, required=False, type=int)

    parser.add_argument(
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )

    parser.add_argument("--use-oauth2", action="store_true")
    parser.add_argument("--oauth-token-url")
    parser.add_argument("--oauth-client-id")
    parser.add_argument("--oauth-client-secret")
    parser.add_argument("--oauth-scope")

    parser.add_argument("--use-basic-auth", action="store_true")
    parser.add_argument("--basic-username")
    parser.add_argument("--basic-password")

    parser.add_argument("--ca-cert", type=str, default=None)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.loglevel),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    args.ontology_dir.mkdir(parents=True, exist_ok=True)
    args.availability_input_dir.mkdir(parents=True, exist_ok=True)
    args.availability_output_dir.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:

        configure_session(
            session,
            use_oauth2=args.use_oauth2,
            token_url=args.oauth_token_url,
            client_id=args.oauth_client_id,
            client_secret=args.oauth_client_secret,
            scope=args.oauth_scope,
            use_basic_auth=args.use_basic_auth,
            username=args.basic_username,
            password=args.basic_password,
            ca_cert_path=args.ca_cert
        )

        if args.update_ontology:
            base = f"{args.onto_repo}/{args.onto_git_tag}"
            download_and_unzip(session, f"{base}/elastic.zip", args.ontology_dir)
            download_and_unzip(session, f"{base}/availability.zip", args.availability_input_dir)

        n_reports = download_availability_reports(
            session,
            args.availability_input_dir,
            args.availability_report_server_base_url,
            args.availability_master_ident,
        )

        if n_reports < args.min_n_reports:
            log.info("Only %d reports found, but %d required → stopping", n_reports, args.min_n_reports)
            return

        log.info("Processing %d reports", n_reports)

        generator = ElasticAvailabilityGenerator(
            args.availability_input_dir,
            args.availability_output_dir,
            args.ontology_dir,
        )

        generator.generate()

        update_availability_in_es(
            session,
            args.es_base_url,
            args.es_index,
            args.availability_output_dir,
        )


if __name__ == "__main__":
    main()
