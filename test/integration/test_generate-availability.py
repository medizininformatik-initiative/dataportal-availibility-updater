import json
import docker
import pytest
import time
import requests
import subprocess
import os
import shutil

@pytest.fixture(scope="session")
def docker_client():
    client = docker.from_env()
    yield client
    client.close()


@pytest.fixture(scope="session")
def start_containers(docker_client):

    containers = []
    network = None

    try:
        network = docker_client.networks.create("test_network_availability", driver="bridge")

        print("Starting fhir server container...")
        fhir_report_server = docker_client.containers.run(
            image="samply/blaze:0.31",
            name="test-availability-report-store",
            environment={
                "BASE_URL": "http://localhost:8080",
                "JAVA_TOOL_OPTIONS": "-Xmx2g",
                "LOG_LEVEL": "debug"
            },
            ports={"8080/tcp": 8080},
            detach=True
        )

        containers.append(fhir_report_server)

        print("Starting elastic search container...")
        elastic_search = docker_client.containers.run(
               image="docker.elastic.co/elasticsearch/elasticsearch:8.16.1",
               name="test-dataportal-elastic",
               environment={
                   "discovery.type": "single-node",
                   "ES_JAVA_OPTS": "-Xmx512m -Xms512m",
                   "node.name": "es01",
                   "cluster.name": "elasticsearch",
                   "xpack.security.enabled": "false"
               },
               ports={"9200/tcp": 9200},
               detach=True,
               network="test_network_availability"
           )

        containers.append(elastic_search)

        wait_for_health("http://localhost:9200/_cluster/health", timeout=30)

        print("Starting elastic search init container...")
        elastic_search_init = docker_client.containers.run(
            image="ghcr.io/medizininformatik-initiative/dataportal-es-init:latest",
            name="test-dataportal-elastic-init",
            environment={
                "ES_HOST": "http://test-dataportal-elastic",
                "ES_PORT": "9200",
                "ONTO_GIT_TAG": "v3.0.2-alpha",
                "ONTO_REPO": "https://github.com/medizininformatik-initiative/fhir-ontology-generator/releases/download",
                "DOWNLOAD_FILENAME": "elastic.zip",
                "EXIT_ON_EXISTING_INDICES": "false"
            },
            detach=False,
            network="test_network_availability",
            remove=True
        )

        wait_for_health("http://localhost:8080/fhir", timeout=30)

        yield containers

    finally:
        print("Stopping and removing containers...")

        for container in containers:
            container.stop()
            container.remove()

        network.remove()

def wait_for_health(url, timeout=30):
    """Wait for the health check endpoint to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print(f"Health check passed for {url}")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)  # Retry every second
    raise TimeoutError(f"Health check failed: {url} did not become available within {timeout} seconds")


def check_availability_was_updated():

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

    response = requests.get("http://localhost:9200/ontology/_search", headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        search_result = response.json()
        availability = search_result.get("hits", {}).get("hits", [{}])[0].get("_source", {}).get("availability", None)
        return availability


def test_basic_integration(start_containers):

    with open("resources/example_transaction_bundle_availability_report.json") as f:
        test_availability_report = json.load(f)

    requests.post("http://localhost:8080/fhir", json=test_availability_report)

    os.makedirs("tmp", exist_ok=True)
    shutil.copy("resources/stratum-to-context.json", "tmp/input_dir/stratum-to-context.json")

    result = subprocess.run(
        [
            "python", "../src/py/generate-availability.py",  # Replace with your script's filename
            "--onto_repo", "https://github.com/medizininformatik-initiative/fhir-ontology-generator/releases/download",
            "--onto_git_tag", "v3.0.2-alpha",
            "--update_ontology", "true",
            "--ontology_dir", "./tmp/elastic_ontology",
            "--availability_input_dir", "./tmp/input_dir",
            "--availability_output_dir", "./tmp/output_dir",
            "--availability_report_server_base_url", "http://localhost:8080/fhir",
            "--es_base_url", "http://localhost:9200",
            "--es_index", "ontology",
            "--loglevel", "INFO",
        ],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"Script failed with error: {result.stderr}"

    assert check_availability_was_updated() == 10000


