# VSPELLS AI Agent Project Guidelines

## Build Commands
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- Run: `python -m vspells_ai_agent`
- Lint: `ruff check src/`
- Format: `ruff format src/`
- Type check: `mypy src/`
- Test: `pytest tests/`
- Single test: `pytest tests/path_to_test.py::test_name`

## Code Style Guidelines
- Python 3.12+ only
- Use type annotations everywhere (strict mypy mode)
- Snake case for variables, functions, modules (`my_var`, `my_function`)
- PascalCase for classes (`MyClass`)
- Constants in UPPERCASE (`MAX_RETRIES`)
- Use TypedDict for structured data
- ABC with @abstractmethod for interfaces
- Explicit error handling with appropriate exceptions
- Async code with proper exception handling
- Imports order: standard lib → third party → local
- Line length: 100 characters
- 4-space indentation, no tabs