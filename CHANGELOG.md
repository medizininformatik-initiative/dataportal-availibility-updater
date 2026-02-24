# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

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
