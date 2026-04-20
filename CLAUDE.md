# CLAUDE.md

## Environment

- Python virtual environment: `.venv`
- Activate: `source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt` or `pip install -e .`
- Python version: use system `python3` if available

## Execution

- Run scripts: `python <file>.py`
- Run tests: `pytest -q`
- Lint (if present): `ruff check .`
- Format (if present): `ruff format .`

Do not assume tools exist. Check before using.

## Coding Rules

- Make the **smallest possible change** to satisfy the request
- Do **not** refactor unrelated code
- Do **not** introduce abstractions for single-use logic
- Match existing code style exactly
- Do not add comments unless necessary for correctness

## Dependencies

- Prefer standard library
- Add external dependencies only if required
- If adding a dependency:
  - Update `requirements.txt`
  - Use widely adopted, maintained packages only

## File Edits

- Modify only files required for the task
- Do not rename or move files unless explicitly asked
- Do not introduce new directories unless necessary

## Error Handling

- Fail fast with clear errors
- Do not silently swallow exceptions
- Log only what is necessary to debug

## Testing

- If fixing a bug:
  - Reproduce it first (test or script)
  - Then fix it
- Do not add large test frameworks if none exist
- Keep tests minimal and targeted

## Environment Safety

- Never hardcode secrets
- Use environment variables for credentials
- Assume environment variables may be missing and handle accordingly

## Output Expectations

- Prefer deterministic output
- Avoid non-deterministic behavior unless required
- Avoid unnecessary logging or verbosity

## When Unsure

- State assumptions explicitly
- If multiple valid approaches exist, list them briefly
- Do not pick a complex solution when a simple one works
