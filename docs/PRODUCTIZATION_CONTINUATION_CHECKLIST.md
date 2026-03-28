# Productization Continuation Checklist

## Milestone A: Report Persistence
- [ ] Add `executive_reports` table in SQLite layer.
- [ ] Switch report metadata from index file to DB-first persistence.
- [ ] Add report list endpoint (`GET /api/reports`).

## Milestone B: ROI Accuracy
- [ ] Add seeded test fixtures for sessions/messages ROI calculations.
- [ ] Add week/month trend boundary tests.

## Milestone C: Reliability
- [ ] Add report artifact checksum validation.
- [ ] Add partial artifact failure handling and status reporting.

## Milestone D: Delivery Assets
- [ ] Add `scripts/smoke_productization.sh`.
- [ ] Add `docs/productization_api.md`.
- [ ] Add `docs/release_checklist.md`.
