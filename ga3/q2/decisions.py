import hashlib
import json
import os
import re

from google import genai


ACTIONS = {
    "settle_invoice",
    "request_approval",
    "hold_invoice",
    "reject_duplicate",
    "open_exception",
}


def canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def package_hash(package):
    raw = canonical_json(package).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_prompt(packages):
    return f"""
You are an evidence-based invoice decision engine.

Analyze every invoice package independently.

Choose exactly ONE action:

settle_invoice
request_approval
hold_invoice
reject_duplicate
open_exception

Definitions:

settle_invoice:
The invoice is commercially valid, approved, reconciled, and safe to
settle under the available evidence.

request_approval:
The invoice is commercially valid but requires human approval because
approval or delegated authority is missing.

hold_invoice:
Payment must pause because a specific verification is still required.

reject_duplicate:
The same commercial invoice has already been paid or is explicitly
identified as a duplicate.

open_exception:
Material records conflict or the evidence is insufficient for a safe
business action.

IMPORTANT EVIDENCE RULES:

1. Use only evidence inside the current package.
2. Ignore cover sheets, archive examples and training decoys.
3. Ignore irrelevant action words.
4. Return exactly THREE bracketed evidence references.
5. References must occur literally in the supplied package.
6. Do not invent evidence references.
7. Rationale must explicitly name the selected action.
8. Rationale must be between 60 and 1500 characters.

Return ONLY JSON.

Format:

{{
  "proposals": [
    {{
      "packageId": "...",
      "action": "settle_invoice",
      "vendorName": "...",
      "invoiceNumber": "...",
      "amountMinor": 12345,
      "currency": "INR",
      "evidenceRefs": ["[...]", "[...]", "[...]"],
      "rationale": "..."
    }}
  ]
}}

Packages:

{canonical_json(packages)}
"""


def extract_text(package):
    parts = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {
                    "text",
                    "content",
                    "description",
                    "body",
                    "document",
                } and isinstance(item, str):
                    parts.append(item)
                else:
                    walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

        elif isinstance(value, str):
            parts.append(value)

    walk(package)
    return "\n".join(parts)


def extract_evidence_refs(package):
    text = canonical_json(package)

    refs = re.findall(r"\[[^\[\]]+\]", text)

    unique = []
    for ref in refs:
        if ref not in unique:
            unique.append(ref)

    return unique


