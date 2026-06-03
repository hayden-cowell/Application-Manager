# Job Application OS — Phase 2 PRD

**Status:** In design
**Phase 1:** Complete — fitment engine live at `services/fitment-engine/`

---

## Phase 2 Goal

Enable a real user to go from raw resume to a scored job assessment in under two minutes, without any manual profile construction or hardcoded data.

---

## Success Criteria

1. Upload a real resume (PDF or text) and get a `UserProfile` and `ResumeBaseline` that pass Pydantic validation
2. Answer follow-up questions for fields the parser could not infer
3. Paste a job description and receive an assessment with score, tier, reasoning, and missing signals
4. The assessment score is within 5 points of a manually constructed profile for the same candidate and job

---

## Services

| Service | Path | Port | Status |
|---|---|---|---|
| Fitment engine | `services/fitment-engine/` | 8000 | Complete |
| Web app backend | `services/web-app/backend/` | 8001 | Phase 2 |
| Resume parser | `services/resume-parser/` | 8002 | Phase 2 |
| Web app frontend | `services/web-app/frontend/` | 5173 | Phase 2 |

---

## User Flow

```
1. User uploads resume (PDF or text paste)
        ↓
2. Resume parser produces UserProfile + ResumeBaseline
        ↓
3. User answers follow-up questions for fields parser could not infer
        ↓
4. User pastes a job description
        ↓
5. Web app calls fitment engine → returns scored assessment
        ↓
6. User sees score, tier, reasoning, gaps, and tailoring suggestions
```

---

## Out of Scope for Phase 2

- Chrome extension (designed but not built)
- User accounts or authentication
- Application tracker
- Multi-user support
- Question bank and progressive enrichment UI
- Any design polish

---

## Phase 2 Complete When

End-to-end flow works: real resume → parsed profile → JD paste → assessment result, in a single browser session, with no manual file editing required.

---

## Design Documents

- Resume parser design: `services/resume-parser/SPEC.md`
- Web app design: `services/web-app/SPEC.md`
- Fitment engine design: `Input Documents/fitment-engine-spec.md`
