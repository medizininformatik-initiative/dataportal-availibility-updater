import json
import docker
import pytest
import time
import requests
import subprocess
import os
import shutil
import yaml


@pytest.fixture(scope="session")
def config():
    with open("resources/config.yml", "r") as file:
        return yaml.safe_load(file)

@pytest.fixture(scope="session")
def docker_client():
    client = docker.from_env()
    yield client
    client.close()


@pytest.fixture(scope="session")
def start_containers(docker_client, config):

    containers = []
    network = None

    try:
        network = docker_client.networks.create("test_network_availability", driver="bridge")

        print("Starting fhir server container...")
        fhir_report_server = docker_client.containers.run(
            image=f"samply/blaze:{config['fhir_server']['image_tag']}",
            name="test-availability-report-store",
            environment={
                "BASE_URL": config['fhir_server']['base_url'],
                "JAVA_TOOL_OPTIONS": "-Xmx2g",
                "LOG_LEVEL": "debug"
            },
            ports={"8080/tcp": config['fhir_server']['port']},
            detach=True
        )

        containers.append(fhir_report_server)

        print("Starting elastic search container...")
        elastic_search = docker_client.containers.run(
               image=f"docker.elastic.co/elasticsearch/elasticsearch:{config['elastic']['image_tag']}",
               name="test-dataportal-elastic",
               environment={
                   "discovery.type": "single-node",
                   "ES_JAVA_OPTS": "-Xmx512m -Xms512m",
                   "node.name": "es01",
                   "cluster.name": "elasticsearch",
                   "xpack.security.enabled": "false"
               },
               ports={"9200/tcp": config['elastic']['port']},
               detach=True,
               network="test_network_availability"
           )

        containers.append(elastic_search)

        wait_for_health(f"http://localhost:{config['elastic']['port']}/_cluster/health", timeout=30)

        print("Starting elastic search init container...")
        docker_client.containers.run(
            image="ghcr.io/medizininformatik-initiative/dataportal-es-init:latest",
            name="test-dataportal-elastic-init",
            environment={
                "ES_HOST": "http://test-dataportal-elastic",
                "ES_PORT": "9200",
                "ONTO_GIT_TAG": config['onto']['tag'],
                "ONTO_REPO": config['onto']['repo'],
                "DOWNLOAD_FILENAME": "elastic.zip",
                "EXIT_ON_EXISTING_INDICES": "false"
            },
            detach=False,
            network="test_network_availability",
            remove=True
        )

        wait_for_health(f"http://localhost:{config['fhir_server']['port']}/fhir", timeout=30)

        yield containers

    finally:
        print("Stopping and removing containers...")
        for container in containers:
            container.stop()
            container.remove()

        network.remove()

def wait_for_health(url, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print(f"Health check passed for {url}")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    raise TimeoutError(f"Health check failed: {url} did not become available within {timeout} seconds")


def check_availability_was_updated(config):

    data = {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": "I95.0",
                            "fields": [
                                "name",
                                "termcode^2"
                            ]
                        }
                    }
                ]
            }
        }
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.get(f"http://localhost:{config['elastic']['port']}/ontology/_search", headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        search_result = response.json()
        availability = search_result.get("hits", {}).get("hits", [{}])[0].get("_source", {}).get("availability", None)
        return availability


def test_basic_integration(start_containers, config):

    with open("resources/example_transaction_bundle_availability_report.json") as f:
        test_availability_report = json.load(f)

    requests.post(f"http://localhost:{config['fhir_server']['port']}/fhir", json=test_availability_report)

    os.makedirs("tmp", exist_ok=True)
    shutil.copy("resources/stratum-to-context.json", "tmp/input_dir/stratum-to-context.json")

    result = subprocess.run(
        [
            "python", "../src/py/generate_availability.py",  # Replace with your script's filename
            "--onto-repo", config['onto']['repo'],
            "--onto-git-tag", config['onto']['tag'],
            "--update-ontology"
            "--ontology-dir", "./tmp/elastic_ontology",
            "--availability-master-ident", "fdpg-data-availability-report-obfuscated",
            "--availability-input-dir", "./tmp/input_dir",
            "--availability-output-dir", "./tmp/output_dir",
            "--availability-report-server-base-url", f"http://localhost:{config['fhir_server']['port']}/fhir",
            "--es-base-url", f"http://localhost:{config['elastic']['port']}",
            "--es-index", "ontology",
            "--min-n-reports", "1",
            "--loglevel", "INFO",
        ],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"Script failed with error: {result.stderr}"

    assert check_availability_was_updated(config) == 10000


