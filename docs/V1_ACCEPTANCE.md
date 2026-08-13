# V1 Acceptance Checklist

Last verified: 2026-08-13

## Automated checks

- [x] Python unit and API tests pass (31 tests).
- [x] Python dependencies pass `pip check`.
- [x] Frontend lint, TypeScript build, and component tests pass (9 tests).
- [x] Production frontend bundle builds successfully.
- [x] npm production dependency audit reports zero known vulnerabilities.

## Product flow

- [x] JPEG, PNG, and WebP selection is supported.
- [x] Invalid media types and files over 10 MiB are rejected before submission.
- [x] Photo preview, removal, optional intent, and privacy consent work.
- [x] Analysis cannot start without a photo and explicit consent.
- [x] Vite proxies multipart requests to FastAPI.
- [x] Mock end-to-end upload returns five dimensions, three priority actions, and one exercise.
- [x] Expected API failures use the uniform error response shape.
- [x] Loading, retry, and invalid-response states are covered by frontend tests.

## Privacy and security

- [x] `.env`, virtual environments, frontend dependencies, and builds are not tracked.
- [x] No real API keys are present in tracked files.
- [x] V1 does not persist uploaded images.
- [x] The UI requires explicit provider-transfer consent.
- [x] Prompt instructions treat image text and user intent as untrusted data.
- [x] Reports must not invent EXIF, equipment, location, or off-frame conditions.

## Responsive and accessibility checks

- [x] No horizontal overflow at 375 px, 768 px, or 1280 px.
- [x] The primary action is at least 44 px high.
- [x] The home heading stays on one line at tested widths.
- [x] Form controls have labels, errors use text, and async status uses `aria-live`.
- [x] Keyboard focus is moved to the completed report.
- [x] Reduced-motion preferences are respected.

## Release conclusion

V1 meets its defined single-photo coaching scope using the Mock provider and has
also completed one separately authorized real Qwen integration test. Real model
quality remains an evaluation concern: schema validation guarantees structure,
not the professional accuracy of photography advice.
