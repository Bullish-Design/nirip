# Nuclear Refactor Progress

- [x] Step 1: Implemented `src/nirip/spec.py` (models, validation, loading, errors).
- [x] Step 2: Implemented `src/nirip/resolve.py` (matching, assignment, flat resolution).
- [x] Step 3: Implemented `src/nirip/plan.py` (unified steps, plan builder, topo sort).
- [x] Step 4: Implemented `src/nirip/execute.py` (async engine, handlers, hooks, runtime state).
- [x] Step 5: Implemented `src/nirip/capture.py` (snapshot to SessionSpec capture).
- [x] Step 6: Implemented `src/nirip/cli.py` (commands, formatting, parser, main).
- [x] Step 7: Implemented `src/nirip/__init__.py` (new public API, sync apply_session).
- [x] Step 8: Updated `src/nirip/__main__.py` to v2 cli entrypoint.
- [ ] Step 9: Delete legacy code (already absent in this branch, verify final state).
- [ ] Step 10: Build new v2 test suite from scratch.
- [ ] Step 11: Optional version bump in `pyproject.toml`.
- [ ] Step 12: Final validation suite.
