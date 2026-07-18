"""Pydantic schemas for the impact-analysis subsystem (DevImpact brief §5).

Import discipline: this module may import only pydantic + stdlib. The API
service imports it (via councilhound.impact.schemas) to type responses, and
the API image does not install the geo stack. Keep it light.

Two invariants the rest of the subsystem builds on:
- every MetricValue carries provenance and, where an assumption was applied,
  the Assumption's key — numbers are traceable or they don't ship;
- Assumption low/high bounds are REQUIRED, so sensitivity propagation is
  never optional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ModuleName = Literal["economic", "fiscal", "connectivity", "environmental", "comparables"]

Confidence = Literal["high", "medium", "low"]


class Provenance(BaseModel):
    source_name: str  # e.g. "Census ACS 5-yr 2023, table B25010"
    url: str
    vintage: str  # data year / release version / fiscal year
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str | None = None


class Assumption(BaseModel):
    key: str  # e.g. "avg_household_size"
    value: float
    low: float  # sensitivity bounds — required by design
    high: float
    basis: Provenance | str  # dataset it came from, or a citation string
    rationale: str

    @model_validator(mode="after")
    def _ordered(self) -> "Assumption":
        if not (self.low <= self.value <= self.high):
            raise ValueError(f"assumption {self.key}: expected low <= value <= high")
        return self


class CorridorSpec(BaseModel):
    """Present only for street/multimodal projects (M5 seam)."""
    length_ft: float | None = None
    facilities: list[str] = Field(default_factory=list)


class ExistingConditions(BaseModel):
    use: str | None = None
    sqft: float | None = None
    units: int | None = None
    assessed_value: float | None = None
    jobs_estimate: float | None = None


class ProposedProgram(BaseModel):
    units: int | None = None
    retail_sqft: float | None = None
    office_sqft: float | None = None
    stories: int | None = None
    acres: float | None = None
    parking_spaces: int | None = None
    affordable_units: int | None = None
    corridor: CorridorSpec | None = None


class ProjectSpec(BaseModel):
    name: str
    jurisdiction: str  # "fairfax_city_va"
    city_project_slug: str  # CityProject.external_slug this spec was built from
    source_url: str
    project_type: Literal[
        "residential", "mixed_use", "commercial", "street_multimodal", "park", "other"
    ]
    status: str
    parcels: list[str] = Field(default_factory=list)  # parcel PINs; may be empty pre-resolution
    geometry: dict | None = None  # GeoJSON geometry (site polygon or corridor line), EPSG:4326
    existing: ExistingConditions = Field(default_factory=ExistingConditions)
    proposed: ProposedProgram = Field(default_factory=ProposedProgram)
    extraction_confidence: dict[str, Confidence] = Field(default_factory=dict)
    extraction_quotes: dict[str, str] = Field(default_factory=dict)  # field -> verbatim ≤15 words
    extraction_notes: list[str] = Field(default_factory=list)  # e.g. document conflicts
    documents: list[Provenance] = Field(default_factory=list)


class MetricValue(BaseModel):
    name: str
    value: float
    unit: str
    low: float | None = None  # from propagating Assumption bounds
    high: float | None = None
    provenance: list[Provenance]
    assumptions: list[str] = Field(default_factory=list)  # Assumption.key references
    method: str  # one-line formula/method description
    headline: bool = False  # surfaced as a stat tile on the report page


class ModuleResult(BaseModel):
    module: ModuleName
    metrics: list[MetricValue]
    # labels of entries in ProjectEvaluation.map_layers this module produced
    map_layer_labels: list[str] = Field(default_factory=list)
    narrative_notes: list[str] = Field(default_factory=list)  # deterministic caveats
    assumptions: list[Assumption] = Field(default_factory=list)


class EvaluationBundle(BaseModel):
    """The full artifact of a run — what evaluate.py persists and audits."""
    spec: ProjectSpec
    results: list[ModuleResult] = Field(default_factory=list)
    map_layers: dict[str, dict] = Field(default_factory=dict)  # label -> GeoJSON FeatureCollection
    report_markdown: str | None = None

    def all_assumptions(self) -> list[Assumption]:
        """Deduped by key; first occurrence wins (modules share defaults)."""
        seen: dict[str, Assumption] = {}
        for result in self.results:
            for assumption in result.assumptions:
                seen.setdefault(assumption.key, assumption)
        return list(seen.values())

    def all_sources(self) -> list[Provenance]:
        """Deduped by (source_name, vintage) across spec documents and metrics."""
        seen: dict[tuple[str, str], Provenance] = {}
        for doc in self.spec.documents:
            seen.setdefault((doc.source_name, doc.vintage), doc)
        for result in self.results:
            for metric in result.metrics:
                for p in metric.provenance:
                    seen.setdefault((p.source_name, p.vintage), p)
        return list(seen.values())

    def all_metrics(self) -> list[MetricValue]:
        return [m for r in self.results for m in r.metrics]
