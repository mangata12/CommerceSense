"""Bounded session-only view results, invalidated on file or mapping changes."""


def cached_view(state, name, conditions, calculate):
    signature = (state.get("commerce_file_fingerprint"),
                 tuple(sorted((state.get("commerce_applied_mapping") or {}).items())),
                 state.get("commerce_currency"), conditions)
    caches = state.setdefault("commerce_view_cache", {})
    saved = caches.get(name)
    if saved is None or saved[0] != signature:
        saved = (signature, calculate())
        caches[name] = saved
    return saved[1]
