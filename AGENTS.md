# AGENTS.md

Guidance for future agents working in this repo:

- Prefer simple, direct code. Avoid defensive branches, broad compatibility handling, wrappers, and helpers unless current requirements make them necessary.
- Do not add abstractions just to make code look generic. Inline small single-use helpers when the call site is clearer.
- In LangGraph workflows, prefer nodes that return `Command(update=..., goto=...)` directly. Avoid conditional-edge routing helpers unless routing is shared or complex enough to justify them.
- Treat invocation contracts as contracts. If the code assumes context/config/input is present, express that assumption directly instead of silently inventing fallbacks.
- Keep service dependencies typed and visible:
  - Use protocols instead of `Any` for service boundaries.
  - Put each protocol near the real implementation it describes.
  - Have real implementations explicitly inherit their protocol so the contract is discoverable from the implementation file.
  - Keep dependency containers focused and typed.
  - Keep default construction private unless callers need it.
- Avoid redundant syntax. Do not use splat/unpacking, dict merges, keyword-only markers, or temporary variables when direct expressions are clearer.
- Prefer whole-workflow tests over testing private node/helper internals. Use fakes at service boundaries and exercise the compiled graph when practical.
- Tests must not make real external side effects. Use fakes that record calls and assert behavior from those records.
- Keep side-effect boundaries explicit. If a service method is intentionally a no-op, make that clear in the implementation and tests.
- After changes, run focused tests and lint/type checks for touched code. If broader checks fail on pre-existing unrelated issues, report that separately instead of folding in unrelated cleanup.
