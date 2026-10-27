# COLA Label Verifier

Prototype that helps TTB compliance agents check alcohol label artwork against its COLA application data.

> Work in progress. Full documentation of the approach, tools, assumptions and trade-offs is coming.

## Run locally

Requires Python 3.13.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows (Git Bash); use .venv/bin/activate on macOS/Linux
pip install --require-hashes -r requirements-dev.txt
cp .env.example .env              # then fill in your keys; .env is gitignored
pytest                            # run the test suite
python -m app.server              # http://127.0.0.1:8000/healthz
```

Or with Docker:

```bash
docker build -t cola-label-verifier .
docker run --rm -p 8000:8000 --env-file .env cola-label-verifier
```

## Dependencies

`pyproject.toml` lists the direct dependencies. The `requirements*.txt` lock files are generated from it with hashes:

```bash
pip-compile --strip-extras --generate-hashes --allow-unsafe -o requirements.txt pyproject.toml
pip-compile --strip-extras --generate-hashes --allow-unsafe --extra dev -o requirements-dev.txt pyproject.toml
pip-compile --strip-extras --generate-hashes --allow-unsafe --extra security -o requirements-security.txt pyproject.toml
```
