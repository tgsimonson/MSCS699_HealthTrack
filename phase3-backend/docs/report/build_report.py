"""fill the report text from reports/performance.json and test_results data, then write text.json for report.js"""
import json
import math
import sys

perf = json.load(open(sys.argv[1]))
tests = json.load(open(sys.argv[2]))          # {"total":..,"passed":..,"coverage":..}
e, d, ix, b = perf["environment"], perf["dataset"], perf["index_effectiveness"], perf["ingest_batch_500"]
ep = perf["endpoints"]


def p(name, k="p50_ms"):  # noqa: ANN001, ANN201
    return f"{ep[name][k]:.1f}"


worst_read = max(ep.values(), key=lambda s: s["p95_ms"])["p95_ms"]

text = {
    "title": "HealthTrack Backend Security Implementation and Performance Testing",
    "sections": [
        {"heading": None, "paras": [
            "The Phase 3 backend implements the Phase 2 design as a FastAPI service over SQLAlchemy models with "
            "Alembic migrations. All data is synthetic."]},
        {"heading": "Security Measures", "paras": [
            "*Authentication.* Passwords are stored only as bcrypt hashes at cost "
            "12, and an unknown email triggers a dummy hash check so response time does not reveal which accounts "
            "exist. Access tokens are JSON Web Tokens that expire after 15 minutes, with the algorithm, issuer, and "
            "audience pinned. Refresh tokens are 256-bit random "
            "values stored only as SHA-256 hashes and rotated on every use. Presenting a rotated token is treated as "
            "theft and revokes every session. Access tokens are tied to a session row, so logout or deactivation ends "
            "access at once. Five failed logins lock an account for 15 minutes, a rate limiter returns 429 on "
            "repeated attempts, and multifactor accounts must supply a time-based one-time password.",
            "*Authorization and auditing.* Every patient-scoped route resolves the patient and checks both role and "
            "relationship: patients reach only their own record, clinicians and physicians reach only patients on "
            "their current care team, administrators see demographics but no readings, and IT administrators see no "
            "patient data. An out-of-scope request returns 404 instead of 403 so the API never confirms that another "
            "clinician's patient exists, and the denial is written to the audit log. The append-only audit log, which "
            "follows the audit control safeguard of the HIPAA Security Rule (U.S. Department of Health and Human "
            "Services, n.d.), records the actor, action, record, and outcome of each read and write, never health values.",
            "*Input validation and error handling.* Pydantic schemas reject unknown fields, and the database repeats "
            "each rule as a CHECK, unique, or foreign key constraint. Physically impossible "
            "readings are rejected, while unlikely ones are stored with a suspect flag so they never drive an alert. "
            "All errors return RFC 9457 problem details (Nottingham et al., 2023) with a request identifier; "
            "unhandled exceptions return a generic 500, and responses are marked no-store. The main gap from the "
            "Phase 2 design is that the care-team rule is enforced in the API layer, not yet by PostgreSQL row-level "
            "security policies, which are planned for final integration."]},
        {"heading": "Performance Testing", "paras": [
            f"The benchmark (scripts/benchmark.py) migrated a fresh database and loaded {d['patients'] - 8} synthetic "
            f"patients with {d['vital_signs_rows']:,} vital sign rows. Requests ran in-process through the full stack, excluding network time. The run used macOS {e['os'].split('-')[1]} on an "
            f"Apple silicon Mac mini with {e['cpu_count']} cores, Python {e['python']}, and SQLite "
            f"{e['database_version']}. The test suite passed {tests['passed']} of {tests['total']} tests on the same "
            f"machine with {tests['coverage']:.1f}% line coverage, above the 80% target in requirement NFR-16.",
            "[TABLE1]",
            f"As Table 1 shows, every read endpoint stayed under {math.ceil(worst_read)} ms at the 95th percentile, well inside the 300 ms "
            f"target from requirement NFR-08. Batch upload sustained about {b['readings_per_second']:,} readings per "
            f"second, and a replayed batch stored nothing, so device retries are safe. Login was the slowest operation at {perf['login']['p50_ms']:.0f} "
            f"ms, an intended cost of the bcrypt work factor.",
            f"The composite index on patient and recorded time had the largest effect. For a 24-hour window "
            f"on a patient with {ix['patient_total_rows']:,} readings, the query returned {ix['rows_returned']} rows "
            f"in {ix['with_index']['p50_ms']:.2f} ms with the index. Without it, SQLite read and sorted every reading "
            f"for the patient, taking "
            f"{ix['without_index']['p50_ms']:.2f} ms, a {ix['speedup_p50']:.0f}\u2011fold difference that grows with "
            f"patient history. These results cover one machine, "
            f"SQLite, and a single client; concurrent load and PostgreSQL are left for Phase 6."]},
    ],
    "table": [[name, ep_s["n"], ep_s["p50_ms"], ep_s["p95_ms"]] for name, ep_s in
              [("POST /auth/token (bcrypt cost 12)", perf["login"]),
               ("POST vitals, single reading", perf["ingest_single"]),
               ("POST vitals/batch, 500 readings", b),
               ("GET /patients (worklist page)", ep["GET /patients (worklist page)"]),
               ("GET vitals, 24-hour page", ep["GET /patients/{id}/vitals (24 h page)"]),
               ("GET vitals, 7 days, 200 per page", ep["GET /patients/{id}/vitals (7 days, page 1 of n)"]),
               ("GET vitals/latest", ep["GET /patients/{id}/vitals/latest"]),
               ("GET vitals/daily-summary, 21 days", ep["GET /patients/{id}/vitals/daily-summary (21 days)"]),
               ("GET daily-activity/summary", ep["GET /patients/{id}/daily-activity/summary"]),
               ("POST /patients/search", ep["POST /patients/search"])]],
    "table_n": perf["environment"]["load"]["iterations"],
    "references": [
        "Nottingham, M., Wilde, E., & Dalal, S. (2023). *Problem details for HTTP APIs* (RFC 9457). Internet "
        "Engineering Task Force. https://doi.org/10.17487/RFC9457",
        "U.S. Department of Health and Human Services. (n.d.). *Summary of the HIPAA Security Rule*. Retrieved "
        "November 8, 2026, from https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html",
    ],
}
json.dump(text, open(sys.argv[3], "w"), indent=2)
print(sum(len(x.split()) for s in text["sections"] for x in s["paras"] if x != "[TABLE1]"), "words")
