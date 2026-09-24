# Claim-to-evidence map

| Claim | Evidence | Status |
| --- | --- | --- |
| Answered fixture responses carry citations. | `tests/test_service.py::test_answer_has_citations`. | Supported |
| Missing evidence abstains. | `tests/test_service.py::test_missing_evidence_abstains`; CI run 35991123370. | Supported |
| Tested prompt injection patterns refuse. | `tests/test_service.py::test_injection_is_refused`. | Supported |
| The project provides production safety coverage. | No production corpus or red-team benchmark exists. | Not claimed |
