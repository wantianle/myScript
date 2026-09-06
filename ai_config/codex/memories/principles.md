# Principles

## Core Style

- Explicit is better than implicit. Cross-module boundaries, inputs, outputs, side effects, configuration, startup flow, lifecycle, and error handling should be visible and easy to trace.
- Do not add entities unless necessary. Before adding a wrapper, script, config, class, service, temporary file, metadata transform, or abstraction layer, first check whether the existing interface can solve the problem with a smaller input shape.
- Prefer Pythonic code, but reject magic. Code should be concise, idiomatic, and readable, not clever, hidden, or overly compressed.

## Implementation Rules

- Start from the consumer's real interface. If the consumer only needs a file, provide a file; if a fixed overwritten path is enough, prefer it over unique temporary files plus cleanup.
- A new entity is justified only when it carries a clear boundary, ownership, lifecycle, invariant, reuse point, test seam, or safety guarantee that reduces overall complexity.
- Prefer stable, boring, traceable control flow over hidden registration, import-time side effects, monkey patching, dynamic attribute tricks, or behavior hidden behind decorators.
- Keep Python idiomatic when it improves clarity: comprehensions for simple value construction, context managers for resource lifetime, standard library parsers for structured data, and small functions for clear operations.
- Avoid Pythonic-looking code that hides intent: nested clever comprehensions, list comprehensions used only for side effects, broad `**locals()` forwarding, implicit global mutation, and unnecessary metaprogramming.
- When two designs both work, choose the one with fewer moving parts and more visible data flow.
- This is not anti-abstraction. It is a requirement that every abstraction prove it pays for itself.
