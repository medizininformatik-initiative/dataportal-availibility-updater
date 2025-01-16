import argparse
import json
import logging
import os
import zipfile

import requests

from ElasticAvailabilityGenerator import ElasticAvailabilityGenerator

def str_to_bool(s):
    return s.lower() in ["true", "yes", "1"]

def download_and_unzip(url, extract_to):
    local_zip_path = "temp.zip"
    with requests.get(url, stream=True) as response:
        response.raise_for_status()  # Raise an error for bad status codes
        with open(local_zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    os.makedirs(extract_to, exist_ok=True)
    with zipfile.ZipFile(local_zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_to)

    os.remove(local_zip_path)


def download_availability_reports(availability_input_dir, fhir_base_url):
    response = requests.get(f'{fhir_base_url}/DocumentReference?_count=500&_format=json')

    doc_refs = response.json()

    for doc_ref in doc_refs['entry']:

        doc_ref = doc_ref['resource']

        author = doc_ref['author'][0]['identifier']['value']
        master_ident_system = doc_ref['masterIdentifier']['system']
        master_ident_value = doc_ref['masterIdentifier']['value']

        if not (master_ident_system == 'http://medizininformatik-initiative.de/sid/project-identifier'
                and master_ident_value == 'fdpg-availability-report'):
            logging.info(f'Not a availability report Doc ref -> skipping')
            continue

        if len(doc_ref.get('content', [])) != 1:
            logging.warning(f'Found measure reference not equal to 1 - expected measure ref number equal to 1')
            continue

        measure_ref = doc_ref.get('content')[0].get('attachment', {}).get('url', None)

        if measure_ref is None:
            logging.warning(
                f'Could not find a Measure Reference for availability report Doc Reference - ignoring Doc Reference')
            continue

        response = requests.get(f'{fhir_base_url}/{measure_ref}?_format=json')

        measure_report = response.json()

        report_file_name = f'availability_report_{author}.json'

        with open(os.path.join(availability_input_dir, report_file_name), 'w+') as fp:
            json.dump(measure_report, fp)


def update_availability_in_es(es_base_url, es_index, availability_dir):
    es_url = f'{es_base_url}/{es_index}/_bulk'

    for filename in os.listdir(availability_dir):
        file_path = os.path.join(availability_dir, filename)
        if os.path.isfile(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                response = requests.post(
                    es_url,
                    headers={'Content-Type': 'application/json'},
                    data=file
                )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--onto_repo', type=str)
    parser.add_argument('--onto_git_tag', type=str)
    parser.add_argument("--update_ontology", help="", type=str_to_bool, default="false")
    parser.add_argument('--ontology_dir', type=str)
    parser.add_argument('--availability_input_dir', type=str)
    parser.add_argument('--availability_output_dir', type=str)
    parser.add_argument('--availability_report_server_base_url', type=str)
    parser.add_argument('--es_base_url', type=str)
    parser.add_argument('--es_index', type=str)
    parser.add_argument(
        '--loglevel',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Set the logging level. Default is INFO."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.loglevel),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    os.makedirs(args.ontology_dir, exist_ok=True)
    os.makedirs(args.availability_input_dir, exist_ok=True)
    os.makedirs(args.availability_output_dir, exist_ok=True)

    if args.update_ontology:
        onto_download_url = f'{args.onto_repo}/{args.onto_git_tag}/elastic.zip'
        download_and_unzip(onto_download_url, args.ontology_dir)

    download_availability_reports(args.availability_input_dir, args.availability_report_server_base_url)

    es_avail_generator = ElasticAvailabilityGenerator(args.availability_input_dir, args.availability_output_dir,
                                                      args.ontology_dir)

    es_avail_generator.generate_availability()
    update_availability_in_es(args.es_base_url, args.es_index, args.availability_output_dir)
