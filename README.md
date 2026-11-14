# Wer stellt ein? — DACH Tech Hiring Index

Static site generator for a weekly index of open jobs at tech companies in Germany, Austria and Switzerland, read from the companies' public career-site feeds.

- `fetch.py` pulls the latest weekly run of the [Career Site Jobs Scraper](https://apify.com/goldfoot/ats-jobs-feed).
- `build.py` (no dependencies) renders pages per company, city, job area and ATS into `dist/`.
- `.github/workflows/weekly.yml` rebuilds every Monday and deploys to GitHub Pages (enabled via repo variable `DEPLOY=true`).

Data: company names, job titles, locations and links from public job boards. No personal data.
