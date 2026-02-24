FROM python:3.14

RUN mkdir -p /opt/availability-updater

COPY src/py/elastic_availability_generator.py /opt/availability-updater/src/py/elastic_availability_generator.py
COPY src/py/generate_availability.py /opt/availability-updater/src/py/generate_availability.py

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /opt/availability-updater

RUN mkdir availability_input
RUN mkdir availability_output
RUN mkdir elastic_ontology
COPY src/resources/stratum-to-context.json /opt/availability-updater/availability_input

RUN chown -R 10001:10001 /opt/availability-updater

COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER 10001

ENTRYPOINT ["docker-entrypoint.sh"]