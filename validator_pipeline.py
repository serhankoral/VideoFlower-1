from dataclasses import dataclass

from candidate_store import StreamCandidate


@dataclass
class ValidationPolicy:
    blacklist_entries: tuple[str, ...] = tuple()
    min_content_length_mb: int = 0
    exclude_manifest: bool = False


@dataclass
class ValidationResult:
    accepted: bool
    reason: str


def validate_candidate(candidate: StreamCandidate, policy: ValidationPolicy) -> ValidationResult:
    url_lower = candidate.url.lower()

    for entry in policy.blacklist_entries:
        if entry and entry in url_lower:
            return ValidationResult(False, f"blacklist:{entry}")

    if policy.exclude_manifest and (".m3u8" in url_lower or "manifest" in url_lower):
        return ValidationResult(False, "manifest-excluded")

    if policy.min_content_length_mb > 0 and candidate.content_length is not None:
        min_size_bytes = policy.min_content_length_mb * 1024 * 1024
        if candidate.content_length < min_size_bytes:
            return ValidationResult(False, "content-length-too-small")

    return ValidationResult(True, "ok")


def filter_candidates(candidates: list[StreamCandidate], policy: ValidationPolicy) -> tuple[list[StreamCandidate], dict[str, str]]:
    accepted: list[StreamCandidate] = []
    rejected: dict[str, str] = {}

    for candidate in candidates:
        result = validate_candidate(candidate, policy)
        if result.accepted:
            accepted.append(candidate)
        else:
            rejected[candidate.url] = result.reason

    return accepted, rejected
