"""Research synthesis with source/quote/population checks independent of the LLM."""

from personal_markets.ports import ResearchArtifact, ResearchClaim, ResearchResult


def validate_research(
    proposed: ResearchArtifact, retrieved: ResearchResult, external_required: bool
) -> ResearchArtifact:
    originals = {str(row.get("source")): row for row in retrieved.claims}
    claims: list[ResearchClaim] = []
    limitations = list(proposed.limitations)
    provenance = []
    for candidate in proposed.claims:
        original = originals.get(candidate.source)
        if original is None:
            limitations.append("Rejected a claim without a retrieved source.")
            continue
        source_type = original.get("source_type", "frozen")
        if source_type == "frozen":
            # Versioned local references are explicit mechanistic assumptions, not verified studies.
            candidate = candidate.model_copy(
                update={
                    "source_type": "frozen",
                    "verification": "frozen_reference",
                    "material_kind": "frozen_reference",
                    "retrieved_at": str(
                        original.get("retrieved_at") or retrieved.retrieved_at.isoformat()
                    ),
                }
            )
        else:
            material = str(original.get("claim") or "")
            quote = candidate.supporting_quote.strip()
            if not quote or quote not in material:
                limitations.append("Rejected an unsupported quotation/claim.")
                continue
            candidate = candidate.model_copy(
                update={
                    "source_type": "web",
                    "verification": "candidate"
                    if original.get("material_kind") == "snippet"
                    else "source_supported",
                    "material_kind": original.get("material_kind", "document_text"),
                    "retrieved_at": retrieved.retrieved_at.isoformat(),
                }
            )
            if original.get("material_kind") == "snippet":
                limitations.append(
                    "Search snippets do not verify claims against the original source."
                )
            if candidate.applicability != "applicable" or not candidate.population:
                limitations.append("Reference population applicability is unestablished.")
            if candidate.contradiction:
                limitations.append("Contradictory research: " + candidate.contradiction)
        claims.append(candidate)
        if candidate.parameter:
            provenance.append(
                {
                    "parameter": candidate.parameter,
                    "value": candidate.value,
                    "unit": candidate.unit,
                    "source": candidate.source,
                    "retrieved_at": candidate.retrieved_at,
                    "supporting_quote": candidate.supporting_quote,
                    "population": candidate.population,
                    "applicability": candidate.applicability,
                    "verification": candidate.verification,
                    "status": "candidate",
                    "used_by_engine": False,
                }
            )
    if external_required:
        limitations.append(
            "Researched parameter candidates require domain review before model use; "
            "quoted text alone does not verify a numeric prior."
        )
    return ResearchArtifact(
        claims=claims,
        reference_class_candidates=list(originals),
        limitations=list(dict.fromkeys(limitations)),
        status="insufficient_evidence" if external_required else "sufficient",
        tool_trace=retrieved.tool_trace,
        parameter_provenance=provenance,
    )
