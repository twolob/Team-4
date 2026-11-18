# FarmProof Architecture

FarmProof uses a modular Django monolith with one shared database.

Interfaces:
- Farmer: USSD
- Field agent: smartphone-friendly web interface
- Cooperative: management dashboard
- Buyer: public, permission-controlled batch verification

The backend owns business rules, validation, authorization and data integrity.

SQLite is used for local development. PostgreSQL is the intended deployment database.
