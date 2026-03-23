Create a database migration.

Read @docs/05-DATABASE-MIGRATIONS.md for schema conventions and the index strategy table.

Rules:
- Every migration needs both upgrade() and downgrade()
- New indexes follow the naming convention: ix_<table>_<columns>
- UUID primary keys use server_default=sa.text("gen_random_uuid()")
- Never drop a column in the same migration that adds its replacement

Run after creating: alembic revision --autogenerate -m "$ARGUMENTS"
Then review the generated file before finalizing.
