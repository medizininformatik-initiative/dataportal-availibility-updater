# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.4.2] - 2026-10-06

### Upgrade notes

- Elasticsearch in `docker/docker-compose.yml` moves from 8.16.1 to 9.5.4, which cannot start on the data of an 8.16 node. Before upgrading, stop the stack and delete the volume: `docker volume rm avail-dataportal-elastic-data`. The `availability-init-elasticsearch` service rebuilds the indices on the next start.

### Fixed

- Load ontology files from the `elastic/content` directory introduced in ontology 5.x ([#28](https://github.com/medizininformatik-initiative/dataportal-availibility-updater/issues/28))
- Fail with a clear error when no ontology nodes are loaded instead of sending an empty bulk request to Elasticsearch
- Skip empty update files when uploading to Elasticsearch

### Changed

- Upgrade to ontology 5.0.1
- Upgrade dependencies: requests 2.34.2, pytest 9.1.1, docker 7.2.0, Blaze 1.11.0, Elasticsearch 9.5.4, GitHub Actions to latest major versions

## [0.4.1] - 2026-08-19

### Fixed

- Reduced memory usage of the elastic availability generator by dropping unused ontology fields and writing updates in chunks directly instead of buffering them in memory

## [0.4.0] - 2026-08-18

### Added

- Added support for auth credentials (oauth2/basic auth) when fetching the ontology files
- Run integration and unit tests in CI

### Fixed

- Fixed chunking error in elastic availability generator
- Delete input dir on availability updater run
- Upgrade to ontology 4.3.0
- Fix resolving of MeasureReport url

## [0.3.0] - 2026-02-24

### Added

- Added oauth2 and basic auth support
- Added self-signed certificate support

## [0.2.0] - 2026-02-24

### Changed

- Refactored code
- Improved performance

### Added

- Treat patient stratifier differently - calculate accross als statifier and map individually
- Make min required reports for availability update configurable

## [0.1.1] - 2025-07-09

### Changed

- Exit with 0 if not enough reports


## [0.1.0] - 2025-07-09

Initial Release

### Added

- Initial Release with Container build
- Download Ontology from fhir-ontology-generator repository
- Download availability reports from local fhir report server
- Update Availability based on ontology
- Update Availability on local elastic search
