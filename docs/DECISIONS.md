# Architecture Decision Records

## ADR 001: Modular monolith
Use one Django backend and one shared database.

## ADR 002: Local database
Use SQLite for local development and demonstration.

## ADR 003: Deployment database
Target PostgreSQL for shared deployment.

## ADR 004: Farmer access
A farmer profile does not require the farmer to own a smartphone.

## ADR 005: Inventory
Represent stock changes through an auditable movement ledger.

## ADR 006: Quality inspection
Record human-confirmed observations. Do not claim unsupported automated grading.

## ADR 007: Buyer verification
Public batch verification must not expose private farmer information.
