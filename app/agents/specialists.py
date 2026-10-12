from app.agents.base import JUDGE_SPEC, AgentSpec

ARCHITECTURE_AGENT = AgentSpec(
    name="Architecture Agent",
    role="software architect",
    description="You assess overall structure, boundaries, coupling, and fitness for the stated requirements.",
    focus=(
        "component boundaries and responsibilities, coupling/cohesion, API design, "
        "technology choices vs. requirements, over- or under-engineering, missing alternatives"
    ),
)

SECURITY_AGENT = AgentSpec(
    name="Security Agent",
    role="application security engineer",
    description="You look for ways the design can be attacked, abused or leak data.",
    focus=(
        "authentication and authorization, secrets management, encryption in transit/at rest, "
        "input validation, trust boundaries, multi-tenancy, PII/compliance, audit logging"
    ),
)

DATABASE_AGENT = AgentSpec(
    name="Database Agent",
    role="database and data-modelling expert",
    description="You evaluate how data is modelled, stored, queried and evolved.",
    focus=(
        "schema design, normalisation vs. denormalisation, indexing, transactions and consistency, "
        "choice of datastore, migrations, retention, backup and restore"
    ),
)

SCALABILITY_AGENT = AgentSpec(
    name="Scalability Agent",
    role="performance and scalability engineer",
    description="You estimate where the design will bottleneck as load and data grow.",
    focus=(
        "throughput and latency targets, horizontal vs. vertical scaling, statelessness, caching, "
        "queues and backpressure, hot spots, capacity planning, cost at scale"
    ),
)

RELIABILITY_AGENT = AgentSpec(
    name="Reliability Agent",
    role="site reliability engineer",
    description="You look for failure modes and how the system detects and recovers from them.",
    focus=(
        "single points of failure, retries/timeouts/circuit breakers, graceful degradation, "
        "SLOs, observability, deployment and rollback safety, disaster recovery"
    ),
)

SPECIALISTS: list[AgentSpec] = [
    ARCHITECTURE_AGENT,
    SECURITY_AGENT,
    DATABASE_AGENT,
    SCALABILITY_AGENT,
    RELIABILITY_AGENT,
]

ALL_SPECS: list[AgentSpec] = [*SPECIALISTS, JUDGE_SPEC]
