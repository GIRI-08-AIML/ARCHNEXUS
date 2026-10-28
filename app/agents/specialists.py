from app.agents.base import JUDGE_SPEC, AgentSpec

ARCHITECTURE_AGENT = AgentSpec(
    name="Architecture Agent",
    role="software architect",
    description="You assess overall structure, boundaries, coupling, and fitness for the stated requirements.",
    focus=(
        "component boundaries and responsibilities, coupling/cohesion, API design, "
        "technology choices vs. requirements, over- or under-engineering, missing alternatives. "
        "Always check: whether the design can meet every goal the RFC states (for example a rule that something "
        "must never happen), and whether any step that must be all-or-nothing is done in separate steps"
    ),
)

SECURITY_AGENT = AgentSpec(
    name="Security Agent",
    role="application security engineer",
    description="You look for ways the design can be attacked, abused or leak data.",
    focus=(
        "authentication and authorization, secrets management, encryption in transit/at rest, "
        "input validation, trust boundaries, multi-tenancy, PII/compliance, audit logging. "
        "Always check: how long sessions and tokens last and whether they can be revoked, whether administrators "
        "and ordinary users are separated (own login, roles, extra verification), whether sensitive data is "
        "written to logs or stored unencrypted, where secrets are kept, and whether logins are protected against "
        "guessing and abuse (rate limits, lockout)"
    ),
)

DATABASE_AGENT = AgentSpec(
    name="Database Agent",
    role="database and data-modelling expert",
    description="You evaluate how data is modelled, stored, queried and evolved.",
    focus=(
        "schema design, normalisation vs. denormalisation, indexing, transactions and consistency, "
        "choice of datastore, migrations, retention, backup and restore. "
        "Always check: whether the RFC says how data is backed up and restored, whether the database runs on the "
        "same machine as the application, whether uniqueness and integrity rules are enforced by the database "
        "itself, whether files holding data are stored outside the database safely, and how schema changes are applied"
    ),
)

SCALABILITY_AGENT = AgentSpec(
    name="Scalability Agent",
    role="performance and scalability engineer",
    description="You estimate where the design will bottleneck as load and data grow.",
    focus=(
        "throughput and latency targets, horizontal vs. vertical scaling, statelessness, caching, "
        "queues and backpressure, hot spots, capacity planning, cost at scale. "
        "Always check: work that scans or loops over all records on a schedule, searches that cannot use an index, "
        "and a single machine or single instance that all load depends on"
    ),
)

RELIABILITY_AGENT = AgentSpec(
    name="Reliability Agent",
    role="site reliability engineer",
    description="You look for failure modes and how the system detects and recovers from them.",
    focus=(
        "single points of failure, retries/timeouts/circuit breakers, graceful degradation, "
        "SLOs, observability, deployment and rollback safety, disaster recovery. "
        "Always check: whether the RFC says where each component runs and whether a single machine, instance or "
        "database holds everything (a single point of failure), whether there are backups and a tested restore, "
        "how failures are detected and who is alerted, and how a bad release is rolled back"
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
