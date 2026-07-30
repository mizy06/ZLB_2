from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.inventory import SourceInventory
from backend.vnext.contracts.source import SourceObservationIR
from backend.vnext.source_inventory import enumerate_source_inventory
from backend.vnext.source_ir import parse_source


@dataclass(frozen=True, slots=True)
class SourceShadowResult:
    source_observation: SourceObservationIR
    source_envelope: ArtifactEnvelope
    source_inventory: SourceInventory
    inventory_envelope: ArtifactEnvelope


def run_source_shadow(
    path: Path,
    *,
    owner_id: str,
    store: LocalArtifactStore,
) -> SourceShadowResult:
    """Parse, archive, and independently inventory one source document."""

    source = parse_source(path)
    source_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.DOCUMENT_INTERPRETER,
        payload=source,
        producer=ArtifactProducerRef(
            producer_id="vnext-source-observer",
            producer_version="1.0.0",
            role=RuntimeRole.DOCUMENT_INTERPRETER,
        ),
    )
    source_ref = store.ref(source_envelope)
    inventory = enumerate_source_inventory(
        source,
        source_path=path,
        document_ir_ref=source_ref,
    )
    inventory_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.SOURCE_INVENTORY_AUDITOR,
        payload=inventory,
        producer=ArtifactProducerRef(
            producer_id="vnext-source-inventory-enumerator",
            producer_version="1.0.0",
            role=RuntimeRole.SOURCE_INVENTORY_AUDITOR,
        ),
        input_refs=(source_ref,),
    )
    return SourceShadowResult(
        source_observation=source,
        source_envelope=source_envelope,
        source_inventory=inventory,
        inventory_envelope=inventory_envelope,
    )