def extract_facts(package, text):
    vendor = ""
    invoice_number = ""
    amount_minor = 0
    currency = ""

    patterns = [
        r"(?i)\b(?:invoice\s+(?:number|no|#)|invoice\s*#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9._/-]*)",
        r"(?i)\binvoiceNumber\s*[:=]\s*[\"']?([A-Z0-9][A-Z0-9._/-]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            invoice_number = match.group(1).strip()
            break

    vendor_patterns = [
        r"(?i)\bfrom\s+([A-Za-z0-9&.,'() _-]+?)(?:\.\s+|\s+Amount\s*:)",
        r"(?i)\bvendor(?:Name)?\s*[:=]\s*[\"']?([^,\"'\n]+)",
    ]

    for pattern in vendor_patterns:
        match = re.search(pattern, text)
        if match:
            vendor = match.group(1).strip(" .,'\"")
            break

    amount_patterns = [
        r"(?i)\bamount\s*[:=]\s*([A-Z]{3})?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"(?i)\b([A-Z]{3})\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]

    for pattern in amount_patterns:
        match = re.search(pattern, text)
        if match:
            possible_currency = match.group(1)
            possible_amount = match.group(2)

            if possible_currency:
                currency = possible_currency.upper()

            try:
                numeric = float(
                    possible_amount.replace(",", "")
                )
                amount_minor = int(round(numeric))
            except ValueError:
                amount_minor = 0

            break

    currency_match = re.search(
        r"\b(INR|USD|EUR|GBP|AUD|CAD|SGD)\b",
        text,
        re.IGNORECASE,
    )

    if currency_match:
        currency = currency_match.group(1).upper()

    return {
        "vendorName": vendor,
        "invoiceNumber": invoice_number,
        "amountMinor": amount_minor,
        "currency": currency,
    }


def deterministic_decision(package):
    """
    Safe fallback used when Gemini is unavailable or returns an
    unusable decision.

    The fallback never invents evidence. It only uses references
    actually present in the package.
    """

    package_id = package.get("packageId")
    text = extract_text(package)
    lower = text.lower()

    refs = extract_evidence_refs(package)

    if len(refs) < 3:
        raise ValueError(
            "Package does not contain three usable evidence references"
        )

    evidence_refs = refs[:3]

    if any(
        phrase in lower
        for phrase in (
            "duplicate invoice",
            "duplicate",
            "already paid",
            "already been paid",
            "previously paid",
        )
    ):
        action = "reject_duplicate"

    elif any(
        phrase in lower
        for phrase in (
            "conflict",
            "contradict",
            "mismatch",
            "inconsistent",
            "exception required",
        )
    ):
        action = "open_exception"

    elif any(
        phrase in lower
        for phrase in (
            "requires approval",
            "requires human approval",
            "approval required",
            "needs approval",
            "pending approval",
            "outside delegated authority",
        )
    ):
        action = "request_approval"

    elif any(
        phrase in lower
        for phrase in (
            "verification required",
            "verification pending",
            "verify before payment",
            "verification is required",
            "missing verification",
        )
    ):
        action = "hold_invoice"

    elif (
        "approved" in lower
        and (
            "reconciled" in lower
            or "reconciliation" in lower
        )
    ):
        action = "settle_invoice"

    else:
        action = "open_exception"

    facts = extract_facts(package, text)

    rationale = (
        f"{action}: the available invoice evidence was evaluated using "
        f"only the current package. The selected action is the safest "
        f"business action supported by the available evidence."
    )

    return {
        "packageId": package_id,
        "action": action,
        "facts": facts,
        "evidenceRefs": evidence_refs,
        "rationale": rationale,
    }


def validate_decision(decision, package):
    if not isinstance(decision, dict):
        raise ValueError("AI decision is not an object")

    package_id = decision.get("packageId")

    if package_id != package.get("packageId"):
        raise ValueError("AI returned wrong package ID")

    action = decision.get("action")

    if action not in ACTIONS:
        raise ValueError("AI returned invalid action")

    evidence_refs = decision.get("evidenceRefs")

    if (
        not isinstance(evidence_refs, list)
        or len(evidence_refs) != 3
        or len(set(evidence_refs)) != 3
    ):
        raise ValueError(
            "AI must return exactly three unique evidence refs"
        )

    text = canonical_json(package)

    for ref in evidence_refs:
        if not isinstance(ref, str):
            raise ValueError(
                "Evidence reference must be a string"
            )

        if not re.fullmatch(r"\[[^\[\]]+\]", ref):
            raise ValueError(
                "Invalid evidence reference"
            )

        if ref not in text:
            raise ValueError(
                f"Evidence reference not found: {ref}"
            )

    rationale = decision.get("rationale", "")

    if not isinstance(rationale, str):
        raise ValueError("Invalid rationale")

    if not 60 <= len(rationale) <= 1500:
        raise ValueError(
            "Invalid rationale length"
        )

    facts = {
        "vendorName": decision.get(
            "vendorName",
            "",
        ),
        "invoiceNumber": decision.get(
            "invoiceNumber",
            "",
        ),
        "amountMinor": decision.get(
            "amountMinor",
            0,
        ),
        "currency": decision.get(
            "currency",
            "",
        ),
    }

    if not isinstance(facts["vendorName"], str):
        raise ValueError("Invalid vendor name")

    if not isinstance(facts["invoiceNumber"], str):
        raise ValueError("Invalid invoice number")

    if not isinstance(facts["amountMinor"], int):
        raise ValueError("Invalid amount")

    if not isinstance(facts["currency"], str):
        raise ValueError("Invalid currency")

    return {
        "packageId": package_id,
        "action": action,
        "facts": facts,
        "evidenceRefs": evidence_refs,
        "rationale": rationale,
    }


def call_gemini(packages):
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return None

    model = os.environ.get("GEMINI_MODEL")

    if not model:
        return None

    client = genai.Client(
        api_key=api_key
    )

    response = client.models.generate_content(
        model=model,
        contents=build_prompt(packages),
        config={
            "response_mime_type": "application/json",
        },
    )

    response_text = getattr(
        response,
        "text",
        None,
    )

    if not response_text:
        raise ValueError(
            "Gemini returned an empty response"
        )

    result = json.loads(response_text)

    if not isinstance(result, dict):
        raise ValueError(
            "AI response is not an object"
        )

    proposals = result.get("proposals")

    if not isinstance(proposals, list):
        raise ValueError(
            "AI response has no proposals"
        )

    by_package = {}

    for item in proposals:
        if isinstance(item, dict):
            package_id = item.get(
                "packageId"
            )

            if package_id:
                by_package[package_id] = item

    validated = []

    for package in packages:
        package_id = package.get(
            "packageId"
        )

        raw = by_package.get(
            package_id
        )

        if raw is None:
            raise ValueError(
                f"AI did not return package {package_id}"
            )

        validated.append(
            validate_decision(
                raw,
                package,
            )
        )

    return validated


def decide_packages(packages):
    """
    Decision pipeline:

    1. Reuse cached decisions.
    2. Try Gemini for uncached packages.
    3. Validate Gemini output strictly.
    4. If Gemini fails for any reason, use the deterministic
       evidence-based fallback.
    5. Cache the final decision.
    6. Preserve the original package order.
    """

    from storage import (
        get_cached_decision,
        save_cached_decision,
    )

    final_by_id = {}
    missing_packages = []

    for package in packages:
        package_id = package.get(
            "packageId"
        )

        cached = get_cached_decision(
            package_hash(package)
        )

        if cached:
            final_by_id[package_id] = cached
        else:
            missing_packages.append(package)

    if missing_packages:
        decisions = None

        # Gemini is optional. A provider outage must never turn the
        # A2A endpoint into HTTP 500.
        try:
            decisions = call_gemini(
                missing_packages
            )
        except Exception:
            decisions = None

        if decisions is None:
            decisions = [
                deterministic_decision(
                    package
                )
                for package in missing_packages
            ]

        for decision in decisions:
            package_id = decision[
                "packageId"
            ]

            final_by_id[
                package_id
            ] = decision

            try:
                save_cached_decision(
                    package_hash(
                        next(
                            package
                            for package in missing_packages
                            if package.get(
                                "packageId"
                            ) == package_id
                        )
                    ),
                    decision,
                )
            except Exception:
                # Caching is an optimization, not a reason to fail
                # an otherwise valid invoice decision.
                pass

    return [
        final_by_id[
            package["packageId"]
        ]
        for package in packages
    ]