# DCA Backend Service

A minimal, self-hosted backend service for an automatic BTC DCA strategy.

## Features
- Transaction history tracking
- Simulation endpoint
- Simple web interface

## Setup
1. Install dependencies: `poetry install`
2. Run server: `poetry run uvicorn dca_service.main:app --reload`
