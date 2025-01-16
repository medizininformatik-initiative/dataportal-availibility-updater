FROM python:3.9

RUN mkdir -p /opt/availability-updater

COPY src/py/ElasticAvailabilityGenerator.py /opt/availability-updater/src/py/ElasticAvailabilityGenerator.py
COPY src/py/generate-availability.py /opt/availability-updater/src/py/generate-availability.py

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /opt/availability-updater

RUN mkdir availability_input
RUN mkdir availability_output
RUN mkdir elastic_ontology

RUN chown -R 10001:10001 /opt/availability-updater

COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER 10001

ENTRYPOINT ["docker-entrypoint.sh"]