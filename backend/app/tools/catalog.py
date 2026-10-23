"""Single source of truth for what each known technology looks like in a compose stack."""

from dataclasses import dataclass, field

from app.schemas import Node


@dataclass(frozen=True)
class TechSpec:
    port: int
    image: str | None = None  # None -> custom service built from ./services/<id>
    env: dict[str, str] = field(default_factory=dict)  # VAR -> default value (.env.example)
    volume: str | None = None  # container data path for a named volume
    healthcheck: list[str] | None = None
    command: list[str] | None = None
    container_env: dict[str, str] = field(default_factory=dict)  # fixed env, "{id}" = service name
    connect_env: tuple[str, str] | None = None  # (VAR, url template) injected into dependants
    # Built services (image=None) get starter code from tools/starters.py and listen on their host
    # port, unless the stack fixes the container port (nginx serving static files listens on 80).
    container_port: int | None = None

    @property
    def custom(self) -> bool:
        return self.image is None


# Techs a user can pick per category in the download dialog (see tools/stack.py).
BACKEND_TECHS = ("node", "python", "go")
FRONTEND_TECHS = ("react", "static")
SQL_TECHS = ("postgres", "mysql")

TECH: dict[str, TechSpec] = {
    "postgres": TechSpec(
        port=5432,
        image="postgres:16-alpine",
        env={"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"},
        volume="/var/lib/postgresql/data",
        healthcheck=["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"],
        connect_env=(
            "DATABASE_URL",
            "postgresql://${POSTGRES_USER:-app}:${POSTGRES_PASSWORD:-app}@{id}:5432/${POSTGRES_DB:-app}",
        ),
    ),
    "mysql": TechSpec(
        port=3306,
        image="mysql:8.4",
        env={"MYSQL_ROOT_PASSWORD": "app", "MYSQL_DATABASE": "app"},
        volume="/var/lib/mysql",
        healthcheck=["CMD", "mysqladmin", "ping", "-h", "localhost"],
        connect_env=(
            "DATABASE_URL",
            "mysql://root:${MYSQL_ROOT_PASSWORD:-app}@{id}:3306/${MYSQL_DATABASE:-app}",
        ),
    ),
    "mongodb": TechSpec(
        port=27017, image="mongo:7", volume="/data/db", connect_env=("MONGO_URL", "mongodb://{id}:27017")
    ),
    "redis": TechSpec(
        port=6379,
        image="redis:7-alpine",
        volume="/data",
        healthcheck=["CMD", "redis-cli", "ping"],
        connect_env=("REDIS_URL", "redis://{id}:6379"),
    ),
    "rabbitmq": TechSpec(
        port=5672,
        image="rabbitmq:3-management",
        volume="/var/lib/rabbitmq",
        connect_env=("AMQP_URL", "amqp://guest:guest@{id}:5672"),
    ),
    "kafka": TechSpec(
        port=9092,
        image="apache/kafka:3.8.0",
        container_env={
            "KAFKA_NODE_ID": "1",
            "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": "PLAINTEXT://:9092,CONTROLLER://:9093",
            "KAFKA_ADVERTISED_LISTENERS": "PLAINTEXT://{id}:9092",
            "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
        },
        connect_env=("KAFKA_BROKERS", "{id}:9092"),
    ),
    "minio": TechSpec(
        port=9000,
        image="minio/minio:latest",
        volume="/data",
        command=["server", "/data"],
        env={"MINIO_ROOT_USER": "minio", "MINIO_ROOT_PASSWORD": "minio12345"},
        connect_env=("S3_ENDPOINT", "http://{id}:9000"),
    ),
    "nginx": TechSpec(port=80, image="nginx:alpine"),
    "node": TechSpec(port=3000),
    "python": TechSpec(port=8000),
    "go": TechSpec(port=8080),
    "react": TechSpec(port=5173),
    "static": TechSpec(port=8080, container_port=80),
}

# Aliases the models (or humans) commonly write.
TECH_ALIASES: dict[str, str] = {
    "postgresql": "postgres",
    "pg": "postgres",
    "psql": "postgres",
    "mariadb": "mysql",
    "mongo": "mongodb",
    "rabbit": "rabbitmq",
    "amqp": "rabbitmq",
    "s3": "minio",
    "express": "node",
    "nestjs": "node",
    "nextjs": "react",
    "next": "react",
    "vite": "react",
    "vue": "react",
    "angular": "react",
    "svelte": "react",
    "html": "static",
    "html/css/javascript": "static",
    "vanilla": "static",
    "nodejs": "node",
    "javascript": "node",
    "typescript": "node",
    "fastapi": "python",
    "flask": "python",
    "django": "python",
    "golang": "go",
    "gin": "go",
}

KIND_DEFAULT_TECH: dict[str, str] = {
    "database": "postgres",
    "cache": "redis",
    "queue": "rabbitmq",
    "gateway": "nginx",
    "frontend": "react",
    "service": "python",
    "unknown": "python",
}


def resolve_tech(node: Node) -> str | None:
    """Return the catalog key for a node, or None for external nodes (no container)."""
    if node.kind == "external":
        return None
    if node.tech:
        key = node.tech.strip().lower().replace(".", "").replace(" ", "")
        key = TECH_ALIASES.get(key, key)
        if key in TECH:
            return key
    return KIND_DEFAULT_TECH.get(node.kind, "python")


def env_var_name(node_id: str, suffix: str) -> str:
    return f"{node_id.upper().replace('-', '_')}_{suffix}"
