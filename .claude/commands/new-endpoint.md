Create a new API endpoint.

Read before writing:
- @docs/06-API-CONTRACT.md for the error format and response shapes
- backend/app/api/v1/datasets.py as a reference route file
- backend/app/dependencies.py for available DI components

Create in order:
1. Pydantic schema in backend/app/schemas/ (request + response)
2. Repository method if DB access needed
3. Service method in backend/app/services/
4. Route in the appropriate backend/app/api/v1/*.py file
5. Integration test in backend/tests/integration/

Apply rate limiting. Scope all queries by current_user.id. Raise ClarifiError subclasses.

Endpoint to create: $ARGUMENTS
