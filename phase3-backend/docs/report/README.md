# Building the security and performance report

Run from `phase3-backend/` after `./scripts/run_reports.sh`. Needs Node with the `docx` package and LibreOffice.

```bash
echo '{"total":237,"passed":237,"coverage":97.8}' > /tmp/tests.json   # numbers from reports/test_results.md
python3 docs/report/build_report.py reports/performance.json /tmp/tests.json /tmp/text.json
node docs/report/report.js /tmp/text.json docs/HealthTrack_Phase3_Security_Performance.docx
soffice --headless --convert-to pdf --outdir docs docs/HealthTrack_Phase3_Security_Performance.docx
```
