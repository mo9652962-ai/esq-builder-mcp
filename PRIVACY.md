# Privacy Policy for esq-builder-mcp

**Last Updated:** October 2026

`esq-builder-mcp` is an open-source, local-first Model Context Protocol (MCP) server for building, validating, and managing ESQ question-bank packages.

## 1. Local Processing & Zero External Telemetry
- All package compilation, JSON parsing, key normalization, candidate extraction, and validation execute **100% locally** within the running Python process.
- No analytics SDKs, error reporting beacons, or user tracking mechanisms exist in this repository.

## 2. Network & Upload Boundaries
- Network operations are restricted to `upload_and_publish`, which connects solely to the **user's explicitly designated local or internal test server** (e.g. `http://127.0.0.1:8765`).
- No question-bank data, vocabulary lists, or exam content are transmitted to any third-party clouds or external services.

## 3. Data Ownership
- All question packages and user materials remain the exclusive intellectual property of the author/user.

## 4. Contact
For questions or concerns, please open an issue at [mo9652962-ai/esq-builder-mcp](https://github.com/mo9652962-ai/esq-builder-mcp).
