# Submission checklist — AI Field Developer / AI Solutions Engineer

## What to upload

Upload the **contents of this project folder** to a **public** GitHub repository. The repository root should display `README.md`, `requirements.txt`, `docker-compose.yml`, and the root Python files, root test and demo scripts. Do not commit the containing ZIP itself in lieu of the source files.

Suggested repository name: `ai-field-developer-solutions-engineer-assessment`.

## Before sharing the link

- [ ] Create a GitHub repository with **Public** visibility.
- [ ] Upload project files, including the **hidden** `.gitignore`, `.dockerignore`, and `.env.example` files. There is no `.github/` directory in this flat-file edition.
- [ ] Verify `.env` and any real credentials, private records, and local SQLite databases are **not** committed.
- [ ] Run `python -m pip install -r requirements.txt` with Python 3.11 or 3.12.
- [ ] Run `python -m pytest -v`; expect all tests to pass with the official MCP SDK installed.
- [ ] Run `python mcp_stdio_check.py` to confirm MCP stdio wire behavior.
- [ ] Run `docker compose up --build -d` then `python demo.py` (Docker required).
- [ ] Stop services with `docker compose down` when finished.
- [ ] Confirm the public repository loads in an incognito/private browser window.
- [ ] Share the URL, in this format: `https://github.com/YOUR-USERNAME/YOUR-REPOSITORY`.

## GitHub web upload

1. Sign in at https://github.com/new and create a public repository. Leave it empty (avoid initializing a second README or license).
2. Open the new repository. Select **uploading an existing file** or **Add file > Upload files**.
3. **Unzip** the provided archive and drag the files **inside** the extracted folder into the upload area. GitHub's browser uploader may not include hidden files or empty directories reliably; confirm hidden files are present after uploading.
4. Commit the files. Confirm the directory structure and the README preview look correct.
5. The flat-file edition does not include a GitHub Actions workflow. Run the documented pytest and stdio checks locally before submitting.
6. Copy the URL from the browser address bar and send it to the assessor.

## Alternative — Git commands (preserves hidden files)

After creating an **empty public** repository, from the extracted project folder:

```bash
git init
git add .
git commit -m "Implement MCP and LLM security gateway assessment"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Replace `YOUR-USERNAME` and `YOUR-REPOSITORY`; GitHub may ask you to authenticate using your configured credential manager. `git add .` respects `.gitignore` and does not add `.env` or SQLite files.

## Submit this message

**Subject:** AI Field Developer / Solutions Engineer — Technical Assessment Submission

Hello,

I have completed the technical assessment and published the source code, tests, Docker setup, and implementation documentation in a public GitHub repository:

**Repository:** https://github.com/YOUR-USERNAME/YOUR-REPOSITORY

The README includes setup instructions, usage examples, and verification commands for all four tasks.

Thank you for reviewing my submission.

Best regards

## Scope disclosure

The repository is an assessment implementation: it uses mock customer/refund systems, local authentication demonstration tokens, and mock LLM upstreams. The MCP SDK must be installed before validating the stdio server. It is not a production-ready, fully compliant MCP Streamable HTTP gateway or a general-purpose PII DLP engine.
