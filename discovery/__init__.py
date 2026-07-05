"""Series discovery — query each source's native search/catalogue API for
charter-relevant series, auto-fill metadata, and stage ranked candidates for
human approval before they enter the registry.

Flow: discover_<source>() -> list[Candidate] -> stage_xlsx() -> human review ->
workbook sync -> registry YAML -> bulk pull.
"""
