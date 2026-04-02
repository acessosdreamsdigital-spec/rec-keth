import re


def normalize_phone(phone: str) -> str:
    """
    Normalize any phone format to E.164 (+55XXXXXXXXXXX).

    Handles:
    - Brazilian formatted: (29) 6670-9524
    - International without +: 5511987654321
    - Already E.164: +5511987654321
    - Short with + but no country code: +11987654321
    """
    digits = re.sub(r"\D", "", phone)

    if not digits:
        return phone

    # Already has +, keep digits as-is but ensure country code
    if phone.strip().startswith("+"):
        # If 12-13 digits and starts with 55, it's already Brazilian E.164
        if len(digits) in (12, 13) and digits.startswith("55"):
            return f"+{digits}"
        # If 10-11 digits, assume Brazilian without country code
        if len(digits) in (10, 11):
            return f"+55{digits}"
        return f"+{digits}"

    # No + prefix
    # 12-13 digits starting with 55 → already has country code
    if len(digits) in (12, 13) and digits.startswith("55"):
        return f"+{digits}"

    # 10-11 digits → Brazilian number without country code
    if len(digits) in (10, 11):
        return f"+55{digits}"

    # Fallback: prepend +
    return f"+{digits}"
